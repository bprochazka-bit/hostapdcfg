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
from flask import Flask, jsonify, request, Response

app = Flask(__name__)

# ── Suppress Flask's development-server warning banner ──────────────────
# We replace show_server_banner so the WARNING / Running-on / Press CTRL+C
# block doesn't print. We emit our own startup line below in __main__.
import flask.cli  # noqa: E402
flask.cli.show_server_banner = lambda *a, **k: None

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>hostapd Configurator</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect width='16' height='16' fill='%230a0e14' rx='2'/><rect x='2' y='11' width='2' height='3' fill='%2300d4ff'/><rect x='5.5' y='8' width='2' height='6' fill='%2300d4ff'/><rect x='9' y='5' width='2' height='9' fill='%2300d4ff'/><rect x='12.5' y='2' width='2' height='12' fill='%2300d4ff'/></svg>">
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Space+Grotesk:wght@300;400;500;600&display=swap');

  :root {
    --bg: #0a0e14;
    --surface: #111820;
    --surface2: #1a2330;
    --surface3: #1f2d3d;
    --border: #253245;
    --accent: #00d4ff;
    --accent2: #00ff88;
    --accent3: #ff6b35;
    --warn: #ffb347;
    --text: #c9d8e8;
    --text-dim: #637080;
    --text-bright: #e8f4ff;
    --mono: 'JetBrains Mono', monospace;
    --sans: 'Space Grotesk', sans-serif;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  /* ── Header ── */
  header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 16px 32px;
    display: flex;
    align-items: center;
    gap: 20px;
  }
  .terminal-logo {
    font-family: var(--mono);
    color: var(--accent);
    font-size: 1.1rem;
    font-weight: 600;
    display: flex;
    align-items: center;
    letter-spacing: -0.01em;
    flex-shrink: 0;
  }
  .terminal-logo .prompt-sym {
    color: var(--accent2);
    margin-right: 8px;
  }
  .cursor {
    display: inline-block;
    width: 0.55em;
    height: 1em;
    background: var(--accent);
    margin-left: 4px;
    vertical-align: text-bottom;
    animation: blink 1s steps(1) infinite;
  }
  @keyframes blink { 50% { opacity: 0; } }
  header .tagline {
    font-size: 0.8rem;
    color: var(--text-dim);
    font-weight: 300;
  }
  .header-badge {
    margin-left: auto;
    background: rgba(0,212,255,0.1);
    border: 1px solid rgba(0,212,255,0.3);
    color: var(--accent);
    font-size: 0.7rem;
    padding: 4px 10px;
    border-radius: 20px;
    font-family: var(--mono);
    font-weight: 600;
  }

  /* ── Main layout ── */
  main {
    display: grid;
    grid-template-columns: 400px 1fr;
    flex: 1;
    gap: 0;
    height: calc(100vh - 73px);
  }

  /* ── Left panel (form) ── */
  .panel-left {
    background: var(--surface);
    border-right: 1px solid var(--border);
    overflow-y: auto;
    padding: 24px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  /* ── Right panel (output) ── */
  .panel-right {
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .output-header {
    background: var(--surface2);
    border-bottom: 1px solid var(--border);
    padding: 12px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .output-header h2 {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }
  .output-actions { display: flex; gap: 8px; }
  .btn-copy, .btn-dl {
    font-family: var(--mono);
    font-size: 0.75rem;
    padding: 6px 14px;
    border-radius: 6px;
    border: none;
    cursor: pointer;
    transition: all 0.15s;
    font-weight: 600;
  }
  .btn-copy {
    background: rgba(0,212,255,0.15);
    color: var(--accent);
    border: 1px solid rgba(0,212,255,0.3);
  }
  .btn-copy:hover { background: rgba(0,212,255,0.25); }
  .btn-dl {
    background: rgba(0,255,136,0.15);
    color: var(--accent2);
    border: 1px solid rgba(0,255,136,0.3);
  }
  .btn-dl:hover { background: rgba(0,255,136,0.25); }

  #config-output {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
    font-family: var(--mono);
    font-size: 0.78rem;
    line-height: 1.7;
    white-space: pre;
    color: #9db8cc;
    background: var(--bg);
  }
  /* Syntax highlighting via spans */
  #config-output .co { color: #3d5a75; }   /* comment */
  #config-output .kw { color: var(--accent); font-weight: 600; }  /* key */
  #config-output .vl { color: var(--accent2); }   /* value */
  #config-output .hd { color: var(--accent3); font-weight: 600; }  /* section header */

  /* ── Section ── */
  .section {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  .section-header {
    padding: 12px 16px;
    background: var(--surface3);
    border-bottom: 1px solid var(--border);
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-dim);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .section-header .dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--accent);
  }
  .section-body { padding: 16px; display: flex; flex-direction: column; gap: 14px; }

  /* ── Form elements ── */
  label {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  label span {
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  label span.hint {
    font-size: 0.7rem;
    text-transform: none;
    letter-spacing: 0;
    color: #445566;
    font-weight: 400;
    margin-top: 3px;
  }

  input[type=text], input[type=number], input[type=password], select {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-bright);
    font-family: var(--mono);
    font-size: 0.82rem;
    padding: 8px 12px;
    outline: none;
    transition: border-color 0.15s;
    width: 100%;
  }
  input:focus, select:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(0,212,255,0.08);
  }
  select option { background: var(--surface2); }

  /* Inline two-column row */
  .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .row3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }

  /* Toggle */
  .toggle-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .toggle-label { font-size: 0.8rem; color: var(--text); }
  .toggle-desc { font-size: 0.7rem; color: var(--text-dim); }
  .toggle {
    position: relative;
    width: 40px; height: 22px;
    flex-shrink: 0;
  }
  .toggle input { display: none; }
  .slider {
    position: absolute; inset: 0;
    background: var(--surface3);
    border: 1px solid var(--border);
    border-radius: 22px;
    cursor: pointer;
    transition: 0.2s;
  }
  .slider:before {
    content: '';
    position: absolute;
    width: 14px; height: 14px;
    background: var(--text-dim);
    border-radius: 50%;
    top: 3px; left: 3px;
    transition: 0.2s;
  }
  input:checked + .slider { background: rgba(0,212,255,0.2); border-color: var(--accent); }
  input:checked + .slider:before { transform: translateX(18px); background: var(--accent); }

  /* ── Interface card ── */
  .iface-card {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .iface-card:hover { border-color: var(--accent); }
  .iface-card.selected { border-color: var(--accent); background: rgba(0,212,255,0.05); }
  .iface-name { font-family: var(--mono); font-size: 0.9rem; color: var(--text-bright); font-weight: 600; }
  .iface-driver { font-size: 0.72rem; color: var(--text-dim); }
  .iface-badges { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px; }
  .badge {
    font-size: 0.62rem;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 4px;
    font-family: var(--mono);
    letter-spacing: 0.04em;
  }
  .badge-wifi { background: rgba(0,212,255,0.15); color: var(--accent); border: 1px solid rgba(0,212,255,0.3); }
  .badge-band { background: rgba(0,255,136,0.12); color: var(--accent2); border: 1px solid rgba(0,255,136,0.25); }
  .badge-noap { background: rgba(255,107,53,0.15); color: var(--accent3); border: 1px solid rgba(255,107,53,0.3); }
  .badge-virt { background: rgba(204,68,255,0.12); color: #cc88ff; border: 1px solid rgba(204,68,255,0.3); }

  /* ── Source tabs (Detected / Library) ── */
  .src-tabs {
    display: flex;
    gap: 0;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 2px;
    background: var(--bg);
    margin-bottom: 12px;
  }
  .src-tab {
    flex: 1;
    padding: 6px 8px;
    background: none;
    border: none;
    color: var(--text-dim);
    font-family: var(--sans);
    font-size: 0.78rem;
    font-weight: 500;
    cursor: pointer;
    border-radius: 4px;
    transition: background 0.15s, color 0.15s;
  }
  .src-tab.active {
    background: var(--surface3);
    color: var(--text-bright);
  }
  .src-tab:hover:not(.active) { color: var(--text); }

  /* ── Library vendor groups ── */
  .lib-vendor {
    margin-bottom: 10px;
  }
  .lib-vendor-title {
    font-size: 0.7rem;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 6px;
    padding: 0 2px;
  }
  .lib-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .lib-card {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 10px;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
  }
  .lib-card:hover { border-color: var(--accent); }
  .lib-card.selected { border-color: var(--accent); background: rgba(0,212,255,0.05); }
  .lib-card-label { font-size: 0.78rem; color: var(--text-bright); font-weight: 500; }
  .lib-card-meta { font-size: 0.66rem; color: var(--text-dim); font-family: var(--mono); margin-top: 2px; }
  .lib-search {
    width: 100%;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    padding: 7px 10px;
    font-family: var(--sans);
    font-size: 0.8rem;
    margin-bottom: 10px;
  }
  .lib-search:focus { outline: none; border-color: var(--accent); }

  /* ── Collapsible Additional Options panes ── */
  details.section > summary {
    list-style: none;
    cursor: pointer;
    user-select: none;
  }
  details.section > summary::-webkit-details-marker { display: none; }
  details.section > summary .chev {
    margin-left: auto;
    color: var(--text-dim);
    font-size: 0.8rem;
    transition: transform 0.18s;
  }
  details.section[open] > summary .chev { transform: rotate(90deg); }

  details.sub-section {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    margin-bottom: 8px;
    overflow: hidden;
  }
  details.sub-section > summary {
    list-style: none;
    cursor: pointer;
    user-select: none;
    padding: 9px 12px;
    font-size: 0.78rem;
    font-weight: 500;
    color: var(--text-bright);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  details.sub-section > summary::-webkit-details-marker { display: none; }
  details.sub-section > summary:hover { background: var(--surface2); }
  details.sub-section > summary .sub-chev {
    margin-left: auto;
    color: var(--text-dim);
    font-size: 0.7rem;
    transition: transform 0.18s;
  }
  details.sub-section[open] > summary .sub-chev { transform: rotate(90deg); }
  details.sub-section[open] > summary {
    border-bottom: 1px solid var(--border);
    background: var(--surface2);
  }
  .sub-body {
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .sub-tag {
    font-family: var(--mono);
    font-size: 0.6rem;
    background: var(--surface3);
    color: var(--text-dim);
    padding: 1px 6px;
    border-radius: 3px;
    letter-spacing: 0.04em;
  }

  textarea {
    width: 100%;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    padding: 8px 10px;
    font-family: var(--mono);
    font-size: 0.75rem;
    resize: vertical;
    min-height: 70px;
  }
  textarea:focus { outline: none; border-color: var(--accent); }

  /* ── Vendor IE list rows ── */
  .row3 {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr;
    gap: 8px;
  }
  .ie-row {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 8px;
  }
  .ie-row .ie-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    justify-content: space-between;
  }
  .ie-row .ie-byte-count {
    font-family: var(--mono);
    font-size: 0.66rem;
    color: var(--text-dim);
  }
  .ie-row .ie-byte-count.err { color: var(--accent3); }
  .btn-add {
    background: none;
    border: 1px dashed var(--border);
    color: var(--accent);
    padding: 7px 12px;
    border-radius: 6px;
    font-family: var(--mono);
    font-size: 0.72rem;
    cursor: pointer;
    transition: border-color 0.15s, color 0.15s;
  }
  .btn-add:hover { border-color: var(--accent); border-style: solid; }
  .btn-remove {
    background: none;
    border: 1px solid var(--border);
    color: var(--text-dim);
    padding: 4px 9px;
    border-radius: 5px;
    font-family: var(--mono);
    font-size: 0.66rem;
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
  }
  .btn-remove:hover { color: var(--accent3); border-color: var(--accent3); }
  .ie-preview {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 8px 10px;
    font-family: var(--mono);
    font-size: 0.7rem;
    color: var(--accent2);
    word-break: break-all;
    white-space: pre-wrap;
    margin: 0;
  }
  .ie-preview.empty { color: var(--text-dim); }

  .no-ifaces {
    padding: 24px;
    text-align: center;
    color: var(--text-dim);
    font-size: 0.8rem;
    line-height: 1.6;
  }

  /* ── Generate button ── */
  .btn-generate {
    width: 100%;
    padding: 14px 18px;
    background: var(--surface3);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--accent);
    font-family: var(--mono);
    font-size: 0.92rem;
    font-weight: 500;
    letter-spacing: 0.01em;
    cursor: pointer;
    text-align: left;
    transition: border-color 0.15s, background 0.15s;
  }
  .btn-generate:hover { border-color: var(--accent); background: var(--surface2); }
  .btn-generate:active { background: var(--surface3); }
  .btn-generate .prompt-sym { color: var(--accent2); margin-right: 10px; font-weight: 700; }

  .btn-refresh {
    background: none;
    border: 1px solid var(--border);
    color: var(--text-dim);
    font-size: 0.72rem;
    padding: 5px 10px;
    border-radius: 5px;
    cursor: pointer;
    font-family: var(--mono);
    transition: color 0.15s, border-color 0.15s;
  }
  .btn-refresh:hover { color: var(--accent); border-color: var(--accent); }

  /* ── Notification ── */
  #notif {
    position: fixed;
    bottom: 24px; right: 24px;
    background: var(--surface3);
    border: 1px solid var(--accent2);
    color: var(--accent2);
    font-family: var(--mono);
    font-size: 0.75rem;
    padding: 10px 18px;
    border-radius: 8px;
    opacity: 0;
    transform: translateY(8px);
    transition: opacity 0.2s, transform 0.2s;
    pointer-events: none;
    z-index: 999;
  }
  #notif.show { opacity: 1; transform: translateY(0); }

  /* ── Capability pills ── */
  .cap-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }
  .cap-pill {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 6px 10px;
    font-size: 0.72rem;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .cap-pill .icon { font-size: 0.9rem; }
  .cap-pill .cap-label { color: var(--text-dim); font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .cap-pill .cap-val { color: var(--text-bright); font-family: var(--mono); font-size: 0.72rem; }
  .cap-pill.ok .icon { color: var(--accent2); }
  .cap-pill.warn .icon { color: var(--warn); }
  .cap-pill.na .icon { color: var(--text-dim); }

  /* ── Warning banners ── */
  #warnings-area {
    position: sticky;
    top: 0;
    z-index: 100;
    display: flex;
    flex-direction: column;
    gap: 0;
    max-height: 50vh;
    overflow-y: auto;
  }
  .warn-banner {
    background: #1a1400;
    border-left: 3px solid var(--warn);
    border-bottom: 1px solid #2a2000;
    padding: 10px 14px 10px 14px;
    display: flex;
    align-items: flex-start;
    gap: 12px;
    animation: slideDown 0.18s ease;
  }
  .warn-banner.info {
    background: #0d1a14;
    border-left-color: var(--accent2);
  }
  @keyframes slideDown {
    from { opacity:0; transform: translateY(-6px); }
    to   { opacity:1; transform: translateY(0); }
  }
  .warn-icon { font-size: 1rem; flex-shrink: 0; margin-top: 1px; }
  .warn-body { flex: 1; min-width: 0; }
  .warn-title {
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--warn);
    margin-bottom: 2px;
  }
  .warn-banner.info .warn-title { color: var(--accent2); }
  .warn-msg {
    font-size: 0.72rem;
    color: var(--text-dim);
    line-height: 1.5;
  }
  .warn-msg strong { color: var(--text); }
  .warn-actions { display: flex; gap: 6px; margin-top: 6px; align-items: center; }
  .btn-undo {
    font-family: var(--mono);
    font-size: 0.68rem;
    padding: 3px 10px;
    border-radius: 4px;
    background: rgba(255,179,71,0.12);
    color: var(--warn);
    border: 1px solid rgba(255,179,71,0.3);
    cursor: pointer;
    transition: background 0.15s;
  }
  .btn-undo:hover { background: rgba(255,179,71,0.22); }
  .btn-dismiss {
    font-family: var(--mono);
    font-size: 0.68rem;
    padding: 3px 8px;
    border-radius: 4px;
    background: none;
    color: var(--text-dim);
    border: 1px solid var(--border);
    cursor: pointer;
    transition: color 0.15s;
  }
  .btn-dismiss:hover { color: var(--text); }
  .warn-field-chip {
    display: inline-block;
    font-family: var(--mono);
    font-size: 0.65rem;
    background: rgba(255,179,71,0.1);
    color: var(--warn);
    border: 1px solid rgba(255,179,71,0.25);
    border-radius: 3px;
    padding: 1px 5px;
    margin: 0 2px;
  }
  .warn-banner.info .warn-field-chip {
    background: rgba(0,255,136,0.08);
    color: var(--accent2);
    border-color: rgba(0,255,136,0.2);
  }

  /* ── Config annotation syntax ── */
  #config-output .an-user    { color: #4a9eff; }   /* user selected */
  #config-output .an-auto    { color: var(--warn); font-style: italic; }  /* auto-adjusted */
  #config-output .an-derived { color: #4a6070; font-style: italic; }      /* derived */
  ::-webkit-scrollbar { width: 5px; height: 5px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>

<header>
  <div class="terminal-logo">
    <span class="prompt-sym">~/$</span>hostapdcfg<span class="cursor"></span>
  </div>
  <p class="tagline">Generate driver-aware hostapd.conf for Linux access points</p>
  <div class="header-badge">Debian 13 · nl80211</div>
</header>

<main>
  <!-- ── LEFT PANEL ── -->
  <div class="panel-left">

    <!-- Interfaces / Library -->
    <div class="section">
      <div class="section-header">
        <div class="dot"></div>
        <span id="src-section-title">Wireless Interfaces</span>
        <button class="btn-refresh" onclick="loadInterfaces()" style="margin-left:auto" id="btn-refresh-ifaces">↺ Refresh</button>
      </div>
      <div class="section-body">
        <div class="src-tabs">
          <button class="src-tab active" id="tab-detected" onclick="setSourceTab('detected')">Detected</button>
          <button class="src-tab" id="tab-library" onclick="setSourceTab('library')">Driver Library</button>
        </div>
        <div id="iface-list">
          <div class="no-ifaces">Scanning for interfaces…</div>
        </div>
        <div id="lib-list" style="display:none">
          <input type="text" class="lib-search" id="lib-search" placeholder="Filter by chipset, vendor, driver…" oninput="renderLibrary()">
          <div id="lib-groups"></div>
        </div>
      </div>
    </div>

    <!-- Detected capabilities -->
    <div class="section" id="cap-section" style="display:none">
      <div class="section-header"><div class="dot" style="background:var(--accent2)"></div>Detected Capabilities</div>
      <div class="section-body">
        <div class="cap-grid" id="cap-grid"></div>
      </div>
    </div>

    <!-- Network -->
    <div class="section">
      <div class="section-header"><div class="dot" style="background:var(--accent3)"></div>Network Settings</div>
      <div class="section-body">
        <label><span>Interface name <em style="font-weight:300;text-transform:none">(used as <code>interface=</code> in hostapd.conf)</em></span>
          <input type="text" id="iface_name" value="wlan0" maxlength="15" placeholder="wlan0">
        </label>
        <label><span>SSID</span><input type="text" id="ssid" value="MyAccessPoint" maxlength="32"></label>
        <div class="row2">
          <label><span>Band</span>
            <select id="band" onchange="onBandChange()">
              <option value="2.4GHz">2.4 GHz</option>
              <option value="5GHz" selected>5 GHz</option>
              <option value="6GHz">6 GHz</option>
            </select>
          </label>
          <label><span>Channel</span>
            <select id="channel"></select>
          </label>
        </div>
        <div class="row2">
          <label><span>Channel Width</span>
            <select id="channel_width" onchange="onWidthChange()">
              <option value="20">20 MHz</option>
              <option value="40">40 MHz</option>
              <option value="80" selected>80 MHz</option>
              <option value="160">160 MHz</option>
            </select>
          </label>
          <label><span>WiFi Gen</span>
            <select id="wifi_gen">
              <option value="4">WiFi 4 (802.11n)</option>
              <option value="5">WiFi 5 (802.11ac)</option>
              <option value="6">WiFi 6 (802.11ax)</option>
              <option value="7">WiFi 7 (802.11be)</option>
            </select>
          </label>
        </div>
        <label><span>Country Code</span><input type="text" id="country" value="US" maxlength="2" style="text-transform:uppercase"></label>
        <label><span>Bridge Interface <em style="font-weight:300;text-transform:none">(optional)</em></span>
          <input type="text" id="bridge" placeholder="br0 — leave blank for no bridge">
        </label>
      </div>
    </div>

    <!-- Security -->
    <div class="section">
      <div class="section-header"><div class="dot" style="background:var(--warn)"></div>Security</div>
      <div class="section-body">
        <label><span>Mode</span>
          <select id="security" onchange="onSecurityChange()">
            <option value="wpa2">WPA2-PSK (AES)</option>
            <option value="wpa3-transition">WPA3-SAE Transition (WPA2+WPA3)</option>
            <option value="wpa3">WPA3-SAE Only</option>
            <option value="open">Open (no auth)</option>
          </select>
        </label>
        <label id="pw-label"><span>Passphrase</span>
          <input type="password" id="passphrase" value="MySecurePass1234" minlength="8" maxlength="63">
          <span class="hint">8–63 characters</span>
        </label>
      </div>
    </div>

    <!-- hostapd Backend -->
    <div class="section" id="backend-section">
      <div class="section-header"><div class="dot" style="background:#cc44ff"></div>hostapd Backend</div>
      <div class="section-body">
        <label><span>Backend binary</span>
          <select id="backend" onchange="onBackendChange()"></select>
        </label>
        <div id="backend-desc" style="font-size:0.72rem;color:var(--text-dim);line-height:1.55;padding:8px;background:var(--bg);border-radius:6px;border:1px solid var(--border)">
          Select a backend above.
        </div>
        <div id="backend-build" style="display:none">
          <div style="font-size:0.7rem;color:var(--text-dim);margin-bottom:4px;text-transform:uppercase;letter-spacing:0.06em">Build instructions</div>
          <pre id="backend-build-code" style="font-family:var(--mono);font-size:0.68rem;color:#9db8cc;white-space:pre-wrap;background:var(--bg);padding:10px;border-radius:6px;border:1px solid var(--border)"></pre>
        </div>
      </div>
    </div>

    <!-- Advanced -->
    <div class="section">
      <div class="section-header"><div class="dot" style="background:#9966ff"></div>Advanced</div>
      <div class="section-body">
        <div class="row2">
          <label><span>Beacon Interval</span><input type="number" id="beacon_int" value="100" min="15" max="1000"><span class="hint">TUs (100 = 102.4 ms)</span></label>
          <label><span>DTIM Period</span><input type="number" id="dtim_period" value="2" min="1" max="255"></label>
        </div>
        <div class="row2">
          <label><span>Max Stations</span><input type="number" id="max_stations" value="32" min="1" max="255"></label>
          <label><span>HE BSS Color</span><input type="number" id="he_bss_color" value="37" min="1" max="63"><span class="hint">WiFi 6 spatial reuse</span></label>
        </div>
        <div class="toggle-row">
          <div>
            <div class="toggle-label">Hidden SSID</div>
            <div class="toggle-desc">Do not broadcast network name</div>
          </div>
          <label class="toggle"><input type="checkbox" id="hidden"><span class="slider"></span></label>
        </div>
        <div class="toggle-row">
          <div>
            <div class="toggle-label">Enable DFS (5 GHz)</div>
            <div class="toggle-desc">Allow radar-protected channels — requires ieee80211h</div>
          </div>
          <label class="toggle"><input type="checkbox" id="enable_dfs"><span class="slider"></span></label>
        </div>
      </div>
    </div>

    <!-- Additional Options (collapsible) -->
    <details class="section" id="addl-section">
      <summary class="section-header">
        <div class="dot" style="background:#ffaa00"></div>
        Additional Options
        <span class="sub-tag">advanced</span>
        <span class="chev">▶</span>
      </summary>
      <div class="section-body">

        <details class="sub-section">
          <summary>EAP / RADIUS (WPA Enterprise)<span class="sub-chev">▶</span></summary>
          <div class="sub-body">
            <div class="toggle-row">
              <div>
                <div class="toggle-label">Enable EAP / 802.1X</div>
                <div class="toggle-desc">Replace PSK with WPA-EAP and add ieee8021x=1</div>
              </div>
              <label class="toggle"><input type="checkbox" id="eap_enabled"><span class="slider"></span></label>
            </div>
            <label><span>NAS identifier</span>
              <input type="text" id="nas_identifier" placeholder="ap1.example.com">
            </label>
            <label><span>Auth server address</span>
              <input type="text" id="radius_auth_addr" placeholder="10.0.0.1">
            </label>
            <div class="row2">
              <label><span>Auth port</span><input type="number" id="radius_auth_port" value="1812" min="1" max="65535"></label>
              <label><span>Auth shared secret</span><input type="password" id="radius_auth_secret" placeholder="changeme"></label>
            </div>
            <label><span>Accounting server <em style="font-weight:300;text-transform:none">(optional)</em></span>
              <input type="text" id="radius_acct_addr" placeholder="10.0.0.1">
            </label>
            <div class="row2">
              <label><span>Acct port</span><input type="number" id="radius_acct_port" value="1813" min="1" max="65535"></label>
              <label><span>Acct shared secret</span><input type="password" id="radius_acct_secret"></label>
            </div>
          </div>
        </details>

        <details class="sub-section">
          <summary>Inactivity & client maintenance<span class="sub-chev">▶</span></summary>
          <div class="sub-body">
            <label><span>ap_max_inactivity <em style="font-weight:300;text-transform:none">(seconds, blank = hostapd default 300)</em></span>
              <input type="number" id="ap_max_inactivity" placeholder="300" min="1" max="86400">
            </label>
            <div class="toggle-row">
              <div>
                <div class="toggle-label">disassoc_low_ack</div>
                <div class="toggle-desc">Drop clients that fail many consecutive ACKs</div>
              </div>
              <label class="toggle"><input type="checkbox" id="disassoc_low_ack"><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
              <div>
                <div class="toggle-label">skip_inactivity_poll</div>
                <div class="toggle-desc">Don't probe idle clients with null-data frames</div>
              </div>
              <label class="toggle"><input type="checkbox" id="skip_inactivity_poll"><span class="slider"></span></label>
            </div>
          </div>
        </details>

        <details class="sub-section">
          <summary>Client isolation & multicast<span class="sub-chev">▶</span></summary>
          <div class="sub-body">
            <div class="toggle-row">
              <div>
                <div class="toggle-label">ap_isolate</div>
                <div class="toggle-desc">Block client-to-client traffic at the AP (guest networks)</div>
              </div>
              <label class="toggle"><input type="checkbox" id="ap_isolate"><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
              <div>
                <div class="toggle-label">multicast_to_unicast</div>
                <div class="toggle-desc">Convert multicast frames to per-client unicast</div>
              </div>
              <label class="toggle"><input type="checkbox" id="multicast_to_unicast"><span class="slider"></span></label>
            </div>
          </div>
        </details>

        <details class="sub-section">
          <summary>Roaming assistance (802.11k / 802.11v)<span class="sub-chev">▶</span></summary>
          <div class="sub-body">
            <div class="toggle-row">
              <div>
                <div class="toggle-label">rrm_neighbor_report</div>
                <div class="toggle-desc">802.11k: advertise neighbor APs to clients</div>
              </div>
              <label class="toggle"><input type="checkbox" id="rrm_neighbor_report"><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
              <div>
                <div class="toggle-label">bss_transition</div>
                <div class="toggle-desc">802.11v: BSS transition management for roaming</div>
              </div>
              <label class="toggle"><input type="checkbox" id="bss_transition"><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
              <div>
                <div class="toggle-label">time_advertisement</div>
                <div class="toggle-desc">Advertise UTC time in beacons (802.11v)</div>
              </div>
              <label class="toggle"><input type="checkbox" id="time_advertisement"><span class="slider"></span></label>
            </div>
            <label><span>time_zone <em style="font-weight:300;text-transform:none">(POSIX TZ string)</em></span>
              <input type="text" id="time_zone" placeholder="UTC0 or EST5EDT,M3.2.0,M11.1.0">
            </label>
          </div>
        </details>

        <details class="sub-section">
          <summary>Vendor-specific information elements<span class="sub-chev">▶</span></summary>
          <div class="sub-body">
            <div class="hint" style="line-height:1.5">
              Each IE is built as <code>dd</code> · length · OUI (3 bytes) · OUI type (1 byte) · data.
              Add one or more entries below — the hex is generated automatically.
            </div>
            <div id="vendor-ie-list"></div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <button type="button" class="btn-add" onclick="addVendorIE()">+ Add IE</button>
              <button type="button" class="btn-add" onclick="toggleVendorRaw()" id="btn-raw-toggle">Use raw hex…</button>
            </div>
            <div id="vendor-raw-wrap" style="display:none">
              <label style="margin-top:6px"><span>Raw <code>vendor_elements=</code> hex <em style="font-weight:300;text-transform:none">(overrides the structured list)</em></span>
                <input type="text" id="vendor_elements_raw" placeholder="dd05112233445566" oninput="updateVendorPreview()">
              </label>
            </div>
            <div id="vendor-ie-preview-wrap" style="display:none">
              <div class="hint" style="margin-top:4px">Generated hex (sent as <code>vendor_elements=</code>):</div>
              <pre id="vendor-ie-preview" class="ie-preview"></pre>
            </div>
          </div>
        </details>

        <details class="sub-section">
          <summary>Custom hostapd lines<span class="sub-chev">▶</span></summary>
          <div class="sub-body">
            <label><span>Free-form configuration</span>
              <textarea id="custom_lines" rows="5" placeholder="# Lines added verbatim to the end of hostapd.conf
# e.g. wmm_ac_be_aifs=3
#      uapsd_advertisement_enabled=1"></textarea>
              <span class="hint">No validation — use for parameters not exposed by the UI.</span>
            </label>
          </div>
        </details>

      </div>
    </details>

    <button class="btn-generate" onclick="generate()"><span class="prompt-sym">&gt;</span>generate hostapd.conf<span class="cursor"></span></button>
  </div>

  <!-- ── RIGHT PANEL ── -->
  <div class="panel-right">
    <div id="warnings-area"></div>
    <div class="output-header">
      <h2>hostapd.conf Output</h2>
      <div class="output-actions">
        <button class="btn-copy" onclick="copyConfig()">⧉ Copy</button>
        <button class="btn-dl" onclick="downloadConfig()">↓ Download</button>
      </div>
    </div>
    <pre id="config-output"><span class="co"># Select an interface on the left and click Generate.</span></pre>
  </div>
</main>

<div id="notif"></div>

<script>
let interfaces = [];
let selectedIface = null;
let currentConfig = '';
let backends = {};
let library = [];           // [{vendor, entries: [...]}]
let sourceMode = 'detected'; // 'detected' | 'library'
let selectedLibDriver = null;

// Switch between "Detected" and "Driver Library" pickers
function setSourceTab(mode) {
  sourceMode = mode;
  document.getElementById('tab-detected').classList.toggle('active', mode === 'detected');
  document.getElementById('tab-library').classList.toggle('active', mode === 'library');
  document.getElementById('iface-list').style.display = mode === 'detected' ? '' : 'none';
  document.getElementById('lib-list').style.display   = mode === 'library'  ? '' : 'none';
  document.getElementById('btn-refresh-ifaces').style.display = mode === 'detected' ? '' : 'none';
  document.getElementById('src-section-title').textContent =
    mode === 'detected' ? 'Wireless Interfaces' : 'Driver Library';

  if (mode === 'detected' && interfaces.length) {
    selectIface(interfaces[0]);
  } else if (mode === 'library') {
    if (selectedLibDriver) selectLibraryEntry(selectedLibDriver);
    else if (library[0] && library[0].entries[0]) selectLibraryEntry(library[0].entries[0]);
  }
}

async function loadLibrary() {
  try {
    const res = await fetch('/api/driver_library');
    library = await res.json();
    renderLibrary();
  } catch (e) {
    document.getElementById('lib-groups').innerHTML =
      '<div class="no-ifaces">⚠ Could not load driver library.</div>';
  }
}

function renderLibrary() {
  const root = document.getElementById('lib-groups');
  const q = (document.getElementById('lib-search').value || '').trim().toLowerCase();
  root.innerHTML = '';
  let any = false;
  for (const grp of library) {
    const matched = grp.entries.filter(e =>
      !q ||
      e.label.toLowerCase().includes(q) ||
      e.driver.toLowerCase().includes(q) ||
      grp.vendor.toLowerCase().includes(q)
    );
    if (!matched.length) continue;
    any = true;
    const wrap = document.createElement('div');
    wrap.className = 'lib-vendor';
    wrap.innerHTML = `<div class="lib-vendor-title">${esc(grp.vendor)}</div>`;
    const list = document.createElement('div');
    list.className = 'lib-list';
    for (const e of matched) {
      const card = document.createElement('div');
      card.className = 'lib-card';
      card.dataset.driver = e.driver;
      const bus = (e.bus_types || []).join('/').toUpperCase() || '—';
      const bands = (e.bands || []).join(', ');
      const lar = e.iwlwifi_lar ? ' · LAR ⚠' : '';
      card.innerHTML = `
        <div class="lib-card-label">${esc(e.label)}</div>
        <div class="lib-card-meta">${esc(e.driver)} · ${bus} · WiFi ${e.wifi_gen} · ${esc(bands)} · ≤${e.max_channel_width} MHz${lar}</div>
      `;
      card.onclick = () => selectLibraryEntry(e);
      if (selectedLibDriver && selectedLibDriver.driver === e.driver) {
        card.classList.add('selected');
      }
      list.appendChild(card);
    }
    wrap.appendChild(list);
    root.appendChild(wrap);
  }
  if (!any) {
    root.innerHTML = '<div class="no-ifaces">No chipsets match your filter.</div>';
  }
}

// Build a synthetic iface object (matching the shape of /api/interfaces entries)
// from a library entry, so the rest of the UI can treat it identically.
function selectLibraryEntry(entry) {
  selectedLibDriver = entry;
  document.querySelectorAll('.lib-card').forEach(c =>
    c.classList.toggle('selected', c.dataset.driver === entry.driver));

  // Find the full capability record by faking the API shape a detected
  // interface would expose. We only need the fields selectIface() reads.
  const fakeCap = {
    label:               entry.label,
    wifi_gen:            entry.wifi_gen,
    bus_types:           entry.bus_types,
    bands:               entry.bands,
    max_channel_width:   entry.max_channel_width,
    he_capab:            entry.he_capab,
    vht_capab:           entry.vht_capab,
    eht_capab:           entry.eht_capab,
    dfs:                 entry.dfs,
    iwlwifi_lar:         entry.iwlwifi_lar,
    recommended_backend: entry.recommended_backend,
    ap_mode:             entry.ap_mode,
    note:                entry.note,
  };
  const synthetic = {
    interface:           document.getElementById('iface_name').value || 'wlan0',
    driver:              entry.driver,
    driver_label:        entry.label,
    bus_type:            (entry.bus_types && entry.bus_types[0]) || 'unknown',
    mac:                 '',
    bands:               entry.bands || [],
    ap_support:          entry.ap_mode !== false,
    iwlwifi_lar:         !!entry.iwlwifi_lar,
    recommended_backend: entry.recommended_backend || 'debian',
    capabilities:        fakeCap,
    from_library:        true,
  };
  selectIface(synthetic);
}

// ── Undo / warning state ─────────────────────────────────────────────────────
// undoStack: array of { change, prevFormState }
// prevFormState is a snapshot of form fields before the auto-adjustment
let undoStack = [];
let dismissedIds = new Set();  // IDs of warnings the user has dismissed

// Capture current form state as a plain object
function snapshotForm() {
  return {
    band:          document.getElementById('band').value,
    channel:       document.getElementById('channel').value,
    channel_width: document.getElementById('channel_width').value,
    wifi_gen:      document.getElementById('wifi_gen').value,
    security:      document.getElementById('security').value,
    he_bss_color:  document.getElementById('he_bss_color').value,
    backend:       document.getElementById('backend').value,
  };
}

// Apply a form snapshot (used by undo)
function applySnapshot(snap) {
  if (snap.band)          document.getElementById('band').value = snap.band;
  if (snap.channel_width) document.getElementById('channel_width').value = snap.channel_width;
  if (snap.wifi_gen)      document.getElementById('wifi_gen').value = snap.wifi_gen;
  if (snap.security)      document.getElementById('security').value = snap.security;
  if (snap.he_bss_color)  document.getElementById('he_bss_color').value = snap.he_bss_color;
  if (snap.backend)       document.getElementById('backend').value = snap.backend;
  if (snap.band)          onBandChange().then(() => {
    if (snap.channel) document.getElementById('channel').value = snap.channel;
  });
  onSecurityChange();
  onBackendChange();
}

// Field display names for warning UI
const FIELD_LABELS = {
  wifi_gen:      'WiFi Generation',
  band:          'Band',
  channel:       'Channel',
  channel_width: 'Channel Width',
  security:      'Security Mode',
  he_bss_color:  'HE BSS Color',
  backend:       'hostapd Backend',
  driver:        'Driver',
};

function fieldLabel(k) { return FIELD_LABELS[k] || k; }

// ── Warning banner rendering ─────────────────────────────────────────────────
function renderWarnings(changes) {
  const area = document.getElementById('warnings-area');
  area.innerHTML = '';

  // Filter to only non-dismissed changes that modified a value
  const visible = changes.filter(ch =>
    ch.from_val !== ch.to_val && !dismissedIds.has(warningId(ch))
  );

  for (const ch of visible) {
    const id = warningId(ch);
    const isWarn = ch.severity === 'warning';
    const div = document.createElement('div');
    div.className = 'warn-banner' + (isWarn ? '' : ' info');
    div.dataset.wid = id;

    div.innerHTML = `
      <div class="warn-icon">${isWarn ? '⚠' : 'ℹ'}</div>
      <div class="warn-body">
        <div class="warn-title">
          ${isWarn ? 'Auto-adjusted:' : 'Auto-set:'}
          <span class="warn-field-chip">${fieldLabel(ch.field)}</span>
          changed from <span class="warn-field-chip">${esc(ch.from_val)}</span>
          to <span class="warn-field-chip">${esc(ch.to_val)}</span>
        </div>
        <div class="warn-msg">
          <strong>Why:</strong> ${esc(ch.reason)}
          <br><strong>Triggered by:</strong>
          <span class="warn-field-chip">${fieldLabel(ch.cause_field)}</span> = <span class="warn-field-chip">${esc(ch.cause_val)}</span>
        </div>
        <div class="warn-actions">
          ${isWarn ? `<button class="btn-undo" onclick="undoChange('${id}')">↩ Undo this change</button>` : ''}
          <button class="btn-dismiss" onclick="dismissWarning('${id}')">Dismiss</button>
        </div>
      </div>
    `;
    area.appendChild(div);
  }
}

function warningId(ch) {
  return `${ch.field}:${ch.from_val}:${ch.to_val}:${ch.cause_field}`;
}

function dismissWarning(id) {
  dismissedIds.add(id);
  const el = document.querySelector(`[data-wid="${id}"]`);
  if (el) el.remove();
}

function undoChange(id) {
  // Find the undo entry for this warning
  const entry = undoStack.find(e => warningId(e.change) === id);
  if (entry) {
    applySnapshot(entry.prevFormState);
    dismissedIds.add(id);  // dismiss the warning after undo
    const el = document.querySelector(`[data-wid="${id}"]`);
    if (el) el.remove();
    notify('↩ Reverted change to ' + fieldLabel(entry.change.field));
    // Re-generate with undone params
    generate();
  }
}

// ── Config rendering with annotation syntax highlighting ────────────────────
function renderConfig(text) {
  const el = document.getElementById('config-output');
  el.innerHTML = text.split('\n').map(line => {
    // Section headers
    if (line.startsWith('#####')) {
      return `<span class="hd">${esc(line)}</span>`;
    }
    // Pure comment lines (annotation lines get the same colors as before,
    // even though they now sit on their own line above the directive).
    if (line.trimStart().startsWith('#')) {
      const trimmed = line.trimStart();
      if (trimmed.startsWith('# ← AUTO-ADJUSTED')) {
        return `<span class="an-auto">${esc(line)}</span>`;
      }
      if (trimmed.startsWith('# ← user selected')) {
        return `<span class="an-user">${esc(line)}</span>`;
      }
      if (trimmed.startsWith('# ← derived')) {
        return `<span class="an-derived">${esc(line)}</span>`;
      }
      return `<span class="co">${esc(line)}</span>`;
    }
    if (!line.includes('=')) return esc(line);

    // Split at first = to get key and rest
    const eqIdx = line.indexOf('=');
    const key = line.substring(0, eqIdx);
    const rest = line.substring(eqIdx + 1);

    // Detect annotation: "  # ← ..."
    const annMatch = rest.match(/^(.*?)(  # ← .*)$/);
    let valPart, annPart;
    if (annMatch) {
      valPart = annMatch[1];
      annPart = annMatch[2];
    } else {
      valPart = rest;
      annPart = '';
    }

    let annHtml = '';
    if (annPart) {
      if (annPart.includes('AUTO-ADJUSTED')) {
        annHtml = `<span class="an-auto">${esc(annPart)}</span>`;
      } else if (annPart.includes('user selected')) {
        annHtml = `<span class="an-user">${esc(annPart)}</span>`;
      } else if (annPart.includes('derived')) {
        annHtml = `<span class="an-derived">${esc(annPart)}</span>`;
      } else {
        annHtml = `<span class="co">${esc(annPart)}</span>`;
      }
    }

    return `<span class="kw">${esc(key)}</span>=<span class="vl">${esc(valPart)}</span>${annHtml}`;
  }).join('\n');
}

// ── Form helpers ─────────────────────────────────────────────────────────────
async function loadInterfaces() {
  const list = document.getElementById('iface-list');
  list.innerHTML = '<div class="no-ifaces">Scanning…</div>';
  try {
    const res = await fetch('/api/interfaces');
    interfaces = await res.json();
    renderInterfaces();
  } catch(e) {
    list.innerHTML = '<div class="no-ifaces">⚠ Could not enumerate interfaces.<br>Run with sudo for full access.</div>';
  }
}

function renderInterfaces() {
  const list = document.getElementById('iface-list');
  if (!interfaces.length) {
    list.innerHTML = '<div class="no-ifaces">No wireless interfaces detected on this system.<br>'
                   + 'Switch to <strong>Driver Library</strong> above to pick a chipset by name '
                   + 'and generate a config for hardware you intend to use.</div>';
    // Auto-switch to library mode so the user has something to do.
    if (sourceMode === 'detected') setSourceTab('library');
    return;
  }
  list.innerHTML = '';
  for (const iface of interfaces) {
    const cap = iface.capabilities;
    const wifiGen = cap.wifi_gen || 4;
    const apOk = iface.ap_support;
    const busColor = iface.bus_type === 'pcie' ? '#9966ff' : iface.bus_type === 'usb' ? 'var(--accent)' : 'var(--text-dim)';
    const busLabel = (iface.bus_type || 'unknown').toUpperCase();
    const larWarn = iface.iwlwifi_lar ? '<span class="badge badge-noap">LAR ⚠</span>' : '';
    const div = document.createElement('div');
    div.className = 'iface-card';
    div.dataset.iface = iface.interface;
    div.innerHTML = `
      <div class="iface-name">${iface.interface}</div>
      <div class="iface-driver">${iface.driver_label}</div>
      <div class="iface-badges">
        <span class="badge" style="background:rgba(128,128,255,0.12);color:${busColor};border:1px solid ${busColor}44">${busLabel}</span>
        <span class="badge badge-wifi">WiFi ${wifiGen}</span>
        ${(iface.bands||[]).map(b => `<span class="badge badge-band">${b}</span>`).join('')}
        ${!apOk ? '<span class="badge badge-noap">AP ⚠</span>' : ''}
        ${larWarn}
      </div>
    `;
    div.onclick = () => selectIface(iface);
    list.appendChild(div);
  }
  if (interfaces.length) selectIface(interfaces[0]);
}

function selectIface(iface) {
  selectedIface = iface;
  document.querySelectorAll('.iface-card').forEach(c => c.classList.remove('selected'));
  const card = document.querySelector(`.iface-card[data-iface="${iface.interface}"]`);
  if (card) card.classList.add('selected');

  // Sync the editable interface-name input. For detected interfaces we
  // overwrite with the real kernel name; for library entries we leave any
  // user-edited value intact and only seed the default 'wlan0' if empty.
  const nameInput = document.getElementById('iface_name');
  if (nameInput) {
    if (iface.from_library) {
      if (!nameInput.value) nameInput.value = 'wlan0';
    } else {
      nameInput.value = iface.interface;
    }
  }

  const recBackend = iface.recommended_backend || 'debian';
  const backendSel = document.getElementById('backend');
  if (backendSel) backendSel.value = recBackend;
  onBackendChange();

  // Update cap grid
  const cap = iface.capabilities;
  const grid = document.getElementById('cap-grid');
  document.getElementById('cap-section').style.display = 'block';
  const wifiGen = cap.wifi_gen || 4;
  const maxW = cap.max_channel_width || 20;
  const hasHE = !!cap.he_capab;
  const hasVHT = !!cap.vht_capab;
  const hasDFS = !!cap.dfs;
  const busType = (iface.bus_type || 'unknown').toUpperCase();
  const hasLAR = !!cap.iwlwifi_lar;

  grid.innerHTML = `
    <div class="cap-pill ok"><span class="icon">📶</span><div><div class="cap-label">WiFi Gen</div><div class="cap-val">WiFi ${wifiGen}</div></div></div>
    <div class="cap-pill ok"><span class="icon">🔌</span><div><div class="cap-label">Bus Type</div><div class="cap-val">${busType}</div></div></div>
    <div class="cap-pill ${maxW>=80?'ok':'warn'}"><span class="icon">↔</span><div><div class="cap-label">Max Width</div><div class="cap-val">${maxW} MHz</div></div></div>
    <div class="cap-pill ${hasHE?'ok':'na'}"><span class="icon">${hasHE?'✓':'✗'}</span><div><div class="cap-label">802.11ax (HE)</div><div class="cap-val">${hasHE?'Yes':'No'}</div></div></div>
    <div class="cap-pill ${hasVHT?'ok':'na'}"><span class="icon">${hasVHT?'✓':'✗'}</span><div><div class="cap-label">802.11ac (VHT)</div><div class="cap-val">${hasVHT?'Yes':'No'}</div></div></div>
    <div class="cap-pill ${hasDFS?'ok':'na'}"><span class="icon">${hasDFS?'✓':'✗'}</span><div><div class="cap-label">DFS Support</div><div class="cap-val">${hasDFS?'Yes':'No'}</div></div></div>
    <div class="cap-pill ${hasLAR?'warn':'na'}"><span class="icon">${hasLAR?'⚠':'✓'}</span><div><div class="cap-label">Intel LAR</div><div class="cap-val">${hasLAR?'Active':'None'}</div></div></div>
    <div class="cap-pill ok"><span class="icon">📻</span><div><div class="cap-label">Bands</div><div class="cap-val">${(iface.bands||['?']).join(', ')}</div></div></div>
  `;
  updateFormFromCap(cap, iface.bands || []);
}

function updateFormFromCap(cap, bands) {
  const genSel = document.getElementById('wifi_gen');
  const maxGen = cap.wifi_gen || 4;
  Array.from(genSel.options).forEach(o => { o.disabled = parseInt(o.value) > maxGen; });
  genSel.value = Math.min(maxGen, 6);

  const widthSel = document.getElementById('channel_width');
  const maxW = cap.max_channel_width || 20;
  Array.from(widthSel.options).forEach(o => { o.disabled = parseInt(o.value) > maxW; });
  const widths = [160,80,40,20].filter(w => w <= maxW);
  widthSel.value = widths[0] || 20;

  const bandSel = document.getElementById('band');
  if (bands.includes('5GHz')) bandSel.value = '5GHz';
  else if (bands.includes('6GHz')) bandSel.value = '6GHz';
  else bandSel.value = '2.4GHz';
  Array.from(bandSel.options).forEach(o => { o.disabled = !bands.includes(o.value); });

  onBandChange();
}

async function onBandChange() {
  const band = document.getElementById('band').value;
  const isIwl = selectedIface && selectedIface.iwlwifi_lar;
  const res = await fetch(`/api/channels?band=${band}&iwlwifi=${isIwl?'true':'false'}`);
  const data = await res.json();
  const chanSel = document.getElementById('channel');
  chanSel.innerHTML = '';
  for (const ch of data.channels) {
    const opt = document.createElement('option');
    opt.value = ch;
    const isDfs = data.dfs_channels.includes(ch);
    opt.textContent = `Ch ${ch}${isDfs?' (DFS)':''}`;
    chanSel.appendChild(opt);
  }
  const defaults = {'2.4GHz':'6','5GHz':'36','6GHz':'1'};
  chanSel.value = defaults[band] || chanSel.options[0]?.value;

  const widthSel = document.getElementById('channel_width');
  if (band === '2.4GHz') {
    ['80','160'].forEach(v => {
      const o = Array.from(widthSel.options).find(x=>x.value===v);
      if(o) o.disabled = true;
    });
    if (parseInt(widthSel.value) > 40) widthSel.value = '40';
  }
}

function onSecurityChange() {
  const sec = document.getElementById('security').value;
  document.getElementById('pw-label').style.display = sec === 'open' ? 'none' : 'flex';
}

async function loadBackends() {
  try {
    const res = await fetch('/api/backends');
    backends = await res.json();
    const sel = document.getElementById('backend');
    sel.innerHTML = '';
    for (const [key, b] of Object.entries(backends)) {
      const opt = document.createElement('option');
      opt.value = key;
      opt.textContent = b.label + (b.available ? '' : ' ⚠ not found');
      if (!b.available) opt.style.color = 'var(--warn)';
      sel.appendChild(opt);
    }
    onBackendChange();
  } catch(e) {}
}

function onBackendChange() {
  const key = document.getElementById('backend').value;
  const b = backends[key];
  if (!b) return;
  const desc = document.getElementById('backend-desc');
  const buildDiv = document.getElementById('backend-build');
  const buildCode = document.getElementById('backend-build-code');
  desc.textContent = b.description || '';
  desc.style.borderColor = b.available ? 'rgba(0,255,136,0.2)' : 'rgba(255,179,71,0.3)';
  desc.style.color = b.available ? 'var(--text-dim)' : 'var(--warn)';
  if (b.build_notes && !b.available) {
    buildDiv.style.display = 'block';
    buildCode.textContent = b.build_notes;
  } else {
    buildDiv.style.display = 'none';
  }
}

// ── Main generate function ────────────────────────────────────────────────────
async function generate() {
  if (!selectedIface) { notify('⚠ Select an interface first'); return; }

  // Snapshot the form state BEFORE we apply any changes (for undo)
  const preSnap = snapshotForm();

  const params = collectParams();

  // Call generate (which also runs validate_and_resolve server-side)
  const res = await fetch('/api/generate', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({...params, _orig: params})
  });
  const data = await res.json();
  currentConfig = data.config;
  const changes = data.changes || [];

  // Build undo entries for each change that actually modified a user-set value
  for (const ch of changes) {
    if (ch.from_val !== ch.to_val) {
      const id = warningId(ch);
      // Only add if not already in undoStack for this id
      if (!undoStack.find(e => warningId(e.change) === id)) {
        undoStack.push({ change: ch, prevFormState: preSnap });
      }
    }
  }

  // Apply resolved values back to form (so the UI shows what was actually used)
  applyResolvedToForm(data.changes || [], params);

  // Clear dismissed state for any NEW changes
  for (const ch of changes) {
    if (ch.from_val !== ch.to_val) {
      dismissedIds.delete(warningId(ch));
    }
  }

  renderWarnings(changes);
  renderConfig(currentConfig);
}

// ── Vendor IE editor ─────────────────────────────────────────────────────────
let _ieCounter = 0;

function addVendorIE(seed) {
  _ieCounter += 1;
  const id = `ie${_ieCounter}`;
  const list = document.getElementById('vendor-ie-list');
  const row = document.createElement('div');
  row.className = 'ie-row';
  row.dataset.id = id;
  row.innerHTML = `
    <div class="row3">
      <label><span>OUI <em style="font-weight:300;text-transform:none">(3 bytes)</em></span>
        <input type="text" class="ie-oui" placeholder="00:50:F2" maxlength="11" oninput="updateVendorPreview()">
      </label>
      <label><span>OUI Type</span>
        <input type="text" class="ie-type" placeholder="04" maxlength="4" oninput="updateVendorPreview()">
      </label>
      <label><span>Data format</span>
        <select class="ie-fmt" onchange="updateVendorPreview()">
          <option value="hex">Hex</option>
          <option value="text">Text (UTF-8)</option>
        </select>
      </label>
    </div>
    <label><span>Data</span>
      <input type="text" class="ie-data" placeholder="01020304 or any hex/text" oninput="updateVendorPreview()">
    </label>
    <div class="ie-actions">
      <span class="ie-byte-count">— bytes</span>
      <button type="button" class="btn-remove" onclick="removeVendorIE('${id}')">Remove</button>
    </div>
  `;
  list.appendChild(row);
  if (seed) {
    if (seed.oui)  row.querySelector('.ie-oui').value  = seed.oui;
    if (seed.type) row.querySelector('.ie-type').value = seed.type;
    if (seed.fmt)  row.querySelector('.ie-fmt').value  = seed.fmt;
    if (seed.data) row.querySelector('.ie-data').value = seed.data;
  }
  updateVendorPreview();
}

function removeVendorIE(id) {
  const row = document.querySelector(`.ie-row[data-id="${id}"]`);
  if (row) row.remove();
  updateVendorPreview();
}

function toggleVendorRaw() {
  const wrap = document.getElementById('vendor-raw-wrap');
  const btn  = document.getElementById('btn-raw-toggle');
  const showing = wrap.style.display !== 'none';
  wrap.style.display = showing ? 'none' : '';
  btn.textContent    = showing ? 'Use raw hex…' : 'Hide raw hex';
  if (showing) document.getElementById('vendor_elements_raw').value = '';
  updateVendorPreview();
}

// Normalise a string to lowercase hex, stripping common separators.
function _toHex(s) {
  return (s || '').replace(/[\s:\-_]+/g, '').toLowerCase();
}

// Convert a UTF-8 text string to a hex byte string.
function _textToHex(s) {
  const bytes = new TextEncoder().encode(s);
  let out = '';
  for (const b of bytes) out += b.toString(16).padStart(2, '0');
  return out;
}

// Build a single IE row's hex (or null if invalid/incomplete).
// Also stamps the row with a byte-count annotation and an err class on overflow.
function _buildIERow(row) {
  const oui  = _toHex(row.querySelector('.ie-oui').value);
  const type = _toHex((row.querySelector('.ie-type').value || '').replace(/^0x/i,''));
  const fmt  = row.querySelector('.ie-fmt').value;
  const data = row.querySelector('.ie-data').value || '';
  const counter = row.querySelector('.ie-byte-count');

  // Both empty → silently skip (incomplete row, not an error)
  if (!oui && !type && !data) {
    counter.textContent = '— bytes';
    counter.classList.remove('err');
    return null;
  }

  if (oui.length !== 6 || !/^[0-9a-f]+$/.test(oui)) {
    counter.textContent = 'invalid OUI';
    counter.classList.add('err');
    return null;
  }
  if (type.length !== 2 || !/^[0-9a-f]+$/.test(type)) {
    counter.textContent = 'invalid type';
    counter.classList.add('err');
    return null;
  }

  let dataHex = '';
  if (fmt === 'hex') {
    dataHex = _toHex(data);
    if (!/^[0-9a-f]*$/.test(dataHex) || dataHex.length % 2 !== 0) {
      counter.textContent = 'invalid hex data';
      counter.classList.add('err');
      return null;
    }
  } else {
    dataHex = _textToHex(data);
  }

  const payload = oui + type + dataHex;          // bytes after the length field
  const byteLen = payload.length / 2;
  if (byteLen > 255) {
    counter.textContent = `${byteLen} bytes — exceeds 255 limit`;
    counter.classList.add('err');
    return null;
  }
  counter.textContent = `${byteLen} bytes`;
  counter.classList.remove('err');
  const lenHex = byteLen.toString(16).padStart(2, '0');
  return 'dd' + lenHex + payload;
}

// Walk the IE list (or use raw override) and return the full vendor_elements hex.
function buildVendorElementsHex() {
  const raw = (document.getElementById('vendor_elements_raw').value || '').trim();
  if (raw) return _toHex(raw);
  const rows = document.querySelectorAll('#vendor-ie-list .ie-row');
  const parts = [];
  for (const r of rows) {
    const h = _buildIERow(r);
    if (h) parts.push(h);
  }
  return parts.join('');
}

function updateVendorPreview() {
  const hex = buildVendorElementsHex();
  const wrap = document.getElementById('vendor-ie-preview-wrap');
  const pre  = document.getElementById('vendor-ie-preview');
  if (hex) {
    wrap.style.display = '';
    pre.textContent = hex;
    pre.classList.remove('empty');
  } else {
    wrap.style.display = 'none';
    pre.textContent = '';
  }
}

function collectParams() {
  const ifaceName = (document.getElementById('iface_name').value || '').trim() || 'wlan0';
  return {
    interface:     ifaceName,
    driver:        selectedIface.driver,
    from_library:  !!selectedIface.from_library,
    ssid:          document.getElementById('ssid').value,
    passphrase:    document.getElementById('passphrase').value,
    band:          document.getElementById('band').value,
    channel:       document.getElementById('channel').value,
    channel_width: document.getElementById('channel_width').value,
    wifi_gen:      document.getElementById('wifi_gen').value,
    country:       document.getElementById('country').value.toUpperCase(),
    bridge:        document.getElementById('bridge').value,
    security:      document.getElementById('security').value,
    hidden:        document.getElementById('hidden').checked,
    max_stations:  document.getElementById('max_stations').value,
    he_bss_color:  document.getElementById('he_bss_color').value,
    beacon_int:    document.getElementById('beacon_int').value,
    dtim_period:   document.getElementById('dtim_period').value,
    enable_dfs:    document.getElementById('enable_dfs').checked,
    backend:       document.getElementById('backend').value,

    // Additional Options (advanced / uncommon)
    eap_enabled:          document.getElementById('eap_enabled').checked,
    nas_identifier:       document.getElementById('nas_identifier').value,
    radius_auth_addr:     document.getElementById('radius_auth_addr').value,
    radius_auth_port:     document.getElementById('radius_auth_port').value,
    radius_auth_secret:   document.getElementById('radius_auth_secret').value,
    radius_acct_addr:     document.getElementById('radius_acct_addr').value,
    radius_acct_port:     document.getElementById('radius_acct_port').value,
    radius_acct_secret:   document.getElementById('radius_acct_secret').value,
    ap_max_inactivity:    document.getElementById('ap_max_inactivity').value,
    disassoc_low_ack:     document.getElementById('disassoc_low_ack').checked,
    skip_inactivity_poll: document.getElementById('skip_inactivity_poll').checked,
    ap_isolate:           document.getElementById('ap_isolate').checked,
    multicast_to_unicast: document.getElementById('multicast_to_unicast').checked,
    rrm_neighbor_report:  document.getElementById('rrm_neighbor_report').checked,
    bss_transition:       document.getElementById('bss_transition').checked,
    time_advertisement:   document.getElementById('time_advertisement').checked,
    time_zone:            document.getElementById('time_zone').value,
    vendor_elements:      buildVendorElementsHex(),
    custom_lines:         document.getElementById('custom_lines').value,
  };
}

// Update form elements to reflect resolved values returned by the server
function applyResolvedToForm(changes, origParams) {
  // Map of field → resolved value from changes
  const resolved = {};
  for (const ch of changes) {
    if (ch.from_val !== ch.to_val) {
      resolved[ch.field] = ch.to_val;
    }
  }
  if (resolved.wifi_gen)      document.getElementById('wifi_gen').value = resolved.wifi_gen;
  if (resolved.channel_width) document.getElementById('channel_width').value = resolved.channel_width;
  if (resolved.security) {
    document.getElementById('security').value = resolved.security;
    onSecurityChange();
  }
  if (resolved.he_bss_color)  document.getElementById('he_bss_color').value = resolved.he_bss_color;
  if (resolved.backend) {
    document.getElementById('backend').value = resolved.backend;
    onBackendChange();
  }
  if (resolved.band) {
    document.getElementById('band').value = resolved.band;
    onBandChange().then(() => {
      if (resolved.channel) document.getElementById('channel').value = resolved.channel;
    });
  } else if (resolved.channel) {
    document.getElementById('channel').value = resolved.channel;
  }
}

function warningId(ch) {
  return `${ch.field}:${ch.from_val}:${ch.to_val}:${ch.cause_field}`;
}

function copyConfig() {
  if (!currentConfig) return;
  navigator.clipboard.writeText(currentConfig).then(() => notify('✓ Copied to clipboard'));
}

function downloadConfig() {
  if (!currentConfig) return;
  const blob = new Blob([currentConfig], {type:'text/plain'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'hostapd.conf';
  a.click();
  notify('↓ Downloading hostapd.conf');
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

let notifTimer;
function notify(msg) {
  const el = document.getElementById('notif');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(notifTimer);
  notifTimer = setTimeout(() => el.classList.remove('show'), 2500);
}

// Init
loadInterfaces();
loadBackends();
loadLibrary();
onBandChange();
addVendorIE();  // seed one empty IE row in the structured editor
</script>

</body>
</html>

"""


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

    # hostapd does NOT support end-of-line comments — anything after `=` is
    # parsed as part of the value. If an annotation was appended to a config
    # line ("key=value  # ← ..."), split it off and emit the annotation as a
    # standalone comment line ABOVE the directive so hostapd ignores it.
    _ann_split = re.compile(r"^(.*?)\s*(#\s*←\s*.*)$")
    def c(t=""):
        if t and not t.lstrip().startswith("#"):
            m = _ann_split.match(t)
            if m:
                cfg = m.group(1).rstrip()
                comment = m.group(2)
                if cfg:
                    lines.append(comment)
                    lines.append(cfg)
                    return
        lines.append(t)

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
    return Response(INDEX_HTML, mimetype="text/html; charset=utf-8")


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
    print("hostapd Configurator — listening on http://0.0.0.0:5000  (Ctrl+C to quit)")
    app.run(host="0.0.0.0", port=5000, debug=False)
