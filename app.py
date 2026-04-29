#!/usr/bin/env python3
"""
hostapd Configuration Generator
Python/Flask backend for Debian 13.

Features:
  - Bus-type detection (USB vs PCIe) via sysfs
  - Comprehensive driver capability DB (USB + PCIe Mediatek, Realtek, Intel, Atheros, Ralink)
  - Full iwlwifi LAR/regulatory limitation awareness with workaround notes
  - Hostapd backend abstraction (stock Debian, LAR-patched, compiled-from-git)
  - Correct hostapd.conf generation with per-WiFi-gen parameter interdependencies
"""

import subprocess
import re
import os
from pathlib import Path
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# ── Hostapd backend registry ──────────────────────────────────────────────────
HOSTAPD_BACKENDS = {
    "debian": {
        "label": "Debian 13 stock (apt)",
        "path": "/usr/sbin/hostapd",
        "version_min": "2.10",
        "description": (
            "The hostapd package shipped with Debian 13 (Trixie). "
            "Supports WiFi 4/5/6 (802.11n/ac/ax). Sufficient for all non-Intel chipsets. "
            "Does NOT include the LAR scan-before-start patch for iwlwifi 5 GHz AP."
        ),
        "iwlwifi_5g_ok": False,
        "wifi7_ok": False,
    },
    "lar_patched": {
        "label": "LAR-patched hostapd (tildearrow patch)",
        "path": "/usr/local/sbin/hostapd-lar",
        "version_min": "2.10",
        "description": (
            "hostapd 2.10 rebuilt with the tildearrow LAR scan-before-start patch. "
            "Makes hostapd scan for nearby APs before fetching the channel list, "
            "allowing LAR to set a proper country code before the AP starts. "
            "Also includes the noscan patch. Required for iwlwifi 5 GHz AP mode."
        ),
        "iwlwifi_5g_ok": True,
        "wifi7_ok": False,
        "build_notes": (
            "sudo apt build-dep hostapd\n"
            "apt source hostapd && cd hostapd-*/\n"
            "wget https://tildearrow.org/storage/hostapd-2.10-lar.patch\n"
            "patch -p1 < hostapd-2.10-lar.patch\n"
            "dpkg-buildpackage -us -uc -b\n"
            "sudo dpkg -i ../hostapd_*.deb\n"
            "sudo cp /usr/sbin/hostapd /usr/local/sbin/hostapd-lar"
        ),
    },
    "git_head": {
        "label": "hostapd upstream git (WiFi 7 / EHT)",
        "path": "/usr/local/sbin/hostapd-git",
        "version_min": "2.11",
        "description": (
            "hostapd built from w1.fi git HEAD. "
            "Required for full IEEE 802.11be (WiFi 7 / EHT) support. "
            "Also recommended for mt7925 and rtw89 on 6 GHz. "
            "Debian 13 ships 2.10; WiFi 7 needs 2.11+."
        ),
        "iwlwifi_5g_ok": False,
        "wifi7_ok": True,
        "build_notes": (
            "sudo apt install -y build-essential libnl-3-dev libnl-genl-3-dev libssl-dev pkg-config\n"
            "git clone git://w1.fi/hostap.git && cd hostap/hostapd\n"
            "cp defconfig .config\n"
            "# Enable CONFIG_IEEE80211BE=y, CONFIG_ACS=y in .config\n"
            "make -j$(nproc)\n"
            "sudo cp hostapd /usr/local/sbin/hostapd-git"
        ),
    },
}

# ── Driver capability database ────────────────────────────────────────────────
DRIVER_CAPABILITIES = {

    # ── Mediatek USB ──────────────────────────────────────────────────────────
    "mt7921u": {
        "label": "Mediatek MT7921U (WiFi 6, USB)",
        "wifi_gen": 6,
        "bus_types": ["usb"],
        "bands": ["2.4GHz", "5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[LDPC][HT40+][HT40-][GF][SHORT-GI-20][SHORT-GI-40][TX-STBC][RX-STBC1][MAX-AMSDU-7935]",
        "vht_capab": "[MAX-MPDU-11454][RXLDPC][SHORT-GI-80][TX-STBC-2BY1][SU-BEAMFORMEE][MU-BEAMFORMEE][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN][RX-STBC-1][BF-ANTENNA-4][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": True, "he_bss_color": True, "ap_mode": True, "dfs": True,
        "module_params": ["options mt76_usb disable_usb_sg=1"],
        "recommended_backend": "debian",
    },
    "mt7925u": {
        "label": "Mediatek MT7925U (WiFi 7, USB)",
        "wifi_gen": 7,
        "bus_types": ["usb"],
        "bands": ["2.4GHz", "5GHz", "6GHz"],
        "max_channel_width": 160,
        "ht_capab": "[LDPC][HT40+][HT40-][GF][SHORT-GI-20][SHORT-GI-40][TX-STBC][RX-STBC1][MAX-AMSDU-7935]",
        "vht_capab": "[VHT160][RXLDPC][SHORT-GI-80][SHORT-GI-160][TX-STBC-2BY1][SU-BEAMFORMEE][MU-BEAMFORMEE][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN][RX-STBC-1][BF-ANTENNA-4][MAX-MPDU-11454][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": True, "eht_capab": True, "he_bss_color": True, "ap_mode": True, "dfs": True,
        "module_params": ["options mt76_usb disable_usb_sg=1"],
        "recommended_backend": "git_head",
        "note": "WiFi 7 EHT requires hostapd 2.11+ (upstream git). 6 GHz AP requires WPA3-SAE (ieee80211w=2).",
    },
    "mt7612u": {
        "label": "Mediatek MT7612U (WiFi 5 AC1200, USB)",
        "wifi_gen": 5,
        "bus_types": ["usb"],
        "bands": ["5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[HT40+][HT40-][GF][SHORT-GI-20][SHORT-GI-40]",
        "vht_capab": "[RXLDPC][SHORT-GI-80][TX-STBC-2BY1][RX-STBC-1][MAX-A-MPDU-LEN-EXP3][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN]",
        "he_capab": False, "ap_mode": True, "dfs": True,
        "module_params": ["options mt76_usb disable_usb_sg=1"],
        "recommended_backend": "debian",
    },
    "mt7610u": {
        "label": "Mediatek MT7610U (WiFi 5 AC600, USB)",
        "wifi_gen": 5,
        "bus_types": ["usb"],
        "bands": ["5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[HT40+][HT40-][GF][SHORT-GI-20][SHORT-GI-40]",
        "vht_capab": "[SHORT-GI-80][MAX-A-MPDU-LEN-EXP3][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN]",
        "he_capab": False, "ap_mode": True, "dfs": True,
        "module_params": ["options mt76_usb disable_usb_sg=1"],
        "recommended_backend": "debian",
    },

    # ── Mediatek PCIe ─────────────────────────────────────────────────────────
    "mt7921e": {
        "label": "Mediatek MT7921E / AMD RZ608 (WiFi 6, PCIe)",
        "wifi_gen": 6,
        "bus_types": ["pcie"],
        "bands": ["2.4GHz", "5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[LDPC][HT40+][HT40-][GF][SHORT-GI-20][SHORT-GI-40][TX-STBC][RX-STBC1][MAX-AMSDU-7935]",
        "vht_capab": "[MAX-MPDU-11454][RXLDPC][SHORT-GI-80][TX-STBC-2BY1][SU-BEAMFORMEE][MU-BEAMFORMEE][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN][RX-STBC-1][BF-ANTENNA-4][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": True, "he_bss_color": True, "ap_mode": True, "dfs": True,
        "recommended_backend": "debian",
    },
    "mt7922": {
        "label": "Mediatek MT7922 / AMD RZ616 (WiFi 6E, PCIe)",
        "wifi_gen": 6,
        "bus_types": ["pcie"],
        "bands": ["2.4GHz", "5GHz"],
        "max_channel_width": 160,
        "ht_capab": "[LDPC][HT40+][HT40-][GF][SHORT-GI-20][SHORT-GI-40][TX-STBC][RX-STBC1][MAX-AMSDU-7935]",
        "vht_capab": "[MAX-MPDU-11454][VHT160][RXLDPC][SHORT-GI-80][SHORT-GI-160][TX-STBC-2BY1][SU-BEAMFORMEE][MU-BEAMFORMEE][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN][RX-STBC-1][BF-ANTENNA-4][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": True, "he_bss_color": True, "ap_mode": True, "dfs": True,
        "recommended_backend": "debian",
        "note": "6 GHz hardware present but AP on 6 GHz requires WPA3-SAE (ieee80211w=2).",
    },
    "mt7915e": {
        "label": "Mediatek MT7915E (WiFi 6 4x4, PCIe)",
        "wifi_gen": 6,
        "bus_types": ["pcie"],
        "bands": ["2.4GHz", "5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[LDPC][HT40+][HT40-][GF][SHORT-GI-20][SHORT-GI-40][TX-STBC][RX-STBC1][MAX-AMSDU-7935]",
        "vht_capab": "[MAX-MPDU-11454][RXLDPC][SHORT-GI-80][TX-STBC-2BY1][SU-BEAMFORMEE][MU-BEAMFORMEE][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN][RX-STBC-1][BF-ANTENNA-4][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": True, "he_bss_color": True, "ap_mode": True, "dfs": True,
        "recommended_backend": "debian",
        "note": "Common in OpenWrt routers and M.2 cards. Supports up to 4 SSIDs (multi-BSS). Excellent AP stability.",
    },
    "mt7916e": {
        "label": "Mediatek MT7916E / Filogic 630 (WiFi 6E, PCIe)",
        "wifi_gen": 6,
        "bus_types": ["pcie"],
        "bands": ["2.4GHz", "5GHz", "6GHz"],
        "max_channel_width": 160,
        "ht_capab": "[LDPC][HT40+][HT40-][GF][SHORT-GI-20][SHORT-GI-40][TX-STBC][RX-STBC1][MAX-AMSDU-7935]",
        "vht_capab": "[MAX-MPDU-11454][VHT160][RXLDPC][SHORT-GI-80][SHORT-GI-160][TX-STBC-2BY1][SU-BEAMFORMEE][MU-BEAMFORMEE][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN][RX-STBC-1][BF-ANTENNA-4][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": True, "he_bss_color": True, "ap_mode": True, "dfs": True,
        "recommended_backend": "debian",
        "note": "True WiFi 6E — includes 6 GHz. 6 GHz AP requires WPA3-SAE mandatory (ieee80211w=2).",
    },
    "mt7996e": {
        "label": "Mediatek MT7996E / Filogic 980 (WiFi 7, PCIe)",
        "wifi_gen": 7,
        "bus_types": ["pcie"],
        "bands": ["2.4GHz", "5GHz", "6GHz"],
        "max_channel_width": 320,
        "ht_capab": "[LDPC][HT40+][HT40-][GF][SHORT-GI-20][SHORT-GI-40][TX-STBC][RX-STBC1][MAX-AMSDU-7935]",
        "vht_capab": "[MAX-MPDU-11454][VHT160][RXLDPC][SHORT-GI-80][SHORT-GI-160][TX-STBC-2BY1][SU-BEAMFORMEE][MU-BEAMFORMEE][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN][RX-STBC-1][BF-ANTENNA-4][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": True, "eht_capab": True, "he_bss_color": True, "ap_mode": True, "dfs": True,
        "recommended_backend": "git_head",
        "note": "WiFi 7 tri-band PCIe. Requires hostapd 2.11+ (upstream git) for EHT. 6 GHz AP requires WPA3-SAE.",
    },
    "mt7925e": {
        "label": "Mediatek MT7925E (WiFi 7, PCIe M.2)",
        "wifi_gen": 7,
        "bus_types": ["pcie"],
        "bands": ["2.4GHz", "5GHz", "6GHz"],
        "max_channel_width": 160,
        "ht_capab": "[LDPC][HT40+][HT40-][GF][SHORT-GI-20][SHORT-GI-40][TX-STBC][RX-STBC1][MAX-AMSDU-7935]",
        "vht_capab": "[VHT160][RXLDPC][SHORT-GI-80][SHORT-GI-160][TX-STBC-2BY1][SU-BEAMFORMEE][MU-BEAMFORMEE][RX-ANTENNA-PATTERN][TX-ANTENNA-PATTERN][RX-STBC-1][BF-ANTENNA-4][MAX-MPDU-11454][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": True, "eht_capab": True, "he_bss_color": True, "ap_mode": True, "dfs": True,
        "recommended_backend": "git_head",
        "note": "M.2 form factor. WiFi 7 EHT requires hostapd 2.11+. 6 GHz AP requires WPA3-SAE mandatory.",
    },

    # ── Realtek USB (rtw88) ───────────────────────────────────────────────────
    "rtw88_8812au": {
        "label": "Realtek RTL8812AU (rtw88, WiFi 5, USB) — kernel 6.14+",
        "wifi_gen": 5,
        "bus_types": ["usb"],
        "bands": ["5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[HT40+][HT40-][SHORT-GI-20][SHORT-GI-40][MAX-AMSDU-7935]",
        "vht_capab": "[MAX-MPDU-11454][SHORT-GI-80][TX-STBC-2BY1][RX-STBC-1][HTC-VHT][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": False, "ap_mode": True, "dfs": False,
        "module_params": ["options rtw88_8812au rtw_vht_enable=2 rtw_switch_usb_mode=1"],
        "recommended_backend": "debian",
        "note": "In-kernel since Linux 6.14. [TX-STBC-2BY1] may cause instability — remove if drops occur.",
    },
    "rtw88_8821au": {
        "label": "Realtek RTL8821AU (rtw88, WiFi 5 AC600, USB) — kernel 6.14+",
        "wifi_gen": 5,
        "bus_types": ["usb"],
        "bands": ["5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[HT40+][HT40-][SHORT-GI-20][SHORT-GI-40][MAX-AMSDU-7935]",
        "vht_capab": "[MAX-MPDU-11454][SHORT-GI-80][RX-STBC-1][HTC-VHT][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": False, "ap_mode": True, "dfs": False,
        "module_params": ["options rtw88_8821au rtw_vht_enable=2"],
        "recommended_backend": "debian",
    },
    "rtw88_8814au": {
        "label": "Realtek RTL8814AU (rtw88, WiFi 5 AC1900, USB) — kernel 6.16+",
        "wifi_gen": 5,
        "bus_types": ["usb"],
        "bands": ["5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[LDPC][HT40+][HT40-][SHORT-GI-20][SHORT-GI-40][MAX-AMSDU-7935][DSSS_CCK-40]",
        "vht_capab": "[MAX-MPDU-11454][RXLDPC][SHORT-GI-80][TX-STBC-2BY1][RX-STBC-1][HTC-VHT][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": False, "ap_mode": True, "dfs": False,
        "module_params": ["options rtw88_8814au rtw_vht_enable=2 rtw_switch_usb_mode=1"],
        "recommended_backend": "debian",
        "note": "In-kernel since Linux 6.16.",
    },
    "rtw88_8812bu": {
        "label": "Realtek RTL8812BU (rtw88, WiFi 5, USB)",
        "wifi_gen": 5,
        "bus_types": ["usb"],
        "bands": ["5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[LDPC][HT40+][HT40-][SHORT-GI-20][SHORT-GI-40][MAX-AMSDU-7935]",
        "vht_capab": "[MAX-MPDU-11454][SHORT-GI-80][TX-STBC-2BY1][RX-STBC-1][HTC-VHT][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": False, "ap_mode": True, "dfs": False,
        "module_params": ["options rtw88_8812bu rtw_vht_enable=2 rtw_switch_usb_mode=2"],
        "recommended_backend": "debian",
        "note": "On RPi 4B, use rtw_switch_usb_mode=2 (USB2) to avoid dropped connections.",
    },
    "rtw88_8821cu": {
        "label": "Realtek RTL8821CU (rtw88, WiFi 5 AC600, USB)",
        "wifi_gen": 5,
        "bus_types": ["usb"],
        "bands": ["5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[HT40+][HT40-][SHORT-GI-20][SHORT-GI-40][MAX-AMSDU-7935]",
        "vht_capab": "[MAX-MPDU-11454][SHORT-GI-80][HTC-VHT][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": False, "ap_mode": True, "dfs": False,
        "module_params": ["options rtw88_8821cu rtw_vht_enable=2"],
        "recommended_backend": "debian",
    },

    # ── Realtek PCIe (rtw89) ──────────────────────────────────────────────────
    "rtw89_8852be": {
        "label": "Realtek RTL8852BE (rtw89, WiFi 6, PCIe)",
        "wifi_gen": 6,
        "bus_types": ["pcie"],
        "bands": ["2.4GHz", "5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[LDPC][HT40+][HT40-][SHORT-GI-20][SHORT-GI-40][TX-STBC][RX-STBC1][MAX-AMSDU-7935]",
        "vht_capab": "[MAX-MPDU-11454][RXLDPC][SHORT-GI-80][TX-STBC-2BY1][RX-STBC-1][SU-BEAMFORMEE][MU-BEAMFORMEE][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": True, "he_bss_color": True, "ap_mode": True, "dfs": True,
        "recommended_backend": "debian",
        "note": "Common in laptops (Acer, ASUS, Lenovo). Good AP support via rtw89.",
    },
    "rtw89_8852ce": {
        "label": "Realtek RTL8852CE (rtw89, WiFi 6E, PCIe)",
        "wifi_gen": 6,
        "bus_types": ["pcie"],
        "bands": ["2.4GHz", "5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[LDPC][HT40+][HT40-][SHORT-GI-20][SHORT-GI-40][TX-STBC][RX-STBC1][MAX-AMSDU-7935]",
        "vht_capab": "[MAX-MPDU-11454][RXLDPC][SHORT-GI-80][TX-STBC-2BY1][RX-STBC-1][SU-BEAMFORMEE][MU-BEAMFORMEE][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": True, "he_bss_color": True, "ap_mode": True, "dfs": True,
        "recommended_backend": "debian",
        "note": "6 GHz hardware present; AP on 6 GHz in this driver has limited verification.",
    },
    "rtw89_8922ae": {
        "label": "Realtek RTL8922AE (rtw89, WiFi 7, PCIe)",
        "wifi_gen": 7,
        "bus_types": ["pcie"],
        "bands": ["2.4GHz", "5GHz", "6GHz"],
        "max_channel_width": 160,
        "ht_capab": "[LDPC][HT40+][HT40-][SHORT-GI-20][SHORT-GI-40][TX-STBC][RX-STBC1][MAX-AMSDU-7935]",
        "vht_capab": "[MAX-MPDU-11454][VHT160][RXLDPC][SHORT-GI-80][SHORT-GI-160][TX-STBC-2BY1][RX-STBC-1][SU-BEAMFORMEE][MU-BEAMFORMEE][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": True, "eht_capab": True, "he_bss_color": True, "ap_mode": True, "dfs": True,
        "recommended_backend": "git_head",
        "note": "WiFi 7 EHT requires hostapd 2.11+ (upstream git). 6 GHz AP needs WPA3-SAE.",
    },

    # ── Intel iwlwifi — PCIe ──────────────────────────────────────────────────
    "iwlwifi": {
        "label": "Intel WiFi (iwlwifi / iwlmvm, PCIe)",
        "wifi_gen": 6,
        "bus_types": ["pcie"],
        "bands": ["2.4GHz", "5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[LDPC][HT40+][HT40-][SHORT-GI-20][SHORT-GI-40]",
        "vht_capab": "[RXLDPC][SHORT-GI-80][TX-STBC-2BY1][RX-STBC-1][SU-BEAMFORMEE][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": True,
        "he_bss_color": True,
        "ap_mode": True,
        "dfs": False,
        "iwlwifi_lar": True,
        "iwlwifi_5g_ap": "patched",
        "recommended_backend": "lar_patched",
        "iwlwifi_notes": [
            "INTEL LAR (LOCATION AWARE REGULATORY) — RESTRICTIONS & WORKAROUNDS",
            "",
            "Root cause:",
            "  Intel's iwlmvm firmware uses LAR (Location Aware Regulatory), which",
            "  determines the regulatory domain by scanning nearby APs, NOT from",
            "  the country_code setting. On startup, hostapd resets the card to",
            "  regdomain '00' (world). The world regdomain marks ALL 5 GHz channels",
            "  as NO-IR (no-initiate-radiation), making them unavailable for AP use.",
            "  Stock hostapd fetches the channel list BEFORE scanning, so LAR never",
            "  gets a chance to update the regdomain, and the AP fails to start.",
            "",
            "  The lar_disable=1 module parameter existed before Linux 5.4 but was",
            "  removed because newer firmware crashes if LAR is disabled. There is",
            "  no kernel-level workaround available today.",
            "",
            "Workaround A — LAR-patched hostapd (RECOMMENDED):",
            "  The tildearrow patch instructs hostapd to issue an iw passive scan",
            "  BEFORE fetching the channel list, giving LAR time to detect the",
            "  correct country from nearby 5 GHz APs. Includes the noscan patch",
            "  (by dviktor) which prevents hostapd's internal scanning from resetting",
            "  the country back to '00' after startup.",
            "  Patch URL: https://tildearrow.org/storage/hostapd-2.10-lar.patch",
            "  CAVEAT: Requires at least one visible nearby 5 GHz AP for country",
            "  detection. Will not work in isolated RF environments.",
            "",
            "Workaround B — NetworkManager pre-scan:",
            "  Start NetworkManager before hostapd (ExecStartPre=/bin/sleep 30).",
            "  NM will scan and allow LAR to set the regdomain. Then stop NM and",
            "  start hostapd. Fragile; NM may interfere with hostapd at runtime.",
            "",
            "Workaround C — 2.4 GHz only (no workaround needed):",
            "  iwlwifi AP mode on 2.4 GHz works with stock Debian hostapd,",
            "  no patches required. 5 GHz and 6 GHz remain restricted.",
            "",
            "Band support summary:",
            "  2.4 GHz: FULLY SUPPORTED — stock hostapd, no issues",
            "  5 GHz  : RESTRICTED — LAR-patched hostapd recommended; unreliable",
            "           in isolated environments with no nearby APs",
            "  6 GHz  : NOT SUPPORTED in iwlwifi AP mode",
            "",
            "Other iwlwifi AP limitations:",
            "  - Only 1 AP BSSID at a time (no multi-BSS / multi-SSID)",
            "  - ht_capab and vht_capab vary by exact card model",
            "  - Verify actual capabilities with: iw list",
            "  - AX200/AX201: 2x2 HE80, 5 GHz AP unreliable without LAR patch",
            "  - AX210/AX211: 2x2 HE160, 5 GHz AP same caveat, no 6 GHz AP",
            "  - AC9260/AC8265: 2x2 VHT80, 5 GHz AP same caveat",
        ],
    },

    # ── Qualcomm Atheros ──────────────────────────────────────────────────────
    "ath9k_htc": {
        "label": "Atheros AR9xxx (ath9k_htc, WiFi 4, USB)",
        "wifi_gen": 4,
        "bus_types": ["usb"],
        "bands": ["2.4GHz", "5GHz"],
        "max_channel_width": 40,
        "ht_capab": "[HT40+][HT40-][SHORT-GI-20][SHORT-GI-40][RX-STBC1][DSSS_CCK-40]",
        "vht_capab": None,
        "he_capab": False, "ap_mode": True, "dfs": False,
        "recommended_backend": "debian",
    },
    "ath10k_pci": {
        "label": "Qualcomm Atheros QCA (ath10k_pci, WiFi 5, PCIe)",
        "wifi_gen": 5,
        "bus_types": ["pcie"],
        "bands": ["5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[HT40+][HT40-][SHORT-GI-20][SHORT-GI-40]",
        "vht_capab": "[SHORT-GI-80]",
        "he_capab": False, "ap_mode": True, "dfs": True,
        "recommended_backend": "debian",
        "note": "ath10k properly implements DFS. One of the best-supported drivers for 5 GHz AP.",
    },
    "ath10k_usb": {
        "label": "Qualcomm Atheros QCA (ath10k_usb, WiFi 5, USB)",
        "wifi_gen": 5,
        "bus_types": ["usb"],
        "bands": ["5GHz"],
        "max_channel_width": 80,
        "ht_capab": "[HT40+][HT40-][SHORT-GI-20][SHORT-GI-40]",
        "vht_capab": "[SHORT-GI-80]",
        "he_capab": False, "ap_mode": True, "dfs": True,
        "recommended_backend": "debian",
    },
    "ath11k_pci": {
        "label": "Qualcomm Atheros QCA (ath11k_pci, WiFi 6, PCIe)",
        "wifi_gen": 6,
        "bus_types": ["pcie"],
        "bands": ["2.4GHz", "5GHz", "6GHz"],
        "max_channel_width": 160,
        "ht_capab": "[LDPC][HT40+][HT40-][SHORT-GI-20][SHORT-GI-40][TX-STBC][RX-STBC1]",
        "vht_capab": "[MAX-MPDU-11454][VHT160][RXLDPC][SHORT-GI-80][SHORT-GI-160][TX-STBC-2BY1][RX-STBC-1][SU-BEAMFORMEE][MU-BEAMFORMEE][MAX-A-MPDU-LEN-EXP7]",
        "he_capab": True, "he_bss_color": True, "ap_mode": True, "dfs": True,
        "recommended_backend": "debian",
        "note": "Found in Qualcomm reference hardware and ARM SBCs. Good 6 GHz AP support.",
    },

    # ── Ralink / rt2x00 ───────────────────────────────────────────────────────
    "rt2800usb": {
        "label": "Ralink RT2870/RT3070 (rt2800usb, WiFi 4 N300, USB)",
        "wifi_gen": 4,
        "bus_types": ["usb"],
        "bands": ["2.4GHz"],
        "max_channel_width": 40,
        "ht_capab": "[HT40+][HT40-][GF][SHORT-GI-20][SHORT-GI-40][RX-STBC1]",
        "vht_capab": None,
        "he_capab": False, "ap_mode": True, "dfs": False,
        "recommended_backend": "debian",
    },

    # ── Generic fallback ──────────────────────────────────────────────────────
    "unknown": {
        "label": "Unknown / unsupported driver",
        "wifi_gen": 4,
        "bus_types": ["unknown"],
        "bands": ["2.4GHz"],
        "max_channel_width": 20,
        "ht_capab": "[SHORT-GI-20]",
        "vht_capab": None,
        "he_capab": False, "ap_mode": True, "dfs": False,
        "recommended_backend": "debian",
    },
}

# ── Driver alias normalization ────────────────────────────────────────────────
DRIVER_ALIAS = {
    "mt7921": "mt7921u", "mt7925": "mt7925u",
    "mt7612": "mt7612u", "mt7610": "mt7610u",
    "mt7921e": "mt7921e", "mt7915e": "mt7915e",
    "mt7916e": "mt7916e", "mt7996e": "mt7996e",
    "mt7925e": "mt7925e", "mt7922": "mt7922",
    "rtw88_8812a": "rtw88_8812au", "rtw88_8821a": "rtw88_8821au",
    "rtw88_8814a": "rtw88_8814au", "rtw88_8812b": "rtw88_8812bu",
    "rtw88_8821c": "rtw88_8821cu", "rtw88_8852b": "rtw88_8812bu",
    "rtl8812au": "rtw88_8812au", "rtl8821cu": "rtw88_8821cu",
    "rtl8814au": "rtw88_8814au",
    "rtw89_8852b": "rtw89_8852be", "rtw89_8852c": "rtw89_8852ce",
    "rtw89_8922a": "rtw89_8922ae",
    "iwlmvm": "iwlwifi", "iwldvm": "iwlwifi",
    "ath9k": "ath9k_htc", "ath10k": "ath10k_pci", "ath11k": "ath11k_pci",
    "rt2800": "rt2800usb", "rt2x00": "rt2800usb",
}

CHANNELS_2G = list(range(1, 14))
CHANNELS_5G = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112,
               116, 120, 124, 128, 132, 136, 140, 149, 153, 157, 161, 165]
CHANNELS_5G_DFS = [52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140]
CHANNELS_5G_NO_DFS = [ch for ch in CHANNELS_5G if ch not in CHANNELS_5G_DFS]
CHANNELS_6G = [1, 5, 9, 13, 17, 21, 25, 29, 33, 37, 41, 45, 49, 53,
               57, 61, 65, 69, 73, 77, 81, 85, 89, 93]


def run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def detect_bus_type(iface_path: Path) -> str:
    """
    Resolve bus type from sysfs device path.
    PCIe paths contain /pci; USB paths contain /usb; SDIO paths contain /mmc or /sdio.
    """
    dev = iface_path / "device"
    if not dev.exists():
        return "unknown"
    try:
        real = str(dev.resolve())
    except Exception:
        return "unknown"
    if "/usb" in real:
        return "usb"
    if "/pci" in real:
        return "pcie"
    if "/mmc" in real or "/sdio" in real:
        return "sdio"
    subsys = dev / "subsystem"
    if subsys.is_symlink():
        name = os.path.basename(os.readlink(str(subsys)))
        if name == "usb":   return "usb"
        if name == "pci":   return "pcie"
    return "unknown"


def get_wireless_interfaces():
    interfaces = []
    net_path = Path("/sys/class/net")
    if not net_path.exists():
        return interfaces

    for iface_path in sorted(net_path.iterdir()):
        if not ((iface_path / "wireless").exists() or (iface_path / "phy80211").exists()):
            continue

        iface = iface_path.name
        bus_type = detect_bus_type(iface_path)

        info = {
            "interface": iface,
            "driver": "unknown",
            "driver_label": "Unknown",
            "bus_type": bus_type,
            "phy": None,
            "mac": "",
            "bands": [],
            "ap_support": False,
            "capabilities": {},
            "iw_info": {},
            "iwlwifi_lar": False,
            "recommended_backend": "debian",
        }

        # Driver via ethtool
        for line in run(["ethtool", "-i", iface]).splitlines():
            if line.startswith("driver:"):
                info["driver"] = _normalize_driver(line.split(":", 1)[1].strip())
                break
        # Sysfs fallback
        if info["driver"] == "unknown":
            link = iface_path / "device" / "driver"
            if link.is_symlink():
                info["driver"] = _normalize_driver(
                    os.path.basename(os.readlink(str(link))))

        db = DRIVER_CAPABILITIES.get(info["driver"], DRIVER_CAPABILITIES["unknown"])
        info["driver_label"] = db["label"]
        info["bands"] = db["bands"]
        info["ap_support"] = db.get("ap_mode", False)
        info["capabilities"] = db
        info["iwlwifi_lar"] = db.get("iwlwifi_lar", False)
        info["recommended_backend"] = db.get("recommended_backend", "debian")

        mac_f = iface_path / "address"
        if mac_f.exists():
            info["mac"] = mac_f.read_text().strip()

        for line in run(["iw", "dev", iface, "info"]).splitlines():
            if line.strip().startswith("wiphy"):
                try:
                    info["phy"] = f"phy{int(line.split()[1])}"
                except (IndexError, ValueError):
                    pass

        if info["phy"]:
            iw_out = run(["iw", "phy", info["phy"], "info"])
            info["iw_info"] = _parse_iw_phy(iw_out)
            if "AP" in info["iw_info"].get("interface_modes", []):
                info["ap_support"] = True

        interfaces.append(info)
    return interfaces


def _normalize_driver(raw):
    r = raw.lower()
    if r in DRIVER_CAPABILITIES:
        return r
    for alias, canonical in DRIVER_ALIAS.items():
        if alias in r:
            return canonical
    return r or "unknown"


def _parse_iw_phy(text):
    result = {"interface_modes": [], "bands": {}, "he_support": False,
              "eht_support": False, "channels_5g_noIR_only": False}
    current_band = None
    in_modes = False
    noIR_5g = total_5g = 0

    for line in text.splitlines():
        s = line.strip()
        if "Supported interface modes:" in s:
            in_modes = True; continue
        if in_modes:
            if s.startswith("*"):
                result["interface_modes"].append(s.lstrip("* "))
            else:
                in_modes = False

        bm = re.match(r"Band (\d+):", s)
        if bm:
            current_band = int(bm.group(1))
            result["bands"][current_band] = {"ht": False, "vht": False, "he": False}

        if current_band == 2 and re.search(r"\d{4} MHz", s):
            total_5g += 1
            if "NO_IR" in s or "PASSIVE_SCAN" in s:
                noIR_5g += 1

        if current_band is not None:
            if "HT20/HT40" in s or "HT capabilities" in s:
                result["bands"][current_band]["ht"] = True
            if "VHT capabilities" in s:
                result["bands"][current_band]["vht"] = True
            if "HE capabilities" in s:
                result["bands"][current_band]["he"] = True
                result["he_support"] = True
            if "EHT capabilities" in s:
                result["eht_support"] = True

    if total_5g > 0 and noIR_5g == total_5g:
        result["channels_5g_noIR_only"] = True
    return result


# ── Dependency resolution ─────────────────────────────────────────────────────
# Each rule is a function(params, db) → list of Change dicts.
# A Change has:
#   field        - the parameter key that was coerced
#   from_val     - the user-supplied value (before coercion)
#   to_val       - the resolved value (after coercion)
#   cause_field  - which user-set field triggered this change
#   cause_val    - the value of the cause field
#   reason       - human-readable explanation
#   severity     - "warning" | "info"

def _change(field, from_val, to_val, cause_field, cause_val, reason, severity="warning"):
    return {"field": field, "from_val": str(from_val), "to_val": str(to_val),
            "cause_field": cause_field, "cause_val": str(cause_val),
            "reason": reason, "severity": severity}


def validate_and_resolve(params: dict) -> tuple[dict, list]:
    """
    Apply all dependency rules to params. Returns (resolved_params, changes).
    resolved_params is a copy of params with coerced values.
    changes is a list of Change dicts describing each coercion.
    Only rules that affect a value the user explicitly set are flagged as changes
    (i.e., where resolved != original). Purely derived/auto values are 'info'.
    """
    p = dict(params)  # work on a copy
    changes = []
    driver_key = p.get("driver", "unknown")
    db = DRIVER_CAPABILITIES.get(driver_key, DRIVER_CAPABILITIES["unknown"])

    band       = p.get("band", "2.4GHz")
    wifi_gen   = int(p.get("wifi_gen", 4))
    ch_width   = int(p.get("channel_width", 20))
    channel    = int(p.get("channel", 6))
    security   = p.get("security", "wpa2")
    he_bss     = int(p.get("he_bss_color", 37))
    backend    = p.get("backend", db.get("recommended_backend", "debian"))

    max_gen    = db.get("wifi_gen", 4)
    max_width  = db.get("max_channel_width", 20)
    is_5g      = band == "5GHz"
    is_6g      = band == "6GHz"
    is_24g     = band == "2.4GHz"
    has_vht    = bool(db.get("vht_capab"))
    has_he     = bool(db.get("he_capab"))

    # ── Rule 1: WiFi gen cannot exceed driver capability ─────────────────────
    if wifi_gen > max_gen:
        changes.append(_change(
            "wifi_gen", wifi_gen, max_gen,
            "driver", driver_key,
            f"The {db['label']} driver only supports up to WiFi {max_gen} "
            f"(802.11{'ax' if max_gen==6 else 'ac' if max_gen==5 else 'n'}). "
            f"WiFi {wifi_gen} is not available on this hardware."
        ))
        p["wifi_gen"] = wifi_gen = max_gen

    # ── Rule 2: Channel width cannot exceed driver/band limits ────────────────
    # 2a. Hardware cap
    if ch_width > max_width:
        changes.append(_change(
            "channel_width", ch_width, max_width,
            "driver", driver_key,
            f"The {db['label']} driver supports a maximum channel width of "
            f"{max_width} MHz. Your requested {ch_width} MHz is not achievable."
        ))
        p["channel_width"] = ch_width = max_width

    # 2b. 2.4 GHz cannot do 80+ MHz
    if is_24g and ch_width > 40:
        new_w = 40
        changes.append(_change(
            "channel_width", ch_width, new_w,
            "band", band,
            f"The 2.4 GHz band does not support channel widths above 40 MHz. "
            f"80/160 MHz operation requires the 5 GHz or 6 GHz band."
        ))
        p["channel_width"] = ch_width = new_w

    # 2c. WiFi 4 (802.11n only) cannot do 80+ MHz — that requires VHT/HE
    if wifi_gen <= 4 and ch_width > 40:
        new_w = 40
        changes.append(_change(
            "channel_width", ch_width, new_w,
            "wifi_gen", f"WiFi {wifi_gen}",
            f"802.11n (WiFi 4) maximum channel width is 40 MHz. "
            f"80 MHz and wider channels require 802.11ac (WiFi 5) or higher, "
            f"which uses the vht_oper_chwidth parameter."
        ))
        p["channel_width"] = ch_width = new_w

    # 2d. WiFi 5 (VHT) not available on 2.4 GHz — no vht_capab there
    if wifi_gen >= 5 and is_24g and not has_vht:
        new_gen = 4
        changes.append(_change(
            "wifi_gen", wifi_gen, new_gen,
            "band", band,
            f"802.11ac (WiFi 5 / VHT) is a 5 GHz-only standard. "
            f"The 2.4 GHz band only supports up to 802.11n (WiFi 4). "
            f"Switch to 5 GHz to use WiFi 5."
        ))
        p["wifi_gen"] = wifi_gen = new_gen

    # 2e. HE (WiFi 6) on 2.4 GHz: valid but width stays at ≤40 MHz
    if wifi_gen >= 6 and is_24g and ch_width > 40:
        new_w = 40
        changes.append(_change(
            "channel_width", ch_width, new_w,
            "band", band,
            f"802.11ax (WiFi 6) on the 2.4 GHz band is limited to 40 MHz channel "
            f"width. he_oper_chwidth is omitted for 2.4 GHz HE operation per the "
            f"802.11ax specification."
        ))
        p["channel_width"] = ch_width = new_w

    # ── Rule 3: Channel must be valid for the selected band ───────────────────
    valid_5g_ch  = set(CHANNELS_5G)
    valid_2g_ch  = set(CHANNELS_2G)
    valid_6g_ch  = set(CHANNELS_6G)

    if is_5g and channel not in valid_5g_ch:
        new_ch = 36
        changes.append(_change(
            "channel", channel, new_ch,
            "band", band,
            f"Channel {channel} is not a valid 5 GHz channel. "
            f"Valid 5 GHz channels start at 36. Defaulting to channel 36."
        ))
        p["channel"] = channel = new_ch

    if is_24g and channel not in valid_2g_ch:
        new_ch = 6
        changes.append(_change(
            "channel", channel, new_ch,
            "band", band,
            f"Channel {channel} is not a valid 2.4 GHz channel (1–13). "
            f"Defaulting to channel 6."
        ))
        p["channel"] = channel = new_ch

    if is_6g and channel not in valid_6g_ch:
        new_ch = 1
        changes.append(_change(
            "channel", channel, new_ch,
            "band", band,
            f"Channel {channel} is not a valid 6 GHz channel. "
            f"6 GHz uses channels 1, 5, 9, 13… (PSC channels). Defaulting to channel 1."
        ))
        p["channel"] = channel = new_ch

    # ── Rule 4: 160 MHz requires a valid 160 MHz block channel ───────────────
    if ch_width == 160 and is_5g:
        valid_160_starts = {36, 40, 44, 48, 52, 56, 60, 64,
                            100, 104, 108, 112, 116, 120, 124, 128,
                            149, 153, 157, 161}
        if channel not in valid_160_starts:
            new_ch = 36
            changes.append(_change(
                "channel", channel, new_ch,
                "channel_width", "160 MHz",
                f"Channel {channel} cannot be the primary channel of a 160 MHz "
                f"block. Valid primary channels for 160 MHz are 36, 40, 44, 48, "
                f"52, 56, 60, 64, 100–128, 149–161. Defaulting to 36."
            ))
            p["channel"] = channel = new_ch

    # ── Rule 5: 6 GHz band requires WPA3 (802.11ax spec §9.4.2.170) ─────────
    if is_6g and security not in ("wpa3", "wpa3-transition"):
        changes.append(_change(
            "security", security, "wpa3",
            "band", band,
            f"The 802.11ax specification mandates WPA3-SAE for 6 GHz AP operation "
            f"(OWE or SAE required; WPA2-PSK is explicitly prohibited). "
            f"ieee80211w=2 (PMF required) will also be set automatically."
        ))
        p["security"] = security = "wpa3"

    # ── Rule 6: WPA3-SAE requires ieee80211w=2; transition requires =1 ───────
    # These are derived values (not user-settable directly in this UI), so they
    # are 'info' rather than 'warning'.
    # Recorded for inline-comment provenance only.

    # ── Rule 7: WiFi 6 (HE) requires WiFi 5 (VHT) which requires WiFi 4 (HT) ─
    if wifi_gen >= 6 and not has_he:
        # Driver doesn't support HE at all
        new_gen = min(max_gen, 5) if has_vht else 4
        changes.append(_change(
            "wifi_gen", wifi_gen, new_gen,
            "driver", driver_key,
            f"The {db['label']} driver does not support 802.11ax (HE/WiFi 6). "
            f"The maximum supported WiFi generation for this driver is WiFi {max_gen}."
        ))
        p["wifi_gen"] = wifi_gen = new_gen

    if wifi_gen >= 5 and not has_vht and is_5g:
        new_gen = 4
        changes.append(_change(
            "wifi_gen", wifi_gen, new_gen,
            "driver", driver_key,
            f"The {db['label']} driver has no vht_capab, meaning 802.11ac (VHT/WiFi 5) "
            f"is not available. Falling back to WiFi 4 (802.11n)."
        ))
        p["wifi_gen"] = wifi_gen = new_gen

    # ── Rule 8: HE BSS color range 1–63 ─────────────────────────────────────
    if not (1 <= he_bss <= 63):
        new_bss = max(1, min(63, he_bss))
        changes.append(_change(
            "he_bss_color", he_bss, new_bss,
            "he_bss_color", he_bss,
            f"he_bss_color must be in the range 1–63 (802.11ax §9.4.2.261). "
            f"Value {he_bss} is out of range; clamped to {new_bss}.",
            severity="warning"
        ))
        p["he_bss_color"] = new_bss

    # ── Rule 9: iwlwifi 5 GHz AP needs LAR-patched backend ───────────────────
    if db.get("iwlwifi_lar") and is_5g and backend == "debian":
        changes.append(_change(
            "backend", "debian", "lar_patched",
            "driver", driver_key,
            f"Intel iwlwifi cards cannot start a 5 GHz AP with stock Debian hostapd "
            f"due to LAR (Location Aware Regulatory). The LAR-patched hostapd scans "
            f"for nearby APs before fetching the channel list, allowing LAR to set "
            f"the correct country code. Switched to LAR-patched backend automatically.",
            severity="warning"
        ))
        p["backend"] = "lar_patched"

    # ── Rule 10: WiFi 7 (EHT) requires git-head hostapd ─────────────────────
    if wifi_gen >= 7 and backend not in ("git_head",):
        changes.append(_change(
            "backend", backend, "git_head",
            "wifi_gen", f"WiFi {wifi_gen}",
            f"IEEE 802.11be (WiFi 7 / EHT) support requires hostapd 2.11 or later. "
            f"Debian 13 ships hostapd 2.10 which does not include EHT. "
            f"The upstream git build must be used.",
            severity="warning"
        ))
        p["backend"] = "git_head"

    return p, changes


# ── Provenance tracking ───────────────────────────────────────────────────────
# Maps param field → user label (for inline comment attribution)
PARAM_LABELS = {
    "wifi_gen":      "WiFi Generation",
    "band":          "Band",
    "channel":       "Channel",
    "channel_width": "Channel Width",
    "security":      "Security Mode",
    "he_bss_color":  "HE BSS Color",
    "backend":       "hostapd Backend",
    "driver":        "Driver",
    "ssid":          "SSID",
    "passphrase":    "Passphrase",
    "country":       "Country Code",
    "bridge":        "Bridge Interface",
    "hidden":        "Hidden SSID",
    "max_stations":  "Max Stations",
    "beacon_int":    "Beacon Interval",
    "dtim_period":   "DTIM Period",
    "enable_dfs":    "Enable DFS",
    "eap_enabled":         "EAP / RADIUS Enabled",
    "radius_auth_addr":    "RADIUS Auth Server",
    "radius_auth_port":    "RADIUS Auth Port",
    "radius_auth_secret":  "RADIUS Auth Secret",
    "radius_acct_addr":    "RADIUS Acct Server",
    "radius_acct_port":    "RADIUS Acct Port",
    "radius_acct_secret":  "RADIUS Acct Secret",
    "nas_identifier":      "NAS Identifier",
    "ap_max_inactivity":   "AP Max Inactivity",
    "disassoc_low_ack":    "Disassoc on Low ACK",
    "skip_inactivity_poll":"Skip Inactivity Poll",
    "ap_isolate":          "AP Client Isolation",
    "multicast_to_unicast":"Multicast to Unicast",
    "rrm_neighbor_report": "RRM Neighbor Report (802.11k)",
    "bss_transition":      "BSS Transition (802.11v)",
    "time_advertisement":  "Time Advertisement",
    "time_zone":           "Time Zone",
    "vendor_elements":     "Vendor Elements",
    "custom_lines":        "Custom Lines",
}


def _ann(key: str, p: dict, changes: list, orig: dict) -> str:
    """
    Build an inline annotation comment for a config key.
    - If the value was coerced by a dependency rule, note which field caused it.
    - If the value matches the original user input, note it as user-selected.
    - For purely derived values (ieee80211d, center_channel, etc.) note why.
    """
    for ch in changes:
        if ch["field"] == key:
            cause_label = PARAM_LABELS.get(ch["cause_field"], ch["cause_field"])
            return (f"  # ← AUTO-ADJUSTED from '{ch['from_val']}' "
                    f"because {cause_label} = {ch['cause_val']}")
    # Check if user set it explicitly (i.e., it appears in original params)
    if key in orig:
        return "  # ← user selected"
    return ""


def generate_hostapd_conf(params: dict, orig_params: dict = None) -> str:
    """
    Generate hostapd.conf from (already-resolved) params.
    orig_params: the raw user params before resolution (for provenance annotation).
    changes: list of Change dicts from validate_and_resolve.
    """
    if orig_params is None:
        orig_params = params

    # Run dependency resolution
    p, changes = validate_and_resolve(params)

    iface       = p.get("interface", "wlan0")
    driver_key  = p.get("driver", "unknown")
    db          = DRIVER_CAPABILITIES.get(driver_key, DRIVER_CAPABILITIES["unknown"])
    backend_key = p.get("backend", db.get("recommended_backend", "debian"))
    backend     = HOSTAPD_BACKENDS.get(backend_key, HOSTAPD_BACKENDS["debian"])

    ssid         = p.get("ssid", "MyAccessPoint")
    passphrase   = p.get("passphrase", "")
    band         = p.get("band", "2.4GHz")
    channel      = int(p.get("channel", 6))
    wifi_gen     = int(p.get("wifi_gen", 4))
    channel_width= int(p.get("channel_width", 20))
    country      = p.get("country", "US")
    bridge       = p.get("bridge", "")
    security     = p.get("security", "wpa2")
    hidden       = p.get("hidden", False)
    max_stations = int(p.get("max_stations", 32))
    he_bss_color = int(p.get("he_bss_color", 37))
    enable_dfs   = p.get("enable_dfs", False)
    beacon_int   = int(p.get("beacon_int", 100))
    dtim_period  = int(p.get("dtim_period", 2))

    # ── Additional Options (advanced / uncommon) ─────────────────────────────
    eap_enabled        = bool(p.get("eap_enabled", False))
    radius_auth_addr   = (p.get("radius_auth_addr") or "").strip()
    radius_auth_port   = str(p.get("radius_auth_port") or "1812").strip() or "1812"
    radius_auth_secret = p.get("radius_auth_secret") or ""
    radius_acct_addr   = (p.get("radius_acct_addr") or "").strip()
    radius_acct_port   = str(p.get("radius_acct_port") or "1813").strip() or "1813"
    radius_acct_secret = p.get("radius_acct_secret") or ""
    nas_identifier     = (p.get("nas_identifier") or "").strip()

    ap_max_inactivity     = str(p.get("ap_max_inactivity") or "").strip()
    disassoc_low_ack      = bool(p.get("disassoc_low_ack", False))
    skip_inactivity_poll  = bool(p.get("skip_inactivity_poll", False))

    ap_isolate           = bool(p.get("ap_isolate", False))
    multicast_to_unicast = bool(p.get("multicast_to_unicast", False))

    rrm_neighbor_report = bool(p.get("rrm_neighbor_report", False))
    bss_transition      = bool(p.get("bss_transition", False))
    time_advertisement  = bool(p.get("time_advertisement", False))
    time_zone           = (p.get("time_zone") or "").strip()

    vendor_elements = (p.get("vendor_elements") or "").strip()
    custom_lines    = p.get("custom_lines") or ""

    is_5g   = band == "5GHz"
    is_6g   = band == "6GHz"
    hw_mode = "a" if (is_5g or is_6g) else "g"
    vht_centr = _center_channel(channel, channel_width)
    is_iwlwifi = db.get("iwlwifi_lar", False)

    # Helper: annotation for a given field
    def ann(key): return _ann(key, p, changes, orig_params)

    # Helper: derived-value annotation (no user input possible)
    def derived(reason): return f"  # ← derived: {reason}"

    lines = []
    def c(t=""): lines.append(t)

    c("# hostapd.conf — generated by hostapd Configurator")
    c(f"# Interface : {iface}  |  Driver  : {db['label']}")
    c(f"# Bus type  : {db.get('bus_types', ['unknown'])[0].upper()}")
    c(f"# WiFi gen  : WiFi {wifi_gen}  |  Band : {band}  |  Width : {channel_width} MHz")
    c(f"# Backend   : {backend['label']}")
    if p.get("from_library"):
        c("# Source    : Driver Library (no live interface) — verify the")
        c(f"#             interface name '{iface}' matches your hardware before use.")
    c("# Reference : https://w1.fi/cgit/hostap/plain/hostapd/hostapd.conf")
    c("# Reference : https://github.com/morrownr/USB-WiFi")
    c()

    # iwlwifi LAR warning block
    if is_iwlwifi and is_5g:
        c("# ════════════════════════════════════════════════════════════")
        c("# INTEL iwlwifi LAR WARNING — 5 GHz AP")
        c("# ════════════════════════════════════════════════════════════")
        c("# Stock hostapd will likely FAIL on 5 GHz with this card.")
        if backend_key == "lar_patched":
            c("# LAR-patched hostapd selected: scan-before-start enabled.")
            c("# Requires a visible nearby 5 GHz AP for country detection.")
        else:
            c("# Switch to 'LAR-patched hostapd' backend to fix this.")
        c("# See: https://tildearrow.org/?p=post&month=7&year=2022&item=lar")
        c("# ════════════════════════════════════════════════════════════")
        c()

    c("##### Basic configuration ##########################################")
    c(f"interface={iface}{ann('interface')}")
    if bridge:
        c(f"bridge={bridge}{ann('bridge')}")
    c("driver=nl80211"
      + derived("nl80211 is required for all Linux mac80211 in-kernel drivers"))
    c()
    c(f"ssid={ssid}{ann('ssid')}")
    c(f"hw_mode={hw_mode}"
      + derived(f"'a' for 5/6 GHz, 'g' for 2.4 GHz — set by band={band}"))
    c(f"channel={channel}{ann('channel')}")
    c(f"country_code={country}{ann('country')}")
    c("ieee80211d=1"
      + derived("advertise country code & allowed channels per 802.11d; required with country_code"))
    if is_5g and enable_dfs:
        c("ieee80211h=1"
          + derived("required for DFS radar detection on 5 GHz; mandatory when using DFS channels"))
    c()

    c("##### Control interface ###########################################")
    c("ctrl_interface=/var/run/hostapd"
      + derived("UNIX socket path for hostapd_cli; standard Debian location"))
    c("ctrl_interface_group=0"
      + derived("restrict control socket to root; set to a group name to allow non-root access"))
    c()

    c("##### Misc settings ###############################################")
    c(f"beacon_int={beacon_int}{ann('beacon_int')}")
    c(f"dtim_period={dtim_period}{ann('dtim_period')}")
    c(f"max_num_sta={max_stations}{ann('max_stations')}")
    c("macaddr_acl=0"
      + derived("0=accept all MACs; change to 1 to use an allow-list"))
    c("rts_threshold=2347"
      + derived("disabled (max value); enable RTS/CTS for congested environments"))
    c("fragm_threshold=2346"
      + derived("disabled (max value); fragmentation reduces error impact on noisy links"))
    c(f"ignore_broadcast_ssid={'1' if hidden else '0'}{ann('hidden')}")
    c()

    c("##### Security ####################################################")
    needs_wpa3 = security in ("wpa3", "wpa3-transition")
    if security == "open":
        c("auth_algs=1"
          + derived("open system authentication; no WPA"))
    else:
        if needs_wpa3:
            c("auth_algs=3"
              + derived("3=both open+shared required for WPA3-SAE and SAE Transition mode"))
        else:
            c("auth_algs=1"
              + derived("open system authentication required for WPA2"))
        c("wpa=2" + derived("WPA2/WPA3 (RSN); wpa=1 is WPA1/TKIP, never use it"))
        c("rsn_pairwise=CCMP"
          + derived("AES-CCMP is the only secure cipher for WPA2/WPA3; TKIP is broken"))
        if not eap_enabled:
            c(f"wpa_passphrase={passphrase}{ann('passphrase')}")
        if security == "wpa3":
            kmgmt = "WPA-EAP-SHA256" if eap_enabled else "SAE"
            c(f"wpa_key_mgmt={kmgmt}{ann('security')}")
            c("ieee80211w=2"
              + derived("PMF required (mandatory) for WPA3-SAE per 802.11ax §12.4"))
            if not eap_enabled:
                c("sae_require_mfp=1"
                  + derived("require Management Frame Protection for all SAE associations"))
        elif security == "wpa3-transition":
            kmgmt = "WPA-EAP-SHA256 WPA-EAP" if eap_enabled else "SAE WPA-PSK"
            c(f"wpa_key_mgmt={kmgmt}{ann('security')}")
            c("ieee80211w=1"
              + derived("PMF capable (optional) for WPA3-SAE Transition mode"))
            if not eap_enabled:
                c("sae_require_mfp=1"
                  + derived("require MFP for SAE clients; WPA2-PSK clients may connect without it"))
        else:
            kmgmt = "WPA-EAP" if eap_enabled else "WPA-PSK"
            c(f"wpa_key_mgmt={kmgmt}{ann('security')}")
        if eap_enabled:
            c("ieee8021x=1"
              + derived("802.1X authenticator required for EAP/RADIUS authentication"))
        if not eap_enabled:
            c("#sae_groups=19 20 21 25 26"
              + derived("SAE ECC groups; 19=P-256 is default and universally supported"))
            c("#sae_anti_clogging_threshold=10"
              + derived("commit frames before requiring anti-clogging token; default 5"))
    c()

    # ── 802.11n ──
    if wifi_gen >= 4:
        c("##### IEEE 802.11n (WiFi 4 / HT) ##################################")
        c(f"ieee80211n=1{ann('wifi_gen')}")
        c("wmm_enabled=1"
          + derived("WMM/QoS required for 802.11n; also required for WPA2"))
        c(f"ht_capab={_build_ht_capab(db, channel_width, band)}"
          + derived(f"HT capabilities from driver db for {driver_key}; "
                    f"width={channel_width} MHz filters out HT40 tokens if width<40"))
        c()

    # ── 802.11ac ──
    if wifi_gen >= 5 and is_5g and db.get("vht_capab"):
        vht_cw = _vht_chwidth_val(channel_width)
        c("##### IEEE 802.11ac (WiFi 5 / VHT) ################################")
        c(f"ieee80211ac=1{ann('wifi_gen')}")
        c(f"vht_oper_chwidth={vht_cw}"
          + derived(f"0=20/40 MHz, 1=80 MHz, 2=160 MHz — set by channel_width={channel_width} MHz"))
        if channel_width >= 80:
            c(f"vht_oper_centr_freq_seg0_idx={vht_centr}"
              + derived(f"center channel for {channel_width} MHz block "
                        f"starting at channel {channel}; "
                        f"formula: primary+6 for 80 MHz, primary+14 for 160 MHz"))
        c(f"vht_capab={db['vht_capab']}"
          + derived(f"VHT capabilities from driver database for {driver_key}"))
        if "[TX-STBC-2BY1]" in db.get("vht_capab", ""):
            c("# [TX-STBC-2BY1] may cause instability on some Realtek adapters — "
              "remove if connections drop")
        c()

    # ── 802.11ax ──
    if wifi_gen >= 6 and db.get("he_capab"):
        he_cw = _vht_chwidth_val(channel_width)
        c("##### IEEE 802.11ax (WiFi 6 / HE) #################################")
        c("# Requires hostapd 2.10+ (Debian 13 ships 2.10)")
        c(f"ieee80211ax=1{ann('wifi_gen')}")
        if is_5g or is_6g:
            c(f"he_oper_chwidth={he_cw}"
              + derived(f"HE channel width: 0=40 MHz, 1=80 MHz, 2=160 MHz "
                        f"— set by channel_width={channel_width} MHz"))
            if channel_width >= 80:
                c(f"he_oper_centr_freq_seg0_idx={vht_centr}"
                  + derived(f"center channel — same calculation as VHT, "
                             f"channel {channel} + offset for {channel_width} MHz"))
        if db.get("he_bss_color"):
            c(f"he_bss_color={he_bss_color}"
              + ann("he_bss_color")
              + derived(" BSS coloring allows spatial reuse by distinguishing "
                        "overlapping APs (range 1-63, pick unique value per AP)").lstrip()
              if not ann("he_bss_color") else ann("he_bss_color"))
        c()

    # ── 802.11be ──
    if wifi_gen >= 7 and db.get("eht_capab"):
        c("##### IEEE 802.11be (WiFi 7 / EHT) ################################")
        c("# Requires hostapd 2.11+ (upstream git — NOT in Debian 13)")
        c(f"ieee80211be=1{ann('wifi_gen')}")
        c()

    # ── EAP / RADIUS (optional, advanced) ──
    if eap_enabled:
        c("##### EAP / RADIUS (802.1X) #######################################")
        if nas_identifier:
            c(f"nas_identifier={nas_identifier}{ann('nas_identifier')}")
        if radius_auth_addr:
            c(f"auth_server_addr={radius_auth_addr}{ann('radius_auth_addr')}")
            c(f"auth_server_port={radius_auth_port}{ann('radius_auth_port')}")
            if radius_auth_secret:
                c(f"auth_server_shared_secret={radius_auth_secret}{ann('radius_auth_secret')}")
        else:
            c("# auth_server_addr=10.0.0.1     # ⚠ no RADIUS auth server set; hostapd will fail to start")
            c("# auth_server_port=1812")
            c("# auth_server_shared_secret=changeme")
        if radius_acct_addr:
            c(f"acct_server_addr={radius_acct_addr}{ann('radius_acct_addr')}")
            c(f"acct_server_port={radius_acct_port}{ann('radius_acct_port')}")
            if radius_acct_secret:
                c(f"acct_server_shared_secret={radius_acct_secret}{ann('radius_acct_secret')}")
        c()

    # ── Inactivity & client maintenance (optional, advanced) ──
    if ap_max_inactivity or disassoc_low_ack or skip_inactivity_poll:
        c("##### Inactivity & client maintenance #############################")
        if ap_max_inactivity:
            c(f"ap_max_inactivity={ap_max_inactivity}{ann('ap_max_inactivity')}")
        if disassoc_low_ack:
            c(f"disassoc_low_ack=1{ann('disassoc_low_ack')}")
        if skip_inactivity_poll:
            c(f"skip_inactivity_poll=1{ann('skip_inactivity_poll')}")
        c()

    # ── Client isolation / multicast (optional, advanced) ──
    if ap_isolate or multicast_to_unicast:
        c("##### Client isolation / multicast handling #######################")
        if ap_isolate:
            c(f"ap_isolate=1{ann('ap_isolate')}")
        if multicast_to_unicast:
            c(f"multicast_to_unicast=1{ann('multicast_to_unicast')}")
        c()

    # ── Roaming assistance 802.11k / 802.11v (optional, advanced) ──
    if rrm_neighbor_report or bss_transition or time_advertisement or time_zone:
        c("##### Roaming assistance (802.11k / 802.11v) ######################")
        if rrm_neighbor_report:
            c(f"rrm_neighbor_report=1{ann('rrm_neighbor_report')}")
        if bss_transition:
            c(f"bss_transition=1{ann('bss_transition')}")
        if time_advertisement:
            c(f"time_advertisement=2{ann('time_advertisement')}")
        if time_zone:
            c(f"time_zone={time_zone}{ann('time_zone')}")
        c()

    # ── Vendor-specific information elements (optional, advanced) ──
    if vendor_elements:
        c("##### Vendor-specific information elements ########################")
        c(f"vendor_elements={vendor_elements}{ann('vendor_elements')}")
        c()

    # ── User-supplied custom lines (optional, advanced) ──
    if custom_lines.strip():
        c("##### Custom configuration (user-supplied) ########################")
        for raw in custom_lines.splitlines():
            ln = raw.rstrip()
            if ln:
                c(ln)
        c()

    # ── Module params ──
    if db.get("module_params"):
        c("##### Recommended module parameters (add to /etc/modprobe.d/) ####")
        for mp in db["module_params"]:
            c(f"# {mp}")
        c()

    # ── Driver notes ──
    if db.get("note"):
        c("##### Driver notes ################################################")
        for ln in db["note"].split(". "):
            c(f"# {ln.strip()}")
        c()

    # ── iwlwifi full notes ──
    if is_iwlwifi and db.get("iwlwifi_notes"):
        c("##### Intel iwlwifi LAR — detailed documentation ##################")
        for ln in db["iwlwifi_notes"]:
            c(f"# {ln}")
        c()

    c("# end of hostapd.conf")
    return "\n".join(lines)


def _build_ht_capab(db, channel_width, band):
    capab = db.get("ht_capab", "[SHORT-GI-20]")
    if channel_width < 40:
        capab = re.sub(r"\[HT40[^\]]*\]", "", capab)
        capab = re.sub(r"\[SHORT-GI-40\]|\[DSSS_CCK-40\]|\[GF\]", "", capab)
    return capab or "[SHORT-GI-20]"


def _vht_chwidth_val(w):
    if w >= 160: return 2
    if w >= 80:  return 1
    return 0


def _center_channel(primary, width):
    if width == 80:
        M = {36:42,40:42,44:42,48:42, 52:58,56:58,60:58,64:58,
             100:106,104:106,108:106,112:106, 116:122,120:122,124:122,128:122,
             132:138,136:138,140:138, 149:155,153:155,157:155,161:155}
        return M.get(primary, primary+6)
    if width == 160:
        M = {36:50,40:50,44:50,48:50,52:50,56:50,60:50,64:50,
             100:114,104:114,108:114,112:114,116:114,120:114,124:114,128:114,
             149:163,153:163,157:163,161:163}
        return M.get(primary, primary+14)
    return primary


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/interfaces")
def api_interfaces():
    return jsonify(get_wireless_interfaces())


@app.route("/api/backends")
def api_backends():
    result = {}
    for key, b in HOSTAPD_BACKENDS.items():
        entry = dict(b)
        entry["available"] = Path(b["path"]).exists()
        result[key] = entry
    return jsonify(result)


@app.route("/api/capabilities/<driver>")
def api_capabilities(driver):
    return jsonify(DRIVER_CAPABILITIES.get(driver, DRIVER_CAPABILITIES["unknown"]))


# Vendor groupings for the picker. Drivers not listed here (e.g. "unknown")
# are excluded from the library so the user only sees real chipset choices.
DRIVER_LIBRARY_GROUPS = [
    ("Mediatek (USB)",        ["mt7610u", "mt7612u", "mt7921u", "mt7925u"]),
    ("Mediatek (PCIe)",       ["mt7921e", "mt7922", "mt7915e", "mt7916e",
                               "mt7925e", "mt7996e"]),
    ("Realtek USB (rtw88)",   ["rtw88_8812au", "rtw88_8821au", "rtw88_8814au",
                               "rtw88_8812bu", "rtw88_8821cu"]),
    ("Realtek PCIe (rtw89)",  ["rtw89_8852be", "rtw89_8852ce", "rtw89_8922ae"]),
    ("Intel (PCIe)",          ["iwlwifi"]),
    ("Qualcomm Atheros",      ["ath9k_htc", "ath10k_usb", "ath10k_pci",
                               "ath11k_pci"]),
    ("Ralink / rt2x00",       ["rt2800usb"]),
]


@app.route("/api/driver_library")
def api_driver_library():
    """
    Return the catalog of known drivers/chipsets, grouped by vendor.
    Used by the frontend on machines that have no wireless interface
    (or when the user wants to generate a config for hardware they
    don't yet have installed).
    """
    groups = []
    for vendor, keys in DRIVER_LIBRARY_GROUPS:
        entries = []
        for k in keys:
            db = DRIVER_CAPABILITIES.get(k)
            if not db:
                continue
            entries.append({
                "driver":              k,
                "label":               db["label"],
                "wifi_gen":            db.get("wifi_gen", 4),
                "bus_types":           db.get("bus_types", []),
                "bands":               db.get("bands", []),
                "max_channel_width":   db.get("max_channel_width", 20),
                "recommended_backend": db.get("recommended_backend", "debian"),
                "iwlwifi_lar":         db.get("iwlwifi_lar", False),
                "ap_mode":             db.get("ap_mode", False),
                "he_capab":            bool(db.get("he_capab")),
                "vht_capab":           bool(db.get("vht_capab")),
                "eht_capab":           bool(db.get("eht_capab")),
                "dfs":                 bool(db.get("dfs")),
                "note":                db.get("note"),
            })
        groups.append({"vendor": vendor, "entries": entries})
    return jsonify(groups)


@app.route("/api/channels")
def api_channels():
    band = request.args.get("band", "2.4GHz")
    iwlwifi = request.args.get("iwlwifi", "false").lower() == "true"
    if band == "5GHz":
        ch = CHANNELS_5G_NO_DFS if iwlwifi else CHANNELS_5G
    elif band == "6GHz":
        ch = CHANNELS_6G
    else:
        ch = CHANNELS_2G
    return jsonify({"channels": ch,
                    "dfs_channels": CHANNELS_5G_DFS if band == "5GHz" else []})


@app.route("/api/validate", methods=["POST"])
def api_validate():
    """
    Validate params and return resolved params + list of dependency changes.
    Used by the frontend to show warnings before generating the config.
    """
    params = request.get_json(force=True)
    resolved, changes = validate_and_resolve(params)
    return jsonify({"resolved": resolved, "changes": changes})


@app.route("/api/generate", methods=["POST"])
def api_generate():
    params = request.get_json(force=True)
    orig   = params.get("_orig", params)   # frontend may pass original params separately
    config = generate_hostapd_conf(params, orig_params=orig)
    _, changes = validate_and_resolve(params)
    return jsonify({"config": config, "changes": changes})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
