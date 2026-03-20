# hostapd Configurator

A Python/Flask web application for Debian 13 that generates correct, driver-aware `hostapd.conf` files for Linux wireless access points. Rather than requiring you to know which parameters are valid for your specific chipset, WiFi generation, and band combination, the app detects your hardware, enforces all inter-parameter dependencies automatically, and annotates the generated config with plain-English explanations for every setting.

---

## Table of Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Installation](#installation)
- [Running the App](#running-the-app)
- [Interface Detection](#interface-detection)
- [Driver & Chipset Database](#driver--chipset-database)
- [Bus Type Detection](#bus-type-detection)
- [Dependency Resolution](#dependency-resolution)
- [Inline Config Annotations](#inline-config-annotations)
- [Conflict Warnings & Undo](#conflict-warnings--undo)
- [hostapd Backend Selection](#hostapd-backend-selection)
- [Intel iwlwifi & LAR Restrictions](#intel-iwlwifi--lar-restrictions)
- [WiFi Generation Parameter Reference](#wifi-generation-parameter-reference)
- [Security Modes](#security-modes)
- [API Reference](#api-reference)
- [Deploying as a systemd Service](#deploying-as-a-systemd-service)
- [References](#references)

---

## Overview

Configuring `hostapd` correctly is harder than it looks. The set of valid parameters depends on your chipset, your kernel driver, your WiFi generation (802.11n/ac/ax/be), your band, and your channel width — and many combinations are silently invalid or will cause hostapd to fail with a cryptic error. For example:

- You cannot set `vht_oper_chwidth=1` (80 MHz) without also providing `vht_oper_centr_freq_seg0_idx` set to the correct center channel.
- `ieee80211ax=1` is only valid in hostapd 2.10+.
- 6 GHz AP operation requires WPA3-SAE (`wpa_key_mgmt=SAE` + `ieee80211w=2`) per the 802.11ax specification — WPA2-PSK is explicitly prohibited.
- Intel WiFi cards using `iwlwifi`/`iwlmvm` cannot start a 5 GHz AP with stock hostapd due to a firmware feature called LAR (Location Aware Regulatory).
- `ht_capab` tokens like `[HT40+]` should be stripped when the channel width is 20 MHz, and the specific capability flags differ per chipset.

This app handles all of that for you, generates a fully annotated config, and explains every auto-adjustment it makes.

---

## Requirements

All dependencies are available in the **Debian 13 (Trixie) apt repository** — no pip packages are required.

```bash
sudo apt install python3 python3-flask iw ethtool hostapd
```

| Package | Purpose |
|---|---|
| `python3-flask` | Web framework for the backend |
| `iw` | Reads nl80211 phy capabilities (`iw phy phyX info`) |
| `ethtool` | Reads the driver name for a given interface |
| `hostapd` | The access point daemon the config is written for |

---

## Installation

```bash
git clone <repo-url> hostapd-configurator
cd hostapd-configurator
```

Or simply copy the two files to any directory:

```
hostapd-configurator/
├── app.py
└── templates/
    └── index.html
```

No virtual environment is needed. No compiled extensions. No external CSS/JS frameworks are fetched at runtime — the UI is entirely self-contained.

---

## Running the App

The app reads `/sys/class/net`, runs `ethtool -i`, and calls `iw phy phyX info`, all of which require either root or a user with `CAP_NET_ADMIN`. The simplest approach:

```bash
sudo python3 app.py
```

Then open **http://localhost:5000** in your browser.

To bind to a specific address or port, edit the last line of `app.py`:

```python
app.run(host="0.0.0.0", port=5000, debug=False)
```

---

## Interface Detection

On startup (and when you click **↺ Refresh**), the app scans `/sys/class/net` for any interface that has a `wireless/` or `phy80211/` subdirectory — the standard kernel markers for wireless interfaces regardless of bus type.

For each wireless interface found, it collects:

- **Driver name** — via `ethtool -i <iface>`, with a sysfs fallback reading `/sys/class/net/<iface>/device/driver`
- **Bus type** — USB, PCIe, or SDIO, by resolving the sysfs device symlink (see [Bus Type Detection](#bus-type-detection))
- **phy number** — via `iw dev <iface> info` to find the nl80211 physical radio name
- **AP mode support** — confirmed from `iw phy phyX info` "Supported interface modes" block
- **Actual HT/VHT/HE capabilities** — parsed from the Band sections of `iw phy phyX info`
- **LAR status** — for `iwlwifi`, whether all 5 GHz channels are marked `NO_IR` (indicating LAR has set the world regdomain)
- **MAC address** — from `/sys/class/net/<iface>/address`

---

## Driver & Chipset Database

The app maintains a capability database (`DRIVER_CAPABILITIES` in `app.py`) for 24 known Linux wireless drivers. Each entry specifies the correct `ht_capab` string, `vht_capab` string, maximum channel width, supported bands, HE/EHT support flags, DFS capability, recommended module parameters, and recommended hostapd backend.

### Mediatek (USB)

| Driver key | Chipset | WiFi Gen | Bands |
|---|---|---|---|
| `mt7610u` | MT7610U | WiFi 5 | 5 GHz |
| `mt7612u` | MT7612U | WiFi 5 | 5 GHz |
| `mt7921u` | MT7921U | WiFi 6 | 2.4 / 5 GHz |
| `mt7925u` | MT7925U | WiFi 7 | 2.4 / 5 / 6 GHz |

USB Mediatek adapters require `options mt76_usb disable_usb_sg=1` in `/etc/modprobe.d/` for stable AP operation. This is included as a commented note in the generated config.

### Mediatek (PCIe — mt76 family)

| Driver key | Chipset | WiFi Gen | Bands |
|---|---|---|---|
| `mt7921e` | MT7921E / AMD RZ608 | WiFi 6 | 2.4 / 5 GHz |
| `mt7922` | MT7922 / AMD RZ616 | WiFi 6E | 2.4 / 5 GHz |
| `mt7915e` | MT7915E | WiFi 6 (4×4) | 2.4 / 5 GHz |
| `mt7916e` | MT7916E / Filogic 630 | WiFi 6E | 2.4 / 5 / 6 GHz |
| `mt7925e` | MT7925E | WiFi 7 | 2.4 / 5 / 6 GHz |
| `mt7996e` | MT7996E / Filogic 980 | WiFi 7 | 2.4 / 5 / 6 GHz |

The mt7915e and mt7916e are the chipsets commonly found in OpenWrt router M.2 slots and mini-PC WiFi cards. The mt7996e supports up to 320 MHz channel width on 6 GHz (EHT, requires hostapd 2.11+).

### Realtek (USB — rtw88 in-kernel)

| Driver key | Chipset | Min Kernel | Notes |
|---|---|---|---|
| `rtw88_8812au` | RTL8812AU | 6.14 | Needs `rtw_vht_enable=2` |
| `rtw88_8821au` | RTL8821AU | 6.14 | Needs `rtw_vht_enable=2` |
| `rtw88_8814au` | RTL8814AU | 6.16 | Needs `rtw_vht_enable=2` |
| `rtw88_8812bu` | RTL8812BU | in-tree | RPi4B: use `rtw_switch_usb_mode=2` |
| `rtw88_8821cu` | RTL8821CU | in-tree | Needs `rtw_vht_enable=2` |

### Realtek (PCIe — rtw89 in-kernel)

| Driver key | Chipset | WiFi Gen | Notes |
|---|---|---|---|
| `rtw89_8852be` | RTL8852BE | WiFi 6 | Common in laptops |
| `rtw89_8852ce` | RTL8852CE | WiFi 6E | Limited 6 GHz AP verification |
| `rtw89_8922ae` | RTL8922AE | WiFi 7 | Requires hostapd 2.11+ |

### Intel (PCIe — iwlwifi)

| Driver key | Chipset | WiFi Gen | Notes |
|---|---|---|---|
| `iwlwifi` | AX200/201/210/211, AC9260/8265 | WiFi 6 | **LAR restriction** — see below |

### Qualcomm Atheros

| Driver key | Chipset | Bus | WiFi Gen |
|---|---|---|---|
| `ath9k_htc` | AR9xxx | USB | WiFi 4 |
| `ath10k_usb` | QCA | USB | WiFi 5 |
| `ath10k_pci` | QCA | PCIe | WiFi 5 |
| `ath11k_pci` | QCA WiFi 6 | PCIe | WiFi 6 |

### Ralink / rt2x00

| Driver key | Chipset | Bus | WiFi Gen |
|---|---|---|---|
| `rt2800usb` | RT2870/RT3070 | USB | WiFi 4 |

---

## Bus Type Detection

The app determines whether each wireless interface is connected via **USB** or **PCIe** by resolving the sysfs device symlink:

```
/sys/class/net/<iface>/device → /sys/devices/...
```

PCIe devices resolve to a path containing `/pci0000:xx/...`. USB devices contain `/usb/...`. SDIO/MMC devices contain `/mmc...`. The bus type is shown as a badge on each interface card in the UI and recorded in the generated config header.

This distinction matters because:

- USB-specific module parameters (`disable_usb_sg`, `rtw_switch_usb_mode`) are only surfaced for USB interfaces
- PCIe-only drivers (`mt7915e`, `mt7996e`, `rtw89_*`) are never matched to USB bus interfaces
- Power budget warnings from morrownr/USB-WiFi are only applicable to USB

---

## Dependency Resolution

When you click **Generate**, the app runs a ten-rule dependency resolver (`validate_and_resolve` in `app.py`) that evaluates your chosen parameters against hardware capabilities and protocol constraints. Rules run in order so that earlier coercions feed correctly into later checks.

### Rule 1 — WiFi generation cap

The requested WiFi generation is clamped to the driver's maximum supported generation. Requesting WiFi 6 on an `rt2800usb` (WiFi 4 max) resolves to WiFi 4.

### Rule 2 — Channel width limits

Three sub-checks apply in sequence:

1. **Hardware cap** — width is clamped to the driver's `max_channel_width`.
2. **Band cap** — 80 MHz and 160 MHz are impossible on 2.4 GHz; width is clamped to 40 MHz.
3. **WiFi 4 cap** — 802.11n (WiFi 4) maximum is 40 MHz. 80/160 MHz requires VHT (`ieee80211ac=1`).
4. **2.4 GHz + WiFi 5 cap** — 802.11ac/VHT is a 5 GHz-only standard; WiFi gen is reduced to 4 if band is 2.4 GHz.
5. **2.4 GHz + HE cap** — WiFi 6 on 2.4 GHz is valid but limited to 40 MHz per spec.

### Rule 3 — Channel number validity

The selected channel must be a legitimate channel number for the chosen band. Invalid channels are reset to band defaults (36 for 5 GHz, 6 for 2.4 GHz, 1 for 6 GHz).

### Rule 4 — 160 MHz primary channel validity

A 160 MHz channel width requires the primary channel to be one of the valid 160 MHz block starting channels (36, 40, 44, 48, 52, 56, 60, 64, 100–128, 149–161). Any other channel is reset to 36.

### Rule 5 — 6 GHz requires WPA3-SAE

The 802.11ax specification (§9.4.2.170) explicitly prohibits WPA2-PSK on 6 GHz AP operation. If the band is 6 GHz and security is not WPA3-SAE or WPA3-SAE Transition, it is automatically upgraded to WPA3-SAE.

### Rule 6 — WPA3 MFP requirements (derived)

WPA3-SAE mandates `ieee80211w=2` (PMF required). WPA3-SAE Transition requires `ieee80211w=1` (PMF capable). These are derived values annotated in the config but not flagged as user-visible changes since they are not user-settable fields.

### Rule 7 — HE/VHT/HT prerequisite chain

IEEE 802.11ax (HE/WiFi 6) requires 802.11ac (VHT/WiFi 5) which requires 802.11n (HT/WiFi 4). If the driver has no `vht_capab` but WiFi 5 is requested on 5 GHz, the gen is reduced to 4. If the driver has no `he_capab` but WiFi 6 is requested, the gen is reduced to the driver maximum.

### Rule 8 — HE BSS color range

`he_bss_color` must be in the range 1–63 per 802.11ax §9.4.2.261. Out-of-range values are clamped.

### Rule 9 — iwlwifi 5 GHz backend enforcement

Intel `iwlwifi`/`iwlmvm` cards cannot start a 5 GHz AP with stock Debian hostapd due to the LAR restriction. If the driver is `iwlwifi`, the band is 5 GHz, and the selected backend is `debian`, the backend is automatically switched to `lar_patched`.

### Rule 10 — WiFi 7 requires git hostapd

`ieee80211be=1` (EHT) requires hostapd 2.11 or later. Debian 13 ships 2.10. If WiFi 7 is selected and the backend is not `git_head`, it is automatically switched.

---

## Inline Config Annotations

Every line in the generated `hostapd.conf` carries an inline comment explaining its provenance. Three annotation tiers are color-coded in the output panel:

**Blue — User selected**
```
wpa_key_mgmt=WPA-PSK  # ← user selected
```
The value came directly from the form as you set it.

**Amber/italic — Auto-adjusted**
```
channel_width=40  # ← AUTO-ADJUSTED from '80' because Band = 2.4GHz
```
The value was changed by the dependency resolver from what you originally entered. The annotation states what the original value was and which setting caused the change.

**Dim gray/italic — Derived**
```
hw_mode=g  # ← derived: 'a' for 5/6 GHz, 'g' for 2.4 GHz — set by band=2.4GHz
ieee80211d=1  # ← derived: advertise country code & allowed channels per 802.11d; required with country_code
vht_oper_centr_freq_seg0_idx=42  # ← derived: center channel for 80 MHz block starting at channel 36; formula: primary+6 for 80 MHz, primary+14 for 160 MHz
```
Calculated or fixed values that have no user-settable counterpart. The annotation explains the technical reason the value exists and how it was computed.

---

## Conflict Warnings & Undo

When the dependency resolver changes a value you explicitly set, a warning banner appears above the config output. Each banner includes:

- **What changed** — the field name, original value, and resolved value, shown as labeled chips
- **Why it changed** — a plain-English explanation citing the relevant specification or hardware constraint
- **What triggered it** — which other setting caused the change
- **↩ Undo this change** button — restores the exact form state from before the generate call and re-generates, so you can evaluate the original combination
- **Dismiss** button — acknowledges the warning without reverting

The undo system works by snapshotting the entire form state immediately before `generate()` runs. Each warning in the banner area is keyed by `field:from_val:to_val:cause_field`, preventing the same logical conflict from being stacked multiple times across repeated generates.

Dismissed warnings do not reappear until the conflicting combination is submitted again (i.e. if you undo, fix the conflict yourself, and re-generate cleanly, no banner appears).

---

## hostapd Backend Selection

The app tracks three hostapd binary variants, each with a known installation path. The UI shows whether each binary is present on your system and provides build instructions for any that are missing.

### `debian` — Debian 13 stock

- **Path**: `/usr/sbin/hostapd`
- **Version**: 2.10
- **Install**: `sudo apt install hostapd`
- **Use when**: Any non-Intel chipset on 2.4 GHz or 5 GHz; any Intel chipset on **2.4 GHz only**

This is the default. It supports WiFi 4, 5, and 6 (802.11n/ac/ax). It does not include the Intel LAR scan-before-start patch, so it will fail to start a 5 GHz AP on any iwlwifi card.

### `lar_patched` — LAR-aware hostapd

- **Path**: `/usr/local/sbin/hostapd-lar`
- **Version**: 2.10 + tildearrow patch
- **Use when**: Intel iwlwifi card, 5 GHz AP

This is hostapd 2.10 rebuilt from Debian source with [the tildearrow LAR patch](https://tildearrow.org/storage/hostapd-2.10-lar.patch) applied. The patch makes hostapd issue a passive scan before fetching the channel list, giving the Intel firmware's LAR subsystem time to detect a valid country code from nearby APs before the AP interface is configured. It also incorporates the noscan patch, which prevents hostapd's own periodic scanning from resetting the regdomain back to "00" after startup.

Build from Debian source:

```bash
sudo apt build-dep hostapd
apt source hostapd && cd hostapd-*/
wget https://tildearrow.org/storage/hostapd-2.10-lar.patch
patch -p1 < hostapd-2.10-lar.patch
dpkg-buildpackage -us -uc -b
sudo dpkg -i ../hostapd_*.deb
sudo cp /usr/sbin/hostapd /usr/local/sbin/hostapd-lar
```

### `git_head` — Upstream hostapd (WiFi 7 / EHT)

- **Path**: `/usr/local/sbin/hostapd-git`
- **Version**: 2.11+
- **Use when**: WiFi 7 (802.11be/EHT); mt7996e, mt7925u/e, rtw89_8922ae

Required for `ieee80211be=1`. Debian 13 ships 2.10 which does not include the EHT code path.

Build from upstream:

```bash
sudo apt install -y build-essential libnl-3-dev libnl-genl-3-dev libssl-dev pkg-config
git clone git://w1.fi/hostap.git && cd hostap/hostapd
cp defconfig .config
# Edit .config: uncomment CONFIG_IEEE80211BE=y and CONFIG_ACS=y
make -j$(nproc)
sudo cp hostapd /usr/local/sbin/hostapd-git
```

The dependency resolver auto-selects the recommended backend per driver. If the selected backend binary is not found at its expected path, the UI shows the binary as unavailable (in amber) and displays the build instructions inline.

---

## Intel iwlwifi & LAR Restrictions

Intel WiFi cards using the `iwlmvm` firmware driver implement a feature called **LAR (Location Aware Regulatory)**. LAR determines the card's regulatory domain by scanning nearby access points and inferring their country, rather than accepting a user-specified `country_code`. This is meant to ensure automatic regulatory compliance, but it creates a fundamental problem for AP mode:

1. When hostapd initializes the wireless interface, the card resets its regdomain to `00` (the world regulatory domain).
2. The world regdomain marks all 5 GHz channels as `NO-IR` (no-initiate-radiation), meaning the driver refuses to transmit on them.
3. Stock hostapd fetches the available channel list **before** performing any scan, so LAR never gets the opportunity to detect a real country code and unlock the 5 GHz channels.
4. Result: hostapd cannot start a 5 GHz AP on any iwlwifi card with stock hostapd.

The `lar_disable=1` module parameter that previously worked around this was removed in Linux 5.4 because newer Intel firmware crashed when LAR was disabled. There is no kernel-level solution available today.

The **LAR-patched hostapd** resolves this by inserting a passive scan step before `hostapd_get_hw_features()`, giving LAR time to update the country code. A second patch (noscan) prevents hostapd's own scanning callbacks from resetting the regdomain back to `00` after startup.

**Important caveats for the LAR patch:**

- It requires at least one visible nearby 5 GHz access point for LAR to detect a valid country. It will not work in an isolated RF environment with no other APs.
- It is not 100% reliable on the first attempt; restarting hostapd usually resolves transient failures.
- It does not affect 2.4 GHz operation, which works normally with stock hostapd on all iwlwifi cards.
- 6 GHz AP is not supported by iwlwifi in any configuration.

The generated config includes a condensed warning when iwlwifi + 5 GHz is detected, and the full technical explanation is embedded as a comment block at the bottom of the config for reference.

---

## WiFi Generation Parameter Reference

The following table summarizes which `hostapd.conf` parameters are active at each WiFi generation. Each generation **adds** to the previous — you cannot have 802.11ax without also having 802.11ac and 802.11n.

| Parameter | WiFi 4 | WiFi 5 | WiFi 6 | WiFi 7 |
|---|:---:|:---:|:---:|:---:|
| `ieee80211n=1` | ✓ | ✓ | ✓ | ✓ |
| `wmm_enabled=1` | ✓ | ✓ | ✓ | ✓ |
| `ht_capab` | ✓ | ✓ | ✓ | ✓ |
| `ieee80211ac=1` | | ✓ | ✓ | ✓ |
| `vht_oper_chwidth` | | ✓ | ✓ | ✓ |
| `vht_oper_centr_freq_seg0_idx` | | ✓ (≥80 MHz) | ✓ (≥80 MHz) | ✓ (≥80 MHz) |
| `vht_capab` | | ✓ | ✓ | ✓ |
| `ieee80211ax=1` | | | ✓ | ✓ |
| `he_oper_chwidth` | | | ✓ (5/6 GHz) | ✓ |
| `he_oper_centr_freq_seg0_idx` | | | ✓ (≥80 MHz) | ✓ |
| `he_bss_color` | | | ✓ | ✓ |
| `ieee80211be=1` | | | | ✓ |

### Center channel calculation

The `vht_oper_centr_freq_seg0_idx` and `he_oper_centr_freq_seg0_idx` values are calculated automatically from the primary channel and channel width. The formula is:

- **80 MHz**: center = the center of the 80 MHz block containing the primary channel (e.g. channels 36–48 → center 42)
- **160 MHz**: center = the center of the 160 MHz block containing the primary channel (e.g. channels 36–64 → center 50)

The full lookup table is encoded in `_center_channel()` in `app.py`.

---

## Security Modes

| Mode | `wpa_key_mgmt` | `ieee80211w` | Notes |
|---|---|---|---|
| **Open** | *(none)* | *(none)* | No authentication. `auth_algs=1`. |
| **WPA2-PSK** | `WPA-PSK` | *(omitted)* | Standard AES-CCMP. `auth_algs=1`. |
| **WPA3-SAE Transition** | `SAE WPA-PSK` | `1` (capable) | Mixed WPA2+WPA3. Allows both old and new clients. `auth_algs=3`. |
| **WPA3-SAE** | `SAE` | `2` (required) | Full WPA3. PMF mandatory. `auth_algs=3`. Required for 6 GHz. |

`rsn_pairwise=CCMP` is set for all authenticated modes. TKIP is not generated — it is a broken cipher and has been deprecated from the 802.11 standard.

`sae_require_mfp=1` is added for all WPA3 modes. SAE group 19 (P-256) is the default and is universally supported; groups 20 and 21 are commented for reference.

---

## API Reference

All endpoints accept and return JSON.

### `GET /api/interfaces`

Returns a list of detected wireless interfaces with their driver, bus type, capabilities, and AP support status.

```json
[
  {
    "interface": "wlan0",
    "driver": "mt7921u",
    "driver_label": "Mediatek MT7921U (WiFi 6, USB)",
    "bus_type": "usb",
    "mac": "aa:bb:cc:dd:ee:ff",
    "bands": ["2.4GHz", "5GHz"],
    "ap_support": true,
    "iwlwifi_lar": false,
    "recommended_backend": "debian",
    "capabilities": { ... }
  }
]
```

### `GET /api/backends`

Returns the three hostapd backend variants with availability status (whether the binary exists at the expected path) and build notes.

### `GET /api/channels?band=5GHz&iwlwifi=false`

Returns valid channel numbers for the specified band. When `iwlwifi=true`, the 5 GHz list is filtered to non-DFS channels only (the DFS channels are unreliable with iwlwifi even with the LAR patch).

### `GET /api/capabilities/<driver>`

Returns the full capability entry for a given driver key from the database.

### `POST /api/validate`

Accepts a params object and returns the resolved params after all dependency rules have been applied, plus a `changes` array describing every coercion that occurred.

```json
{
  "resolved": { "wifi_gen": "4", "channel_width": "40", ... },
  "changes": [
    {
      "field": "wifi_gen",
      "from_val": "6",
      "to_val": "4",
      "cause_field": "driver",
      "cause_val": "rt2800usb",
      "reason": "The Ralink RT2870/RT3070 driver only supports up to WiFi 4...",
      "severity": "warning"
    }
  ]
}
```

### `POST /api/generate`

Accepts a params object (with an optional `_orig` key containing the pre-adjustment params for provenance tracking) and returns the generated `hostapd.conf` text plus the changes array.

```json
{
  "config": "# hostapd.conf ...\ninterface=wlan0\n...",
  "changes": [ ... ]
}
```

---

## Deploying as a systemd Service

To run the configurator persistently, install it system-wide and register it with systemd:

```bash
sudo cp -r hostapd-configurator /opt/
```

Create `/etc/systemd/system/hostapd-cfg.service`:

```ini
[Unit]
Description=hostapd Configurator
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/hostapd-configurator/app.py
WorkingDirectory=/opt/hostapd-configurator
User=root
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hostapd-cfg
```

The service binds to `0.0.0.0:5000` by default. If you want to restrict access to localhost only, change the `app.run()` call in `app.py` to `host="127.0.0.1"` and use an nginx or caddy reverse proxy for external access.

---

## References

- [morrownr/USB-WiFi](https://github.com/morrownr/USB-WiFi) — Authoritative hostapd configuration examples for Linux USB WiFi adapters, chipset capability notes, AP mode guides for WiFi 4 through WiFi 7
- [hostapd reference configuration](https://w1.fi/cgit/hostap/plain/hostapd/hostapd.conf) — The canonical hostapd.conf with documentation for every parameter
- [Linux Wireless documentation](https://wireless.docs.kernel.org/) — mac80211, nl80211, regulatory, iw usage
- [tildearrow LAR patch](https://tildearrow.org/?p=post&month=7&year=2022&item=lar) — Analysis of the Intel iwlwifi LAR problem and the scan-before-start hostapd patch
- [kernel.org iwlwifi driver documentation](https://wireless.wiki.kernel.org/en/users/drivers/iwlwifi) — Official Intel WiFi driver documentation including LAR notes
- [IEEE 802.11ax-2021 specification](https://standards.ieee.org/ieee/802.11ax/7189/) — 6 GHz WPA3 mandate (§9.4.2.170), HE BSS color (§9.4.2.261), PMF requirements
