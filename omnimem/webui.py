from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__ as OMNIMEM_VERSION
from .core import (
    LAYER_SET,
    apply_decay,
    ensure_storage,
    find_memories,
    move_memory_layer,
    update_memory_content,
    resolve_paths,
    save_config,
    sync_error_hint,
    utc_now,
    write_memory,
)


HTML_PAGE = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>OmniMem WebUI</title>
  <style>
    :root {
      --bg: #f6f7fb;
      --bg2: #ffffff;
      --card: rgba(255,255,255,.86);
      --card2: rgba(255,255,255,.94);
      --ink: #0b1220;
      --muted: #445069;
      --line: rgba(11,18,32,.12);
      --line2: rgba(11,18,32,.18);
      --shadow: 0 18px 50px rgba(11,18,32,.10);
      --shadow2: 0 10px 26px rgba(11,18,32,.08);
      --accent: #0ea5e9;
      --accent2: #22c55e;
      --warn: #f59e0b;
      --bad: #ef4444;
      --good: #16a34a;
      --tab: rgba(14,165,233,.10);
      --r12: 12px;
      --r14: 14px;
      --r16: 16px;
      --r18: 18px;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Avenir Next", "Helvetica Neue", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(1200px 700px at 80% 0%, rgba(14,165,233,.14), transparent 60%),
        radial-gradient(980px 560px at 10% 10%, rgba(34,197,94,.10), transparent 60%),
        radial-gradient(980px 560px at 90% 85%, rgba(245,158,11,.10), transparent 55%),
        linear-gradient(180deg, var(--bg), #eef1f8 65%, #e9edf8);
      min-height: 100vh;
    }

    .wrap { max-width: 1120px; margin: 22px auto; padding: 0 16px 46px; }
    .hero {
      padding: 18px;
      border: 1px solid var(--line);
      background: linear-gradient(180deg, var(--card2), var(--card));
      border-radius: var(--r18);
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }
    h1 { margin: 0 0 6px; font-size: 24px; letter-spacing: .2px; }
    h3 { margin: 0 0 10px; font-size: 14px; letter-spacing: .2px; }
    .small { font-size: 12px; color: var(--muted); }
    .hero-head { display:flex; justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap; }

    .lang {
      border: 1px solid var(--line);
      border-radius: var(--r12);
      padding: 8px 10px;
      background: rgba(255,255,255,.80);
      color: var(--ink);
      outline: none;
    }
    .lang:focus { border-color: rgba(14,165,233,.55); box-shadow: 0 0 0 4px rgba(14,165,233,.14); }

    .tabs { display:flex; gap:10px; margin-top:14px; flex-wrap:wrap; }
    .tab-btn {
      border: 1px solid var(--line);
      background: rgba(255,255,255,.76);
      color: var(--ink);
      border-radius: 999px;
      padding: 8px 12px;
      cursor:pointer;
      transition: transform .12s ease, border-color .12s ease, background .12s ease, box-shadow .12s ease;
      box-shadow: 0 1px 0 rgba(11,18,32,.04);
    }
    .tab-btn:hover { transform: translateY(-1px); border-color: var(--line2); box-shadow: 0 10px 18px rgba(11,18,32,.06); }
    .tab-btn.active { background: var(--tab); border-color: rgba(14,165,233,.35); }

    .panel { display:none; margin-top:16px; animation: fadeUp .18s ease both; }
    .panel.active { display:block; }
    @keyframes fadeUp { from { opacity: 0; transform: translateY(8px);} to { opacity: 1; transform: translateY(0);} }

    .grid { display:grid; grid-template-columns: 1fr 1fr; gap:16px; }
    .card {
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,.92), rgba(255,255,255,.78));
      border-radius: var(--r18);
      padding: 16px;
      box-shadow: var(--shadow2);
    }
    .wide { grid-column: 1 / -1; }

	    label { display:block; font-size: 12px; margin-top: 8px; color: var(--muted); }
	    input {
	      width:100%;
	      border: 1px solid var(--line);
	      background: rgba(255,255,255,.86);
	      border-radius: var(--r12);
	      padding: 10px 12px;
	      margin-top: 6px;
	      outline: none;
	    }
	    input[type="range"] {
	      padding: 0;
	      height: 28px;
	      background: transparent;
	      border-color: transparent;
	    }
	    input[type="range"]:focus { box-shadow: none; }
	    input[type="range"]::-webkit-slider-runnable-track { height: 10px; border-radius: 999px; background: rgba(11,18,32,.10); }
	    input[type="range"]::-webkit-slider-thumb {
	      -webkit-appearance: none;
	      appearance: none;
	      width: 18px;
	      height: 18px;
	      border-radius: 999px;
	      margin-top: -4px;
	      background: linear-gradient(180deg, rgba(14,165,233,.95), rgba(14,165,233,.70));
	      border: 1px solid rgba(11,18,32,.18);
	      box-shadow: 0 10px 18px rgba(11,18,32,.14);
	    }
	    input[type="range"]::-moz-range-track { height: 10px; border-radius: 999px; background: rgba(11,18,32,.10); }
	    input[type="range"]::-moz-range-thumb {
	      width: 18px;
	      height: 18px;
	      border-radius: 999px;
	      background: linear-gradient(180deg, rgba(14,165,233,.95), rgba(14,165,233,.70));
	      border: 1px solid rgba(11,18,32,.18);
	      box-shadow: 0 10px 18px rgba(11,18,32,.14);
	    }
    input:focus { border-color: rgba(14,165,233,.55); box-shadow: 0 0 0 4px rgba(14,165,233,.14); }

    button {
      border: 1px solid rgba(14,165,233,.22);
      background: linear-gradient(180deg, rgba(14,165,233,.18), rgba(14,165,233,.08));
      color: var(--ink);
      border-radius: var(--r12);
      padding: 10px 12px;
      margin-top: 10px;
      cursor:pointer;
      transition: transform .12s ease, filter .12s ease, border-color .12s ease, box-shadow .12s ease;
      box-shadow: 0 10px 18px rgba(11,18,32,.06);
    }
	    button:hover { transform: translateY(-1px); filter: brightness(1.06); border-color: rgba(14,165,233,.35); }
	    button:active { transform: translateY(0px); }
	    button.secondary { border-color: rgba(11,18,32,.12); background: rgba(255,255,255,.76); box-shadow: 0 6px 14px rgba(11,18,32,.06); }
	    button.danger { border-color: rgba(239,68,68,.30); background: linear-gradient(180deg, rgba(239,68,68,.18), rgba(239,68,68,.06)); }
	    button:disabled { opacity: .45; cursor: not-allowed; transform: none; filter: none; }

    .row-btn { display:flex; gap:10px; flex-wrap:wrap; }
    .advanced-only { display:none !important; }
    body.advanced .advanced-only { display: revert !important; }

	    table { width:100%; border-collapse: collapse; font-size: 13px; }
	    th, td { padding:10px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align: top; }
	    th { font-size: 12px; color: var(--muted); font-weight: 600; }
	    thead th { position: sticky; top: 0; background: rgba(255,255,255,.92); backdrop-filter: blur(10px); }
	    tbody tr:hover { background: rgba(14,165,233,.06); }
	    tbody tr.row-selected { background: rgba(14,165,233,.10); }
	    tbody tr.row-selected td { border-bottom-color: rgba(14,165,233,.25); }
    a { color: rgba(14,165,233,.95); text-decoration: none; }
    a:hover { text-decoration: underline; }

    .pill { display:inline-flex; align-items:center; gap:6px; padding:4px 10px; border-radius: 999px; border:1px solid var(--line); background: rgba(255,255,255,.86); font-size: 12px; color: var(--muted); }
    .pill b { color: var(--ink); font-weight: 650; }
    .bar { height: 8px; background: rgba(11,18,32,.08); border-radius: 999px; overflow:hidden; }
    .bar > i { display:block; height: 100%; width: 0%; background: linear-gradient(90deg, rgba(14,165,233,.95), rgba(34,197,94,.85)); }
    .kpi { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top: 8px; }
    .layer-card { cursor:pointer; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; font-size: 12px; color: rgba(68,80,105,.95); }
    .ok { color: var(--good); }
    .err { color: var(--bad); }
    .warn { color: var(--warn); }

    .toast {
      position: fixed;
      right: 18px;
      bottom: 18px;
      min-width: 260px;
      max-width: 520px;
      border: 1px solid var(--line);
      border-radius: var(--r16);
      padding: 12px;
      background: rgba(255,255,255,.92);
      box-shadow: var(--shadow);
      display:none;
      z-index: 50;
    }
    .toast.show { display:block; animation: fadeUp .16s ease both; }
    .toast-title { font-size: 12px; color: var(--muted); }
    .toast-body { margin-top: 4px; font-size: 13px; color: var(--ink); }

    .overlay {
      position: fixed;
      inset: 0;
      background: rgba(11,18,32,.38);
      backdrop-filter: blur(4px);
      display:none;
      z-index: 40;
    }
    .overlay.show { display:block; }
    .drawer {
      position: fixed;
      top: 0;
      right: 0;
      height: 100vh;
      width: min(560px, 92vw);
      background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(255,255,255,.88));
      border-left: 1px solid var(--line);
      box-shadow: var(--shadow);
      transform: translateX(102%);
      transition: transform .18s ease;
      z-index: 45;
      overflow: auto;
    }
    .drawer.show { transform: translateX(0%); }
    .drawer-head {
      position: sticky;
      top: 0;
      padding: 14px 14px 10px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.92);
      backdrop-filter: blur(10px);
      z-index: 1;
    }
	    .drawer-title { font-size: 14px; font-weight: 650; letter-spacing: .2px; }
	    .drawer-sub { margin-top: 6px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
	    .drawer-body { padding: 14px; }
	    .drawer-body textarea { width:100%; min-height: 260px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace; font-size: 12px; }
	    .sig-grid { display:grid; grid-template-columns: 1fr; gap: 10px; margin-top: 8px; }
	    .sig-row { display:flex; gap:10px; align-items:center; }
	    .sig-label { width: 96px; font-size: 12px; color: var(--muted); }
	    .sig-val { width: 54px; text-align:right; font-size: 12px; color: var(--muted); }
    .sig-row .bar { flex: 1; height: 10px; }
    .sig-row .bar > i { background: linear-gradient(90deg, rgba(14,165,233,.95), rgba(34,197,94,.85)); }
    .kv { display:grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
    .kv .k { font-size: 11px; color: var(--muted); }
    .kv .v { font-size: 12px; color: var(--ink); }
	    .divider { height: 1px; background: var(--line); margin: 14px 0; }
		    .muted-box { padding: 10px; border: 1px solid var(--line); border-radius: var(--r14); background: rgba(255,255,255,.72); }

	    .modal-overlay {
	      position: fixed;
	      inset: 0;
	      background: rgba(11,18,32,.42);
	      backdrop-filter: blur(4px);
	      display:none;
	      z-index: 60;
	    }
	    .modal-overlay.show { display:block; }
	    .modal {
	      position: fixed;
	      left: 50%;
	      top: 50%;
	      transform: translate(-50%, -50%);
	      width: min(820px, 92vw);
	      max-height: min(82vh, 820px);
	      overflow: auto;
	      border: 1px solid var(--line);
	      border-radius: var(--r18);
	      background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(255,255,255,.88));
	      box-shadow: var(--shadow);
	      display:none;
	      z-index: 65;
	    }
	    .modal.show { display:block; animation: fadeUp .16s ease both; }
	    .modal-head { position: sticky; top: 0; padding: 14px; border-bottom: 1px solid var(--line); background: rgba(255,255,255,.92); backdrop-filter: blur(10px); }
	    .modal-body { padding: 14px; }
	    .modal-title { font-size: 14px; font-weight: 700; letter-spacing: .2px; }
		
		    .board {
		      display:grid;
		      grid-template-columns: repeat(4, 1fr);
	      gap: 12px;
	      margin-top: 12px;
	    }
	    .col {
	      border: 1px solid var(--line);
	      border-radius: var(--r18);
	      background: rgba(255,255,255,.78);
	      padding: 10px;
	      min-height: 260px;
	    }
	    .col-head { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
	    .col-title { font-size: 12px; color: var(--muted); letter-spacing: .2px; }
	    .col-title b { color: var(--ink); font-weight: 700; }
	    .col-body { margin-top: 10px; display:flex; flex-direction:column; gap:10px; }
	    .mem-card {
	      border: 1px solid var(--line);
	      border-radius: var(--r16);
	      background: rgba(255,255,255,.92);
	      padding: 10px;
	      box-shadow: 0 10px 22px rgba(11,18,32,.06);
	      cursor: grab;
	      transition: transform .12s ease, border-color .12s ease, box-shadow .12s ease;
	    }
	    .mem-card:hover { transform: translateY(-1px); border-color: var(--line2); box-shadow: 0 18px 36px rgba(11,18,32,.08); }
	    .mem-card:active { cursor: grabbing; }
	    .mem-card.selected { border-color: rgba(14,165,233,.55); box-shadow: 0 0 0 4px rgba(14,165,233,.14), 0 18px 36px rgba(11,18,32,.08); }
	    .mem-card-title { font-size: 13px; color: var(--ink); font-weight: 650; letter-spacing: .1px; }
	    .mem-card-sub { margin-top: 6px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
	    .drop-hot { outline: 2px dashed rgba(14,165,233,.55); outline-offset: 3px; }

	    @media (max-width: 920px) { .grid { grid-template-columns:1fr; } }
	    @media (max-width: 920px) { .board { grid-template-columns:1fr; } }
	  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"hero\">
      <div class=\"hero-head\">
        <div>
          <h1 data-i18n=\"title\">OmniMem WebUI</h1>
	          <div id=\"subTitle\" class=\"small\" data-i18n=\"subtitle_simple\">Simple mode: Status & Actions / Insights / Memory</div>
        </div>
	        <div>
	          <label class=\"small\"><span data-i18n=\"language\">Language</span></label>
	          <select id=\"langSelect\" class=\"lang\">
	            <option value=\"en\">English</option>
	            <option value=\"zh\">中文</option>
	            <option value=\"ja\">日本語</option>
	            <option value=\"de\">Deutsch</option>
	            <option value=\"fr\">Français</option>
	            <option value=\"ru\">Русский</option>
	            <option value=\"it\">Italiano</option>
	            <option value=\"ko\">한국어</option>
	          </select>
            <button id=\"btnToggleAdvanced\" class=\"secondary\" style=\"margin-top:0; margin-left:10px\" data-i18n=\"btn_advanced\">Advanced</button>
            <span id=\"buildInfo\" class=\"small mono\" style=\"margin-left:10px\"></span>
	        </div>
      </div>
	      <div id=\"status\" class=\"small\"></div>
	      <div id=\"daemonState\" class=\"small\"></div>
	      <div id=\"daemonMetrics\" class=\"small\"></div>
	      <div id=\"daemonAdvice\" class=\"small\"></div>
		      <div class=\"row-btn advanced-only\" style=\"margin-top:10px\">
	        <button id=\"btnLiveToggle\" class=\"secondary\" style=\"margin-top:0\">Live: off</button>
	        <select id=\"liveInterval\" class=\"lang\" style=\"max-width:200px\">
	          <option value=\"2000\">2s</option>
	          <option value=\"5000\" selected>5s</option>
	          <option value=\"15000\">15s</option>
	        </select>
	        <select id=\"scopeMode\" class=\"lang\" style=\"max-width:220px\">
	          <option value=\"auto\" selected>Scope: auto</option>
	          <option value=\"active\">Scope: active</option>
	          <option value=\"pin\">Scope: pin</option>
	          <option value=\"none\">Scope: none</option>
	        </select>
	        <select id=\"worksetSelect\" class=\"lang\" style=\"max-width:240px\">
	          <option value=\"\">Workset: (none)</option>
	        </select>
	        <input id=\"worksetName\" placeholder=\"workset name\" style=\"max-width:200px\" />
	        <button id=\"btnWorksetSave\" class=\"secondary\" style=\"margin-top:0\">Save</button>
	        <button id=\"btnWorksetDelete\" class=\"secondary\" style=\"margin-top:0\">Delete</button>
	        <select id=\"shareMode\" class=\"lang\" style=\"max-width:220px\">
	          <option value=\"full\" selected>Share: full</option>
	          <option value=\"prefs\">Share: prefs-only</option>
	        </select>
	        <button id=\"btnWorksetExport\" class=\"secondary\" style=\"margin-top:0\">Export</button>
	        <button id=\"btnWorksetImport\" class=\"secondary\" style=\"margin-top:0\">Import</button>
	        <button id=\"btnWorksetShare\" class=\"secondary\" style=\"margin-top:0\">Share</button>
	        <label style=\"margin-top:0\"><span class=\"small\">Confirm</span>
	          <input id=\"wsConfirm\" type=\"checkbox\" checked style=\"width:auto; margin:0 0 0 6px\" />
	        </label>
	      </div>
		      <div id=\"liveHint\" class=\"small advanced-only\" style=\"margin-top:6px\">Live refresh updates daemon + current tab.</div>
	      <div class=\"tabs\">
	        <button class=\"tab-btn active\" data-tab=\"statusTab\" data-i18n=\"tab_status\">Status & Actions</button>
	        <button class=\"tab-btn\" data-tab=\"insightsTab\" data-i18n=\"tab_insights\">Insights</button>
	        <button class=\"tab-btn advanced-only\" data-tab=\"configTab\" data-i18n=\"tab_config\">Configuration</button>
        <button class=\"tab-btn advanced-only\" data-tab=\"projectTab\" data-i18n=\"tab_project\">Project Integration</button>
        <button class=\"tab-btn\" data-tab=\"memoryTab\" data-i18n=\"tab_memory\">Memory</button>
      </div>
    </div>

    <div id=\"statusTab\" class=\"panel active\">
      <div class=\"grid\">
        <div class=\"card\">
          <h3 data-i18n=\"system_status\">System Status</h3>
          <div id=\"initState\" class=\"small\"></div>
          <div id=\"syncHint\" class=\"small\" style=\"margin-top:8px\"></div>
        </div>
        <div class=\"card\">
          <h3 data-i18n=\"actions\">Actions</h3>
          <div class=\"row-btn\">
            <button id=\"btnSyncStatus\" data-i18n=\"btn_status\">Check Sync Status</button>
            <button id=\"btnSyncBootstrap\" data-i18n=\"btn_bootstrap\">Bootstrap Device Sync</button>
            <button id=\"btnSyncPush\" data-i18n=\"btn_push\">Push</button>
            <button id=\"btnSyncPull\" data-i18n=\"btn_pull\">Pull</button>
          </div>
          <div class=\"row-btn\">
            <button id=\"btnDaemonOn\" data-i18n=\"btn_daemon_on\">Enable Daemon</button>
            <button id=\"btnDaemonOff\" data-i18n=\"btn_daemon_off\">Disable Daemon</button>
            <button id=\"btnConflictRecovery\" style=\"display:none\">Conflict Recovery (status -> pull -> push)</button>
          </div>
          <pre id=\"syncOut\" class=\"small\"></pre>
        </div>
      </div>
    </div>

    <div id=\"insightsTab\" class=\"panel\">
      <div class=\"grid\">
	        <div class=\"card wide\">
	          <h3 data-i18n=\"insights_title\">Layered Memory Map</h3>
	          <div class=\"small\" data-i18n=\"insights_hint\">A quick read of how your knowledge is distributed. Click a layer to filter the Memory tab.</div>
	          <label><span data-i18n=\"mem_project_filter\">Project ID Filter</span><input id=\"insProjectId\" placeholder=\"(empty = all projects)\" /></label>
	          <label>Session ID Filter <input id=\"insSessionId\" placeholder=\"(empty = all sessions)\" /></label>
	          <div class=\"row-btn\">
	            <button id=\"btnInsightsReload\" data-i18n=\"btn_reload\">Reload</button>
	          </div>
	          <div id=\"insLayers\" class=\"grid\" style=\"grid-template-columns: repeat(4, 1fr);\"></div>
	        </div>
	
	        <div class=\"card wide\">
	          <h3>Layer Board</h3>
	          <div class=\"small\">Drag a card to change its layer. Click a card to open full details.</div>
	          <div class=\"row-btn\" style=\"margin-top:10px\">
	            <button id=\"btnBoardSelectToggle\" class=\"secondary\" style=\"margin-top:0\">Select: off</button>
	            <button id=\"btnBoardPromote\" style=\"margin-top:0\" disabled>Promote → long</button>
	            <button id=\"btnBoardDemote\" class=\"secondary\" style=\"margin-top:0\" disabled>Demote → short</button>
	            <button id=\"btnBoardArchive\" class=\"secondary\" style=\"margin-top:0\" disabled>Archive</button>
	            <button id=\"btnBoardClear\" class=\"secondary\" style=\"margin-top:0\" disabled>Clear</button>
	            <span id=\"boardSelInfo\" class=\"small\" style=\"align-self:center\"></span>
	          </div>
		          <div id=\"layerBoard\" class=\"board\"></div>
		        </div>

          <div class=\"advanced-only\" style=\"display:contents\">
	        <div class=\"card\">
	          <h3 data-i18n=\"ins_kinds\">Kinds</h3>
	          <div id=\"insKinds\" class=\"small\"></div>
	        </div>
        <div class=\"card\">
          <h3 data-i18n=\"ins_activity\">Activity (14d)</h3>
          <div id=\"insActivity\" class=\"small\"></div>
        </div>
        <div class=\"card\">
          <h3 data-i18n=\"ins_govern\">Governance</h3>
          <div class=\"small\" data-i18n=\"ins_govern_hint\">Promote stable knowledge upward; demote volatile, low-reuse items.</div>
          <div class=\"muted-box\" style=\"margin-top:10px\">
            <div class=\"small\"><b>Thresholds</b></div>
            <div class=\"small\" style=\"margin-top:8px\">Promote to long (instant/short)</div>
            <label>importance ≥ <span class=\"mono\" id=\"thrPImpV\"></span>
              <input id=\"thrPImp\" type=\"range\" min=\"0\" max=\"1\" step=\"0.05\" value=\"0.75\" />
            </label>
            <label>confidence ≥ <span class=\"mono\" id=\"thrPConfV\"></span>
              <input id=\"thrPConf\" type=\"range\" min=\"0\" max=\"1\" step=\"0.05\" value=\"0.65\" />
            </label>
            <label>stability ≥ <span class=\"mono\" id=\"thrPStabV\"></span>
              <input id=\"thrPStab\" type=\"range\" min=\"0\" max=\"1\" step=\"0.05\" value=\"0.65\" />
            </label>
            <label>volatility ≤ <span class=\"mono\" id=\"thrPVolV\"></span>
              <input id=\"thrPVol\" type=\"range\" min=\"0\" max=\"1\" step=\"0.05\" value=\"0.65\" />
            </label>
            <div class=\"divider\"></div>
            <div class=\"small\">Demote to short (long)</div>
            <label>volatility ≥ <span class=\"mono\" id=\"thrDVolV\"></span>
              <input id=\"thrDVol\" type=\"range\" min=\"0\" max=\"1\" step=\"0.05\" value=\"0.75\" />
            </label>
            <label>stability ≤ <span class=\"mono\" id=\"thrDStabV\"></span>
              <input id=\"thrDStab\" type=\"range\" min=\"0\" max=\"1\" step=\"0.05\" value=\"0.45\" />
            </label>
            <label>reuse ≤ <span class=\"mono\" id=\"thrDReuseV\"></span>
              <input id=\"thrDReuse\" type=\"range\" min=\"0\" max=\"10\" step=\"1\" value=\"1\" />
            </label>
            <div class=\"row-btn\">
              <button id=\"btnGovernReload\" class=\"secondary\" style=\"margin-top:8px\">Apply</button>
            </div>
          </div>
          <div id=\"insGovern\" class=\"small\"></div>
        </div>
        <div class=\"card wide\">
          <h3 data-i18n=\"ins_tags\">Top Tags</h3>
          <div id=\"insTags\" class=\"small\"></div>
        </div>
        <div class=\"card wide\">
          <h3 data-i18n=\"ins_checkpoints\">Recent Checkpoints</h3>
          <div id=\"insCheckpoints\" class=\"small\"></div>
        </div>
	        <div class=\"card wide\">
	          <h3 data-i18n=\"ins_timeline\">Session Timeline</h3>
	          <div class=\"small\" data-i18n=\"ins_timeline_hint\">Turns and checkpoints, grouped by session. Click an item to open details.</div>
	          <div id=\"insTimeline\" class=\"small\"></div>
	        </div>
	        <div class=\"card wide\">
	          <h3>Sessions Console</h3>
	          <div class=\"small\">Recent sessions with health signals. Use Activate to scope the console.</div>
	          <div class=\"row-btn\">
	            <button id=\"btnSessionsReload\" class=\"secondary\" style=\"margin-top:0\">Reload Sessions</button>
	            <button id=\"btnClearSession\" class=\"secondary\" style=\"margin-top:0\">Clear Active Session</button>
	            <button id=\"btnArchiveActiveSession\" class=\"danger\" style=\"margin-top:0\">Archive Active Session</button>
	          </div>
	          <div class=\"muted-box\" style=\"margin-top:10px\">
	            <div class=\"small\"><b>Archive Options</b></div>
	            <div class=\"row-btn\" style=\"margin-top:8px\">
	              <label style=\"margin-top:0\">from layers
	                <select id=\"sessArchiveFrom\" class=\"lang\" style=\"max-width:260px\">
	                  <option value=\"instant,short\" selected>instant + short</option>
	                  <option value=\"instant\">instant only</option>
	                  <option value=\"short\">short only</option>
	                  <option value=\"instant,short,long\">instant + short + long</option>
	                </select>
	              </label>
	              <label style=\"margin-top:0\">limit
	                <input id=\"sessArchiveLimit\" type=\"number\" min=\"1\" max=\"2000\" value=\"400\" style=\"max-width:180px\" />
	              </label>
	              <label style=\"margin-top:0\">to layer
	                <select id=\"sessArchiveTo\" class=\"lang\" style=\"max-width:220px\">
	                  <option value=\"archive\" selected>archive</option>
	                  <option value=\"short\">short</option>
	                  <option value=\"long\">long</option>
	                </select>
	              </label>
	            </div>
	          </div>
	          <table style=\"margin-top:8px\">
	            <thead>
	              <tr>
	                <th>Session</th>
	                <th>Last</th>
	                <th>Turns</th>
	                <th>Retrieves</th>
	                <th>Checkpoints</th>
	                <th>Avg Drift</th>
	                <th>Switches</th>
	                <th>Actions</th>
	              </tr>
	            </thead>
	            <tbody id=\"sessionsBody\"></tbody>
	          </table>
	        </div>
	        <div class=\"card wide\">
	          <h3>Maintenance</h3>
	          <div class=\"small\">Operational tools to keep the memory model healthy. Use preview first; apply writes a governance event.</div>
	          <div class=\"row-btn\">
	            <label style=\"margin-top:0\">days
	              <input id=\"decayDays\" type=\"number\" min=\"1\" max=\"365\" value=\"14\" style=\"max-width:140px\" />
	            </label>
	            <label style=\"margin-top:0\">layers
	              <input id=\"decayLayers\" value=\"instant,short,long\" style=\"max-width:260px\" />
	            </label>
	            <label style=\"margin-top:0\">limit
	              <input id=\"decayLimit\" type=\"number\" min=\"1\" max=\"2000\" value=\"200\" style=\"max-width:140px\" />
	            </label>
	            <button id=\"btnDecayPreview\" class=\"secondary\" style=\"margin-top:0\">Decay Preview</button>
	            <button id=\"btnDecayApply\" class=\"danger\" style=\"margin-top:0\">Apply Decay</button>
	            <span id=\"decayHint\" class=\"small\" style=\"align-self:center\"></span>
	          </div>
	          <div id=\"decayOut\" class=\"muted-box\" style=\"margin-top:10px\"></div>
	        </div>
	        <div class=\"card wide\">
	          <h3>Governance Log</h3>
	          <div class=\"small\">Operational event stream (promote/reuse/sync/retrieve/write). Click an event to inspect payload.</div>
	          <div class=\"row-btn\">
	            <label style=\"margin-top:0\">event type
	              <select id=\"evtType\" class=\"lang\" style=\"max-width:260px\">
	                <option value=\"\">(all)</option>
	                <option value=\"memory.promote\">memory.promote</option>
	                <option value=\"memory.decay\">memory.decay</option>
	                <option value=\"memory.reuse\">memory.reuse</option>
	                <option value=\"memory.sync\">memory.sync</option>
	                <option value=\"memory.retrieve\">memory.retrieve</option>
	                <option value=\"memory.write\">memory.write</option>
	                <option value=\"memory.checkpoint\">memory.checkpoint</option>
	                <option value=\"memory.update\">memory.update</option>
	              </select>
	            </label>
	            <label style=\"margin-top:0\">search
	              <input id=\"evtSearch\" placeholder=\"type to filter (summary/type/id/project/session)\" style=\"max-width:360px\" />
	            </label>
	            <button id=\"btnPinWorkset\" class=\"secondary\" style=\"margin-top:0\">Pin Workset</button>
	            <button id=\"btnClearPin\" class=\"secondary\" style=\"margin-top:0\">Clear Pin</button>
	            <span id=\"pinHint\" class=\"small\" style=\"align-self:center\"></span>
	            <button id=\"btnEventsReload\" class=\"secondary\" style=\"margin-top:0\">Reload Events</button>
	          </div>
	          <div id=\"evtStats\" class=\"muted-box\" style=\"margin-top:10px\"></div>
	          <div class=\"row-btn\" style=\"margin-top:10px\">
	            <button id=\"btnEventOpenMem\" class=\"secondary\" style=\"margin-top:0\" disabled>Open Memory</button>
	            <button id=\"btnEventActivate\" class=\"secondary\" style=\"margin-top:0\" disabled>Activate Session</button>
	            <button id=\"btnEventShowSession\" class=\"secondary\" style=\"margin-top:0\" disabled>Show Session Events</button>
	            <button id=\"btnEventRevert\" class=\"danger\" style=\"margin-top:0\" disabled>Revert Promote</button>
	            <button id=\"btnEventCopy\" class=\"secondary\" style=\"margin-top:0\" disabled>Copy Payload</button>
	            <span id=\"eventHint\" class=\"small\" style=\"align-self:center\"></span>
	          </div>
	          <table style=\"margin-top:8px; table-layout:fixed\">
	            <colgroup>
	              <col style=\"width:160px\" />
	              <col style=\"width:150px\" />
	              <col style=\"width:140px\" />
	              <col style=\"width:120px\" />
	              <col style=\"width:140px\" />
	              <col />
	            </colgroup>
	            <thead>
	              <tr>
	                <th><a href=\"#\" data-sort=\"event_time\">Time</a></th>
	                <th><a href=\"#\" data-sort=\"event_type\">Type</a></th>
	                <th>Memory</th>
	                <th>Project</th>
	                <th>Session</th>
	                <th>Summary</th>
	              </tr>
	            </thead>
	            <tbody id=\"eventsBody\"></tbody>
	          </table>
	          <div class=\"divider\"></div>
		          <div class=\"small\"><b>Event Payload</b></div>
		          <pre id=\"eventView\" class=\"mono\" style=\"white-space:pre-wrap; margin-top:8px\"></pre>
		        </div>
          </div>
		      </div>
		    </div>

    <div id=\"configTab\" class=\"panel advanced-only\">
      <div class=\"grid\">
        <div class=\"card wide\">
          <h3 data-i18n=\"config_title\">Configuration</h3>
          <form id=\"cfgForm\">
            <label><span data-i18n=\"cfg_path\">Config Path</span><input name=\"config_path\" readonly /></label>
            <label><span data-i18n=\"cfg_home\">Home</span><input name=\"home\" /></label>
            <label><span data-i18n=\"cfg_markdown\">Markdown Path</span><input name=\"markdown\" /></label>
            <label><span data-i18n=\"cfg_jsonl\">JSONL Path</span><input name=\"jsonl\" /></label>
            <label><span data-i18n=\"cfg_sqlite\">SQLite Path</span><input name=\"sqlite\" /></label>
            <label><span data-i18n=\"cfg_remote_name\">Git Remote Name</span><input name=\"remote_name\" /></label>
            <label><span data-i18n=\"cfg_remote_url\">Git Remote URL</span><input name=\"remote_url\" placeholder=\"git@github.com:user/repo.git\" /></label>
            <label><span data-i18n=\"cfg_branch\">Git Branch</span><input name=\"branch\" /></label>
            <button type=\"submit\" data-i18n=\"btn_save\">Save Configuration</button>
          </form>
        </div>
      </div>
    </div>

    <div id=\"projectTab\" class=\"panel advanced-only\">
      <div class=\"grid\">
        <div class=\"card wide\">
          <h3 data-i18n=\"project_title\">Project Integration</h3>
          <label><span data-i18n=\"project_path\">Project Path</span><input id=\"projectPath\" placeholder=\"/path/to/your/project\" /></label>
          <div class=\"row-btn\">
            <button id=\"btnBrowseProject\" data-i18n=\"btn_browse_project\">Browse Directory</button>
            <button id=\"btnUseCwd\" data-i18n=\"btn_use_cwd\">Use Server CWD</button>
          </div>
          <div id=\"browserPanel\" class=\"card\" style=\"margin-top:10px; display:none;\">
            <div class=\"small\" data-i18n=\"browser_title\">Directory Browser</div>
            <div id=\"browserPath\" class=\"small\" style=\"margin:8px 0\"></div>
            <div class=\"row-btn\">
              <button id=\"btnBrowserUp\" data-i18n=\"btn_browser_up\">Up</button>
              <button id=\"btnBrowserSelect\" data-i18n=\"btn_browser_select\">Select This Directory</button>
              <button id=\"btnBrowserClose\" data-i18n=\"btn_browser_close\">Close</button>
            </div>
            <div id=\"browserList\" class=\"small\" style=\"margin-top:8px\"></div>
          </div>
          <label><span data-i18n=\"project_id\">Project ID</span><input id=\"projectId\" placeholder=\"my-project\" /></label>
          <div class=\"row-btn\">
            <button id=\"btnProjectAttach\" data-i18n=\"btn_project_attach\">Attach Project + Install Agent Rules</button>
            <button id=\"btnProjectDetach\" data-i18n=\"btn_project_detach\">Detach Project</button>
          </div>
          <div class=\"small\" data-i18n=\"project_hint\">Attach will create .omnimem files and inject managed memory protocol blocks into AGENTS.md / CLAUDE.md / .cursorrules.</div>
          <pre id=\"projectOut\" class=\"small\"></pre>
        </div>
        <div class=\"card wide\">
          <h3 data-i18n=\"project_list_title\">Attached Projects (Local)</h3>
          <div class=\"row-btn\">
            <button id=\"btnProjectsReload\" data-i18n=\"btn_projects_reload\">Reload Projects</button>
          </div>
          <table>
            <thead>
              <tr>
                <th data-i18n=\"th_project\">Project</th>
                <th data-i18n=\"project_path\">Project Path</th>
                <th data-i18n=\"th_updated\">Updated At</th>
                <th data-i18n=\"th_actions\">Actions</th>
              </tr>
            </thead>
            <tbody id=\"projectsBody\"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div id=\"memoryTab\" class=\"panel\">
      <div class=\"grid\">
	        <div class=\"card wide\">
	          <h3 data-i18n=\"mem_recent\">Recent Memories</h3>
	          <div id=\"layerStats\" class=\"small\" style=\"margin:6px 0\"></div>
	          <label><span data-i18n=\"mem_project_filter\">Project ID Filter</span><input id=\"memProjectId\" placeholder=\"(empty = all projects)\" /></label>
	          <label>Session ID Filter <input id=\"memSessionId\" placeholder=\"(empty = all sessions)\" /></label>
	          <label>Query
	            <input id=\"memQuery\" placeholder=\"(optional) FTS query\" />
	          </label>
	          <label>Layer Filter
	            <select id=\"memLayer\" class=\"lang\" style=\"width:100%; max-width:260px;\">
	              <option value=\"\">(all)</option>
	              <option value=\"instant\">instant</option>
	              <option value=\"short\">short</option>
	              <option value=\"long\">long</option>
	              <option value=\"archive\">archive</option>
	            </select>
	          </label>
		          <div class=\"row-btn\">
		            <button id=\"btnMemReload\" data-i18n=\"btn_mem_reload\">Reload</button>
		            <button id=\"btnMemOpenBoard\" class=\"secondary\" style=\"margin-top:0\">Layer Board</button>
		          </div>
	          <div class=\"small\" data-i18n=\"mem_hint\">Click an ID to open full content</div>
          <table>
            <thead>
              <tr>
                <th data-i18n=\"th_id\">ID</th>
                <th data-i18n=\"th_project\">Project</th>
                <th data-i18n=\"th_layer\">Layer</th>
                <th data-i18n=\"th_kind\">Kind</th>
                <th data-i18n=\"th_summary\">Summary</th>
                <th data-i18n=\"th_updated\">Updated At</th>
              </tr>
            </thead>
            <tbody id=\"memBody\"></tbody>
          </table>
        </div>
        <div class=\"card wide\">
          <h3 data-i18n=\"mem_content\">Memory Content</h3>
          <pre id=\"memView\" style=\"white-space:pre-wrap\"></pre>
        </div>
      </div>
    </div>
	  </div>
	
	  <div id=\"toast\" class=\"toast\" role=\"status\" aria-live=\"polite\">
	    <div class=\"toast-title\" id=\"toastTitle\">Notification</div>
	    <div class=\"toast-body\" id=\"toastBody\"></div>
	  </div>
	
	  <div id=\"overlay\" class=\"overlay\" aria-hidden=\"true\"></div>
	  <div id=\"modalOverlay\" class=\"modal-overlay\" aria-hidden=\"true\"></div>
	  <div id=\"wsModal\" class=\"modal\" role=\"dialog\" aria-modal=\"true\" aria-label=\"Workset import preview\">
	    <div class=\"modal-head\">
	      <div style=\"display:flex; justify-content:space-between; gap:10px; align-items:flex-start;\">
	        <div>
	          <div class=\"modal-title\" id=\"wsModalTitle\">Import Workset</div>
	          <div class=\"small\" id=\"wsModalSource\" style=\"margin-top:6px\"></div>
	        </div>
	        <button id=\"btnWsModalClose\" class=\"secondary\" style=\"margin-top:0\">Close</button>
	      </div>
	    </div>
	    <div class=\"modal-body\">
	      <label style=\"margin-top:0\">Name
	        <input id=\"wsImportName\" placeholder=\"workset name\" />
	      </label>
	      <div class=\"row-btn\" style=\"margin-top:10px\">
	        <label style=\"margin-top:0\"><span class=\"small\">Apply project</span>
	          <input id=\"wsApplyProject\" type=\"checkbox\" checked style=\"width:auto; margin:0 0 0 6px\" />
	        </label>
	        <label style=\"margin-top:0\"><span class=\"small\">Apply session</span>
	          <input id=\"wsApplySession\" type=\"checkbox\" checked style=\"width:auto; margin:0 0 0 6px\" />
	        </label>
	        <label style=\"margin-top:0\"><span class=\"small\">Apply prefs</span>
	          <input id=\"wsApplyPrefs\" type=\"checkbox\" checked style=\"width:auto; margin:0 0 0 6px\" />
	        </label>
	      </div>
	      <div class=\"divider\"></div>
	      <div class=\"small\"><b>Preview</b></div>
	      <pre id=\"wsImportPreview\" class=\"mono\" style=\"white-space:pre-wrap; margin-top:8px\"></pre>
	      <div class=\"row-btn\" style=\"margin-top:10px\">
	        <button id=\"btnWsImportApply\" style=\"margin-top:0\">Import + Apply</button>
	        <button id=\"btnWsImportOnly\" class=\"secondary\" style=\"margin-top:0\">Import Only</button>
	        <button id=\"btnWsImportCancel\" class=\"secondary\" style=\"margin-top:0\">Cancel</button>
	      </div>
	    </div>
	  </div>
	  <div id=\"drawer\" class=\"drawer\" role=\"dialog\" aria-modal=\"true\" aria-label=\"Memory details\">
	    <div class=\"drawer-head\">
	      <div style=\"display:flex; justify-content:space-between; gap:10px; align-items:flex-start;\">
	        <div>
          <div class=\"drawer-title\" id=\"dTitle\">Memory</div>
          <div class=\"drawer-sub\" id=\"dPills\"></div>
          <div class=\"small\" id=\"dReco\" style=\"margin-top:8px\"></div>
        </div>
        <button id=\"btnDrawerClose\" class=\"secondary\" style=\"margin-top:0\">Close</button>
	      </div>
	      <div class=\"row-btn\" style=\"margin-top:10px\">
	        <button id=\"btnEdit\" class=\"secondary\" style=\"margin-top:0\">Edit</button>
	        <button id=\"btnSave\" style=\"margin-top:0; display:none\">Save</button>
	        <button id=\"btnCancel\" class=\"secondary\" style=\"margin-top:0; display:none\">Cancel</button>
	        <button id=\"btnPromote\" style=\"margin-top:0\">Promote → long</button>
	        <button id=\"btnDemote\" class=\"secondary\" style=\"margin-top:0\">Demote → short</button>
	        <button id=\"btnArchive\" class=\"secondary\" style=\"margin-top:0\">Archive</button>
	      </div>
	    </div>
	    <div class=\"drawer-body\">
      <div class=\"muted-box\">
        <div class=\"small\"><b>Signals</b></div>
        <div class=\"sig-grid\" id=\"dSignals\"></div>
      </div>
      <div class=\"kv\" id=\"dMeta\"></div>
      <div class=\"divider\"></div>
      <div class=\"small\"><b>Refs</b></div>
	      <div id=\"dRefs\" class=\"small\"></div>
	      <div class=\"divider\"></div>
	      <div class=\"small\"><b>Body</b></div>
	      <div id=\"dEditBox\" style=\"margin-top:8px; display:none\">
	        <label style=\"margin-top:0\">Summary
	          <input id=\"dEditSummary\" />
	        </label>
	        <label>Tags (comma-separated)
	          <input id=\"dEditTags\" placeholder=\"tag1,tag2\" />
	        </label>
	        <label>Body (markdown)
	          <textarea id=\"dEditBody\" class=\"mono\"></textarea>
	        </label>
	      </div>
	      <pre id=\"dBodyView\" class=\"mono\" style=\"white-space:pre-wrap; margin-top:8px\"></pre>
	    </div>
	  </div>

  <script>
    const I18N = {
      en: {
        title: 'OmniMem WebUI', subtitle_simple: 'Simple mode: Status & Actions / Insights / Memory', subtitle_adv: 'Advanced mode: full console', language: 'Language',
        btn_advanced: 'Advanced', btn_simple: 'Simple',
        tab_status: 'Status & Actions', tab_insights: 'Insights', tab_config: 'Configuration', tab_project: 'Project Integration', tab_memory: 'Memory',
        system_status: 'System Status', actions: 'Actions',
        insights_title: 'Layered Memory Map', insights_hint: 'A quick read of how your knowledge is distributed. Click a layer to filter the Memory tab.',
        ins_kinds: 'Kinds', ins_activity: 'Activity (14d)', ins_govern: 'Governance', ins_govern_hint: 'Promote stable knowledge upward; demote volatile, low-reuse items.',
        ins_tags: 'Top Tags', ins_checkpoints: 'Recent Checkpoints', ins_timeline: 'Session Timeline', ins_timeline_hint: 'Turns and checkpoints, grouped by session. Click an item to open details.',
        btn_reload: 'Reload',
        btn_status: 'Check Sync Status', btn_bootstrap: 'Bootstrap Device Sync', btn_push: 'Push', btn_pull: 'Pull',
        btn_daemon_on: 'Enable Daemon', btn_daemon_off: 'Disable Daemon',
        config_title: 'Configuration', cfg_path: 'Config Path', cfg_home: 'Home', cfg_markdown: 'Markdown Path', cfg_jsonl: 'JSONL Path', cfg_sqlite: 'SQLite Path', cfg_remote_name: 'Git Remote Name', cfg_remote_url: 'Git Remote URL', cfg_branch: 'Git Branch', btn_save: 'Save Configuration',
        mem_recent: 'Recent Memories', mem_hint: 'Click an ID to open full content', mem_content: 'Memory Content',
        mem_project_filter: 'Project ID Filter', btn_mem_reload: 'Reload',
        th_id: 'ID', th_project: 'Project', th_layer: 'Layer', th_kind: 'Kind', th_summary: 'Summary', th_updated: 'Updated At',
        project_title: 'Project Integration', project_path: 'Project Path', project_id: 'Project ID',
        btn_browse_project: 'Browse Directory', btn_use_cwd: 'Use Server CWD',
        browser_title: 'Directory Browser', btn_browser_up: 'Up', btn_browser_select: 'Select This Directory', btn_browser_close: 'Close',
        btn_project_attach: 'Attach Project + Install Agent Rules', btn_project_detach: 'Detach Project',
        project_list_title: 'Attached Projects (Local)', btn_projects_reload: 'Reload Projects',
        project_hint: 'Attach will create .omnimem files and inject managed memory protocol blocks into AGENTS.md / CLAUDE.md / .cursorrules.',
        cfg_saved: 'Configuration saved', cfg_failed: 'Save failed',
        project_attach_ok: 'Project attached', project_detach_ok: 'Project detached', project_failed: 'Project action failed',
        th_actions: 'Actions', btn_use: 'Use', btn_detach: 'Detach',
        init_ok: 'Config state: initialized', init_hint_ok: 'Daemon runs quasi-realtime sync in background (can be disabled).',
        init_missing: 'Config state: not initialized (save configuration first)', init_hint_missing: 'Daemon is disabled until configuration is initialized.',
        daemon_state: (d) => `Daemon: ${d.running ? 'running' : 'stopped'}, enabled=${d.enabled}, initialized=${d.initialized}`
      },
      zh: {
        title: 'OmniMem 网页控制台', subtitle_simple: '简洁模式：状态与动作 / 洞察 / 记忆', subtitle_adv: '高级模式：完整控制台', language: '语言',
        btn_advanced: '高级', btn_simple: '简洁',
        tab_status: '状态与动作', tab_insights: '洞察', tab_config: '配置', tab_project: '项目集成', tab_memory: '记忆',
        system_status: '系统状态', actions: '动作',
        insights_title: '分层记忆地图', insights_hint: '快速查看你的知识在各层级的分布。点击层级可跳转并过滤记忆列表。',
        ins_kinds: '类型分布', ins_activity: '活跃度 (14天)', ins_govern: '治理', ins_govern_hint: '把稳定知识向上提升，把高波动低复用内容降级。',
        ins_tags: '常用标签', ins_checkpoints: '最近检查点', ins_timeline: '会话时间线', ins_timeline_hint: '按 session 聚合的 turns 与 checkpoints。点击条目查看详情。',
        btn_reload: '刷新',
        btn_status: '检查同步状态', btn_bootstrap: '首次设备对齐', btn_push: '推送', btn_pull: '拉取',
        btn_daemon_on: '开启守护', btn_daemon_off: '关闭守护',
        config_title: '配置', cfg_path: '配置路径', cfg_home: '主目录', cfg_markdown: 'Markdown 路径', cfg_jsonl: 'JSONL 路径', cfg_sqlite: 'SQLite 路径', cfg_remote_name: 'Git 远端名', cfg_remote_url: 'Git 远端 URL', cfg_branch: 'Git 分支', btn_save: '保存配置',
        mem_recent: '最近记忆', mem_hint: '点击 ID 查看正文', mem_content: '记忆正文',
        mem_project_filter: '项目 ID 过滤', btn_mem_reload: '刷新',
        th_id: 'ID', th_project: '项目', th_layer: '层级', th_kind: '类型', th_summary: '摘要', th_updated: '更新时间',
        cfg_saved: '配置已保存', cfg_failed: '保存失败',
        init_ok: '配置状态：已初始化', init_hint_ok: '后台守护进程会自动准实时同步（可关闭）。',
        init_missing: '配置状态：未初始化（请先保存配置）', init_hint_missing: '未初始化前不会启动守护进程。',
        daemon_state: (d) => `守护进程：${d.running ? '运行中' : '已停止'}，启用=${d.enabled}，初始化=${d.initialized}`
      },
      ja: {
        title: 'OmniMem WebUI', subtitle: 'シンプルモード：状態と操作 / 設定 / メモリ', language: '言語',
        tab_status: '状態と操作', tab_config: '設定', tab_memory: 'メモリ',
        system_status: 'システム状態', actions: '操作',
        btn_status: '同期状態を確認', btn_bootstrap: '初回デバイス同期', btn_push: 'Push', btn_pull: 'Pull',
        btn_daemon_on: 'デーモン有効', btn_daemon_off: 'デーモン無効',
        config_title: '設定', cfg_path: '設定パス', cfg_home: 'ホーム', cfg_markdown: 'Markdown パス', cfg_jsonl: 'JSONL パス', cfg_sqlite: 'SQLite パス', cfg_remote_name: 'Git リモート名', cfg_remote_url: 'Git リモート URL', cfg_branch: 'Git ブランチ', btn_save: '設定を保存',
        mem_recent: '最近のメモリ', mem_hint: 'ID をクリックして本文を表示', mem_content: 'メモリ内容',
        th_id: 'ID', th_layer: 'レイヤー', th_kind: '種類', th_summary: '要約', th_updated: '更新日時',
        cfg_saved: '設定を保存しました', cfg_failed: '保存に失敗しました',
        init_ok: '設定状態：初期化済み', init_hint_ok: 'デーモンがバックグラウンドで準リアルタイム同期します。',
        init_missing: '設定状態：未初期化（先に保存してください）', init_hint_missing: '初期化されるまでデーモンは無効です。',
        daemon_state: (d) => `Daemon: ${d.running ? 'running' : 'stopped'}, enabled=${d.enabled}, initialized=${d.initialized}`
      },
      de: {
        title: 'OmniMem WebUI', subtitle: 'Einfachmodus: Status & Aktionen / Konfiguration / Speicher', language: 'Sprache',
        tab_status: 'Status & Aktionen', tab_config: 'Konfiguration', tab_memory: 'Speicher',
        system_status: 'Systemstatus', actions: 'Aktionen',
        btn_status: 'Sync-Status prüfen', btn_bootstrap: 'Erstsynchronisierung', btn_push: 'Push', btn_pull: 'Pull',
        btn_daemon_on: 'Daemon aktivieren', btn_daemon_off: 'Daemon deaktivieren',
        config_title: 'Konfiguration', cfg_path: 'Konfigurationspfad', cfg_home: 'Home', cfg_markdown: 'Markdown-Pfad', cfg_jsonl: 'JSONL-Pfad', cfg_sqlite: 'SQLite-Pfad', cfg_remote_name: 'Git Remote-Name', cfg_remote_url: 'Git Remote-URL', cfg_branch: 'Git-Branch', btn_save: 'Konfiguration speichern',
        mem_recent: 'Aktuelle Speicher', mem_hint: 'ID anklicken, um Inhalt zu öffnen', mem_content: 'Speicherinhalt',
        th_id: 'ID', th_layer: 'Ebene', th_kind: 'Typ', th_summary: 'Zusammenfassung', th_updated: 'Aktualisiert',
        cfg_saved: 'Konfiguration gespeichert', cfg_failed: 'Speichern fehlgeschlagen',
        init_ok: 'Konfigurationsstatus: initialisiert', init_hint_ok: 'Daemon synchronisiert quasi in Echtzeit im Hintergrund.',
        init_missing: 'Konfigurationsstatus: nicht initialisiert', init_hint_missing: 'Daemon ist deaktiviert, bis gespeichert wird.',
        daemon_state: (d) => `Daemon: ${d.running ? 'running' : 'stopped'}, enabled=${d.enabled}, initialized=${d.initialized}`
      },
      fr: {
        title: 'OmniMem WebUI', subtitle: 'Mode simple : État et actions / Configuration / Mémoire', language: 'Langue',
        tab_status: 'État et actions', tab_config: 'Configuration', tab_memory: 'Mémoire',
        system_status: 'État du système', actions: 'Actions',
        btn_status: 'Vérifier la sync', btn_bootstrap: 'Sync initiale appareil', btn_push: 'Push', btn_pull: 'Pull',
        btn_daemon_on: 'Activer le daemon', btn_daemon_off: 'Désactiver le daemon',
        config_title: 'Configuration', cfg_path: 'Chemin config', cfg_home: 'Home', cfg_markdown: 'Chemin Markdown', cfg_jsonl: 'Chemin JSONL', cfg_sqlite: 'Chemin SQLite', cfg_remote_name: 'Nom remote Git', cfg_remote_url: 'URL remote Git', cfg_branch: 'Branche Git', btn_save: 'Enregistrer',
        mem_recent: 'Mémoires récentes', mem_hint: 'Cliquez un ID pour ouvrir le contenu', mem_content: 'Contenu mémoire',
        th_id: 'ID', th_layer: 'Couche', th_kind: 'Type', th_summary: 'Résumé', th_updated: 'Mise à jour',
        cfg_saved: 'Configuration enregistrée', cfg_failed: "Échec de l'enregistrement",
        init_ok: 'État config : initialisée', init_hint_ok: 'Le daemon synchronise en quasi temps réel.',
        init_missing: 'État config : non initialisée', init_hint_missing: 'Le daemon reste désactivé avant initialisation.',
        daemon_state: (d) => `Daemon: ${d.running ? 'running' : 'stopped'}, enabled=${d.enabled}, initialized=${d.initialized}`
      },
      ru: {
        title: 'OmniMem WebUI', subtitle: 'Простой режим: статус и действия / конфигурация / память', language: 'Язык',
        tab_status: 'Статус и действия', tab_config: 'Конфигурация', tab_memory: 'Память',
        system_status: 'Состояние системы', actions: 'Действия',
        btn_status: 'Проверить синхронизацию', btn_bootstrap: 'Первичная синхронизация', btn_push: 'Push', btn_pull: 'Pull',
        btn_daemon_on: 'Включить daemon', btn_daemon_off: 'Выключить daemon',
        config_title: 'Конфигурация', cfg_path: 'Путь к конфигу', cfg_home: 'Home', cfg_markdown: 'Путь Markdown', cfg_jsonl: 'Путь JSONL', cfg_sqlite: 'Путь SQLite', cfg_remote_name: 'Имя remote Git', cfg_remote_url: 'URL remote Git', cfg_branch: 'Ветка Git', btn_save: 'Сохранить',
        mem_recent: 'Последняя память', mem_hint: 'Нажмите ID, чтобы открыть содержимое', mem_content: 'Содержимое памяти',
        th_id: 'ID', th_layer: 'Слой', th_kind: 'Тип', th_summary: 'Сводка', th_updated: 'Обновлено',
        cfg_saved: 'Конфигурация сохранена', cfg_failed: 'Ошибка сохранения',
        init_ok: 'Состояние конфига: инициализировано', init_hint_ok: 'Daemon выполняет квази-реальную синхронизацию.',
        init_missing: 'Состояние конфига: не инициализировано', init_hint_missing: 'Daemon отключён до инициализации.',
        daemon_state: (d) => `Daemon: ${d.running ? 'running' : 'stopped'}, enabled=${d.enabled}, initialized=${d.initialized}`
      },
      it: {
        title: 'OmniMem WebUI', subtitle: 'Modalità semplice: stato e azioni / configurazione / memoria', language: 'Lingua',
        tab_status: 'Stato e azioni', tab_config: 'Configurazione', tab_memory: 'Memoria',
        system_status: 'Stato sistema', actions: 'Azioni',
        btn_status: 'Controlla sync', btn_bootstrap: 'Bootstrap sync dispositivo', btn_push: 'Push', btn_pull: 'Pull',
        btn_daemon_on: 'Abilita daemon', btn_daemon_off: 'Disabilita daemon',
        config_title: 'Configurazione', cfg_path: 'Percorso config', cfg_home: 'Home', cfg_markdown: 'Percorso Markdown', cfg_jsonl: 'Percorso JSONL', cfg_sqlite: 'Percorso SQLite', cfg_remote_name: 'Nome remote Git', cfg_remote_url: 'URL remote Git', cfg_branch: 'Branch Git', btn_save: 'Salva configurazione',
        mem_recent: 'Memorie recenti', mem_hint: 'Clicca un ID per aprire il contenuto', mem_content: 'Contenuto memoria',
        th_id: 'ID', th_layer: 'Livello', th_kind: 'Tipo', th_summary: 'Sommario', th_updated: 'Aggiornato',
        cfg_saved: 'Configurazione salvata', cfg_failed: 'Salvataggio fallito',
        init_ok: 'Stato config: inizializzata', init_hint_ok: 'Daemon sincronizza quasi in tempo reale.',
        init_missing: 'Stato config: non inizializzata', init_hint_missing: "Daemon disabilitato fino all'inizializzazione.",
        daemon_state: (d) => `Daemon: ${d.running ? 'running' : 'stopped'}, enabled=${d.enabled}, initialized=${d.initialized}`
      },
      ko: {
        title: 'OmniMem WebUI', subtitle: '간단 모드: 상태/작업 · 설정 · 메모리', language: '언어',
        tab_status: '상태/작업', tab_config: '설정', tab_memory: '메모리',
        system_status: '시스템 상태', actions: '작업',
        btn_status: '동기화 상태 확인', btn_bootstrap: '초기 장치 동기화', btn_push: 'Push', btn_pull: 'Pull',
        btn_daemon_on: '데몬 켜기', btn_daemon_off: '데몬 끄기',
        config_title: '설정', cfg_path: '설정 경로', cfg_home: '홈', cfg_markdown: 'Markdown 경로', cfg_jsonl: 'JSONL 경로', cfg_sqlite: 'SQLite 경로', cfg_remote_name: 'Git 원격 이름', cfg_remote_url: 'Git 원격 URL', cfg_branch: 'Git 브랜치', btn_save: '설정 저장',
        mem_recent: '최근 메모리', mem_hint: 'ID를 클릭해 본문 열기', mem_content: '메모리 본문',
        th_id: 'ID', th_layer: '레이어', th_kind: '유형', th_summary: '요약', th_updated: '업데이트 시각',
        cfg_saved: '설정이 저장되었습니다', cfg_failed: '저장 실패',
        init_ok: '설정 상태: 초기화됨', init_hint_ok: '데몬이 백그라운드에서 준실시간 동기화합니다.',
        init_missing: '설정 상태: 미초기화', init_hint_missing: '초기화 전에는 데몬이 비활성화됩니다.',
        daemon_state: (d) => `Daemon: ${d.running ? 'running' : 'stopped'}, enabled=${d.enabled}, initialized=${d.initialized}`
      }
    };

    function safeGetLang() {
      try { return localStorage.getItem('omnimem.lang') || 'en'; } catch (_) { return 'en'; }
    }
    function safeSetLang(v) {
      try { localStorage.setItem('omnimem.lang', v); } catch (_) {}
    }
    function safeGetAdvanced() {
      try { return (localStorage.getItem('omnimem.advanced') || '0') === '1'; } catch (_) { return false; }
    }
    function safeSetAdvanced(v) {
      try { localStorage.setItem('omnimem.advanced', v ? '1' : '0'); } catch (_) {}
    }
    function safeGetToken() {
      try { return localStorage.getItem('omnimem.token') || ''; } catch (_) { return ''; }
    }
	    function safeSetToken(v) {
	      try { localStorage.setItem('omnimem.token', v || ''); } catch (_) {}
	    }
	    function safeGetEvtType() {
	      try { return localStorage.getItem('omnimem.evt_type') || ''; } catch (_) { return ''; }
	    }
	    function safeSetEvtType(v) {
	      try { localStorage.setItem('omnimem.evt_type', v || ''); } catch (_) {}
	    }
	    function safeGetEvtSort() {
	      try { return localStorage.getItem('omnimem.evt_sort') || 'event_time:desc'; } catch (_) { return 'event_time:desc'; }
	    }
	    function safeSetEvtSort(v) {
	      try { localStorage.setItem('omnimem.evt_sort', v || 'event_time:desc'); } catch (_) {}
	    }
	    function safeGetEvtSearch() {
	      try { return localStorage.getItem('omnimem.evt_search') || ''; } catch (_) { return ''; }
	    }
	    function safeSetEvtSearch(v) {
	      try { localStorage.setItem('omnimem.evt_search', v || ''); } catch (_) {}
	    }
	    function safeGetScopeMode() {
	      try { return localStorage.getItem('omnimem.scope_mode') || 'auto'; } catch (_) { return 'auto'; }
	    }
	    function safeSetScopeMode(v) {
	      try { localStorage.setItem('omnimem.scope_mode', v || 'auto'); } catch (_) {}
	    }
	    function safeGetWsConfirm() {
	      try { return (localStorage.getItem('omnimem.ws_confirm') || '1') === '1'; } catch (_) { return true; }
	    }
	    function safeSetWsConfirm(v) {
	      try { localStorage.setItem('omnimem.ws_confirm', v ? '1' : '0'); } catch (_) {}
	    }
	    function safeGetWorkset() {
	      try {
	        return {
	          project_id: localStorage.getItem('omnimem.pin_project') || '',
	          session_id: localStorage.getItem('omnimem.pin_session') || ''
	        };
	      } catch (_) {
	        return { project_id:'', session_id:'' };
	      }
	    }
	    function safeSetWorkset(pid, sid) {
	      try {
	        localStorage.setItem('omnimem.pin_project', pid || '');
	        localStorage.setItem('omnimem.pin_session', sid || '');
	      } catch (_) {}
	    }

	    function safeLoadWorksets() {
	      try {
	        const raw = localStorage.getItem('omnimem.worksets') || '[]';
	        const arr = JSON.parse(raw);
	        return Array.isArray(arr) ? arr : [];
	      } catch (_) {
	        return [];
	      }
	    }
	    function safeSaveWorksets(items) {
	      try { localStorage.setItem('omnimem.worksets', JSON.stringify(items || [])); } catch (_) {}
	    }
	    function safeGetActiveWorksetName() {
	      try { return localStorage.getItem('omnimem.workset_active') || ''; } catch (_) { return ''; }
	    }
	    function safeSetActiveWorksetName(name) {
	      try { localStorage.setItem('omnimem.workset_active', name || ''); } catch (_) {}
	    }

	    function b64urlEncode(text) {
	      // UTF-8 -> base64url
	      const bytes = new TextEncoder().encode(String(text || ''));
	      let bin = '';
	      bytes.forEach(b => bin += String.fromCharCode(b));
	      return btoa(bin).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
	    }
		    function b64urlDecode(b64url) {
		      const s = String(b64url || '').replaceAll('-', '+').replaceAll('_', '/');
		      const pad = s.length % 4 ? ('='.repeat(4 - (s.length % 4))) : '';
		      const bin = atob(s + pad);
		      const bytes = new Uint8Array(bin.length);
		      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
		      return new TextDecoder().decode(bytes);
		    }
		
		    function clearWsHash() {
		      try {
		        if ((location.hash || '').startsWith('#ws=')) history.replaceState(null, '', location.pathname);
		      } catch (_) {}
		    }
		
		    function showWsModal(show) {
		      const o = document.getElementById('modalOverlay');
		      const m = document.getElementById('wsModal');
		      if (!o || !m) return;
		      if (show) {
		        o.classList.add('show');
		        m.classList.add('show');
		      } else {
		        o.classList.remove('show');
		        m.classList.remove('show');
		      }
		    }
		
			    function beginWorksetImportReview(obj, sourceLabel) {
			      pendingWsImport = obj || null;
			      pendingWsSource = sourceLabel || '';
			      const title = document.getElementById('wsModalTitle');
			      const src = document.getElementById('wsModalSource');
			      const nameEl = document.getElementById('wsImportName');
			      const prev = document.getElementById('wsImportPreview');
			      if (title) title.textContent = 'Import Workset';
			      if (src) src.textContent = pendingWsSource ? `source: ${pendingWsSource}` : '';
			      const nm = String((obj && obj.name) || '').trim() || `shared-${new Date().toISOString().slice(0,10)}`;
			      if (nameEl) nameEl.value = nm;
			      const ap = document.getElementById('wsApplyProject');
			      const as = document.getElementById('wsApplySession');
			      const af = document.getElementById('wsApplyPrefs');
			      const hasP = !!String((obj && obj.project_id) || '').trim();
			      const hasS = !!String((obj && obj.session_id) || '').trim();
			      const hasF = !!(obj && obj.prefs);
			      if (ap) { ap.checked = hasP; ap.disabled = !hasP; }
			      if (as) { as.checked = hasS; as.disabled = !hasS; }
			      if (af) { af.checked = hasF; af.disabled = !hasF; }
			      if (prev) prev.textContent = '';
			      updateWsImportPreview();
			      showWsModal(true);
			    }
		    let currentLang = safeGetLang();
		    if (!I18N[currentLang]) currentLang = 'en';
        let advancedOn = safeGetAdvanced();
		    let daemonCache = { running:false, enabled:false, initialized:false };
		    let browserPath = '';
	    let liveOn = false;
	    let liveTimer = null;
	    let liveBusy = false;
	    let boardSelectMode = false;
	    let selectedBoardIds = new Set();
	    let currentEvent = null;
	    let eventsCache = [];
	    let eventsAll = [];
		    let selectedEventIdx = -1;
		    let eventsSort = { key: 'event_time', dir: 'desc' };
		    let lastEventsCtx = { project_id:'', session_id:'', event_type:'' };
		    let pendingWsImport = null;
		    let pendingWsSource = '';

    function t(key) {
      const dict = I18N[currentLang] || I18N.en;
      return dict[key] || I18N.en[key] || key;
    }

    function renderMode() {
      document.body.classList.toggle('advanced', !!advancedOn);
      const b = document.getElementById('btnToggleAdvanced');
      if (b) b.textContent = t(advancedOn ? 'btn_simple' : 'btn_advanced');
      const s = document.getElementById('subTitle');
      if (s) s.textContent = t(advancedOn ? 'subtitle_adv' : 'subtitle_simple');
      if (!advancedOn) {
        const active = document.querySelector('.panel.active');
        if (active && active.classList.contains('advanced-only')) setActiveTab('statusTab');
      }
    }

	    function applyI18n() {
      document.documentElement.lang = currentLang;
      document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        el.textContent = t(key);
      });
      document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        el.setAttribute('placeholder', t(key));
      });
      document.querySelectorAll('[data-i18n-title]').forEach(el => {
        const key = el.getAttribute('data-i18n-title');
        el.setAttribute('title', t(key));
      });
      document.getElementById('langSelect').value = currentLang;
      renderMode();
	      renderDaemonState();
	    }

    async function loadBuildInfo() {
      const el = document.getElementById('buildInfo');
      if (!el) return;
      try {
        const d = await jget('/api/version');
        if (d && d.ok) {
          const v = String(d.version || '').trim();
          const w = String(d.webui_schema_version || '').trim();
          el.textContent = v ? (`v${v}` + (w ? ` (webui ${w})` : '')) : '';
        }
      } catch (_) {}
    }

	    function toast(title, body, ok) {
      const tEl = document.getElementById('toast');
      if (!tEl) return;
      document.getElementById('toastTitle').textContent = title || 'Notification';
      document.getElementById('toastBody').innerHTML = body || '';
      tEl.classList.add('show');
      setTimeout(() => tEl.classList.remove('show'), ok ? 1400 : 2600);
    }

    function showDrawer(show) {
      const overlay = document.getElementById('overlay');
      const drawer = document.getElementById('drawer');
      if (!overlay || !drawer) return;
      if (show) {
        overlay.classList.add('show');
        drawer.classList.add('show');
      } else {
        overlay.classList.remove('show');
        drawer.classList.remove('show');
      }
    }

    function fmtPct(v) {
      const n = (typeof v === 'number') ? v : 0;
      const p = Math.max(0, Math.min(1, n));
      return Math.round(p * 100);
    }

    function sigRow(label, v) {
      const pct = fmtPct(v);
      const vv = (typeof v === 'number') ? v.toFixed(2) : '-';
      return `<div class="sig-row"><div class="sig-label">${escHtml(label)}</div><div class="bar"><i style="width:${pct}%"></i></div><div class="sig-val mono">${escHtml(vv)}</div></div>`;
    }

    function pill(text, strong) {
      return `<span class="pill">${strong ? '<b>' + escHtml(text) + '</b>' : escHtml(text)}</span>`;
    }

	    function kvRow(k, v) {
	      return `<div><div class="k">${escHtml(k)}</div><div class="v mono">${escHtml(v || '')}</div></div>`;
	    }

	    let drawerMem = null;
	    let drawerEditMode = false;

		    function stripMdTitle(body) {
		      const s = String(body || '');
		      // Canonical bodies are stored as: "# {summary}" + blank line + content.
		      const m = s.match(/^# .*\\n\\n([\\s\\S]*)$/);
		      return m ? m[1] : s;
		    }

	    function setDrawerEditMode(on) {
	      drawerEditMode = !!on;
	      const eb = document.getElementById('dEditBox');
	      const bv = document.getElementById('dBodyView');
	      const btnE = document.getElementById('btnEdit');
	      const btnS = document.getElementById('btnSave');
	      const btnC = document.getElementById('btnCancel');
	      if (eb) eb.style.display = drawerEditMode ? 'block' : 'none';
	      if (bv) bv.style.display = drawerEditMode ? 'none' : 'block';
	      if (btnE) btnE.style.display = drawerEditMode ? 'none' : 'inline-block';
	      if (btnS) btnS.style.display = drawerEditMode ? 'inline-block' : 'none';
	      if (btnC) btnC.style.display = drawerEditMode ? 'inline-block' : 'none';
	      const btnPromote = document.getElementById('btnPromote');
	      const btnDemote = document.getElementById('btnDemote');
	      const btnArchive = document.getElementById('btnArchive');
	      [btnPromote, btnDemote, btnArchive].forEach(b => { if (b) b.disabled = drawerEditMode; });
	    }

	    async function saveDrawerEdit() {
	      const m = drawerMem;
	      if (!m || !m.id) return;
	      const summary = document.getElementById('dEditSummary')?.value?.trim() || '';
	      const tags_csv = document.getElementById('dEditTags')?.value || '';
	      const body = document.getElementById('dEditBody')?.value || '';
	      const r = await jpost('/api/memory/update', { id: m.id, summary, body, tags_csv });
	      if (!r || !r.ok) {
	        toast('Edit', r?.error || 'update failed', false);
	        return;
	      }
	      toast('Edit', 'saved', true);
	      setDrawerEditMode(false);
	      await loadInsights();
	      await loadLayerStats();
	      await loadMem();
	      await openMemory(m.id);
	    }

	    async function openMemory(id) {
	      const d = await jget('/api/memory?id=' + encodeURIComponent(id));
	      if (!d.ok || !d.memory) {
	        toast('Memory', d.error || 'not found', false);
	        return;
	      }
	      const m = d.memory;
	      drawerMem = m;
	      const sig = m.signals || {};
	      document.getElementById('dTitle').textContent = m.summary || 'Memory';
      document.getElementById('dPills').innerHTML = [
        pill((m.scope||{}).project_id || 'global', true),
        pill(m.layer || ''),
        pill(m.kind || ''),
        pill(m.id || '', false)
      ].join(' ');

      document.getElementById('dSignals').innerHTML = [
        sigRow('importance', sig.importance_score),
        sigRow('confidence', sig.confidence_score),
        sigRow('stability', sig.stability_score),
        sigRow('volatility', sig.volatility_score),
        `<div class="sig-row"><div class="sig-label">reuse</div><div class="bar"><i style="width:${Math.min(100, (sig.reuse_count||0) * 20)}%"></i></div><div class="sig-val mono">${escHtml(String(sig.reuse_count||0))}</div></div>`
      ].join('');

      const src = m.source || {};
      const scope = m.scope || {};
      const tags = (m.tags || []).join(',');
      document.getElementById('dMeta').innerHTML = [
        kvRow('created_at', m.created_at || ''),
        kvRow('updated_at', m.updated_at || ''),
        kvRow('project_id', scope.project_id || ''),
        kvRow('workspace', scope.workspace || ''),
        kvRow('tool', src.tool || ''),
        kvRow('session_id', src.session_id || ''),
        kvRow('tags', tags)
      ].join('');

      const refs = (m.refs || []);
	      document.getElementById('dRefs').innerHTML = refs.length
	        ? refs.map(r => `<div class="mono">${escHtml(r.type || '')}:${escHtml(r.target || '')}${r.note ? ' ' + escHtml(r.note) : ''}</div>`).join('')
	        : '<span class="small">(none)</span>';

	      document.getElementById('dBodyView').textContent = d.body || '';
	      const edS = document.getElementById('dEditSummary');
	      const edT = document.getElementById('dEditTags');
	      const edB = document.getElementById('dEditBody');
	      if (edS) edS.value = m.summary || '';
	      if (edT) edT.value = (m.tags || []).join(',');
	      if (edB) edB.value = stripMdTitle(d.body || '');
	      setDrawerEditMode(false);

	      // Wire action buttons based on current layer.
	      const btnPromote = document.getElementById('btnPromote');
	      const btnDemote = document.getElementById('btnDemote');
      const btnArchive = document.getElementById('btnArchive');
      const reco = document.getElementById('dReco');
      const layer = m.layer || '';
      btnPromote.style.display = (layer === 'instant' || layer === 'short') ? 'inline-block' : 'none';
      btnDemote.style.display = (layer === 'long') ? 'inline-block' : 'none';
      btnArchive.style.display = (layer !== 'archive') ? 'inline-block' : 'none';
      btnPromote.onclick = () => moveLayer(m.id, 'long');
      btnDemote.onclick = () => moveLayer(m.id, 'short');
      btnArchive.onclick = () => moveLayer(m.id, 'archive');

      // Lightweight recommendation based on current signals.
      const imp = Number(sig.importance_score || 0);
      const conf = Number(sig.confidence_score || 0);
      const stab = Number(sig.stability_score || 0);
      const vol = Number(sig.volatility_score || 0);
      const reuse = Number(sig.reuse_count || 0);
      let recoText = '';
      if ((layer === 'instant' || layer === 'short') && imp >= 0.75 && conf >= 0.70 && stab >= 0.70 && vol <= 0.55) {
        recoText = `Recommendation: promote to long (imp≥0.75, conf≥0.70, stab≥0.70, vol≤0.55).`;
      } else if (layer === 'long' && reuse <= 1 && (vol >= 0.75 || stab <= 0.45)) {
        recoText = `Recommendation: demote to short (reuse≤1 and (vol≥0.75 or stab≤0.45)).`;
      } else if (layer !== 'archive' && stab >= 0.90 && reuse >= 3 && vol <= 0.30) {
        recoText = `Recommendation: consider archiving a stable reference snapshot.`;
      }
      reco.textContent = recoText;

      showDrawer(true);
    }

    function authHeaders(base) {
      const headers = Object.assign({}, base || {});
      const token = safeGetToken();
      if (token) headers['X-OmniMem-Token'] = token;
      return headers;
    }

    async function requestWithAuth(url, init, retried) {
      const r = await fetch(url, init);
      if (r.status === 401 && !retried) {
        const token = window.prompt('WebUI token required. Enter token:') || '';
        if (token.trim()) {
          safeSetToken(token.trim());
          const next = Object.assign({}, init || {});
          next.headers = authHeaders((init || {}).headers || {});
          return requestWithAuth(url, next, true);
        }
      }
      return r;
    }

    async function jget(url) {
      const r = await requestWithAuth(url, { headers: authHeaders() }, false);
      return await r.json();
    }
    async function jpost(url, obj) {
      const r = await requestWithAuth(
        url,
        { method:'POST', headers:authHeaders({'Content-Type':'application/json'}), body:JSON.stringify(obj) },
        false
      );
      return await r.json();
    }

    function renderInitState(initialized) {
      const initEl = document.getElementById('initState');
      const hintEl = document.getElementById('syncHint');
      if (initialized) {
        initEl.innerHTML = `<span class=\"ok\">${t('init_ok')}</span>`;
        hintEl.textContent = t('init_hint_ok');
      } else {
        initEl.innerHTML = `<span class=\"warn\">${t('init_missing')}</span>`;
        hintEl.textContent = t('init_hint_missing');
      }
    }

    function renderDaemonState() {
      const dict = I18N[currentLang] || I18N.en;
      const fn = dict.daemon_state || I18N.en.daemon_state;
      const primary = fn(daemonCache);
      const extra = [
        `cycles=${daemonCache.cycles || 0}`,
        `success=${daemonCache.success_count || 0}`,
        `failure=${daemonCache.failure_count || 0}`
      ].join(', ');
      const retry = daemonCache.retry_max_attempts ? `retry=${daemonCache.retry_max_attempts}` : '';
      const tail = [extra, retry].filter(Boolean).join(' | ');
      document.getElementById('daemonState').innerHTML = `<span class="pill"><b>${escHtml(primary)}</b><span class="mono">${escHtml(tail)}</span></span>`;
      const metrics = [
        `last_success=${daemonCache.last_success_at || '-'}`,
        `last_failure=${daemonCache.last_failure_at || '-'}`,
        `error_kind=${daemonCache.last_error_kind || '-'}`,
        `last_error=${daemonCache.last_error || '-'}`
      ].join(' | ');
      document.getElementById('daemonMetrics').innerHTML = `<span class="pill"><b>metrics</b><span class="mono">${escHtml(metrics)}</span></span>`;
      document.getElementById('daemonAdvice').innerHTML = daemonCache.remediation_hint ? `<span class="pill"><b>advice</b><span class="mono">${escHtml(daemonCache.remediation_hint)}</span></span>` : '';
      const recoverBtn = document.getElementById('btnConflictRecovery');
      recoverBtn.style.display = daemonCache.last_error_kind === 'conflict' ? 'inline-block' : 'none';
    }

    async function loadCfg() {
      const d = await jget('/api/config');
      const f = document.getElementById('cfgForm');
      for (const k of ['config_path','home','markdown','jsonl','sqlite','remote_name','remote_url','branch']) {
        f.elements[k].value = d[k] || '';
      }
      renderInitState(Boolean(d.initialized));
    }

	    async function loadMem() {
	      const project_id = document.getElementById('memProjectId')?.value?.trim() || '';
	      const session_id = document.getElementById('memSessionId')?.value?.trim() || '';
	      const query = document.getElementById('memQuery')?.value?.trim() || '';
	      const layer = document.getElementById('memLayer')?.value?.trim() || '';
	      const d = await jget('/api/memories?limit=20&project_id=' + encodeURIComponent(project_id) + '&session_id=' + encodeURIComponent(session_id) + '&layer=' + encodeURIComponent(layer) + '&query=' + encodeURIComponent(query));
	      const b = document.getElementById('memBody');
	      b.innerHTML = '';
	      (d.items || []).forEach(x => {
	        const tr = document.createElement('tr');
	        tr.innerHTML = `<td><a href=\"#\" data-id=\"${escHtml(x.id)}\">${escHtml(String(x.id).slice(0,10))}...</a></td><td>${escHtml(x.project_id || '')}</td><td>${escHtml(x.layer || '')}</td><td>${escHtml(x.kind || '')}</td><td>${escHtml(x.summary || '')}</td><td>${escHtml(x.updated_at || '')}</td>`;
	        tr.querySelector('a').onclick = async (e) => {
	          e.preventDefault();
	          await openMemory(x.id);
	        };
	        tr.onclick = async (e) => {
	          if (e.target && e.target.tagName === 'A') return;
	          await openMemory(x.id);
	        };
	        b.appendChild(tr);
	      });
	    }

	    function updateBoardToolbar() {
	      const n = selectedBoardIds.size;
	      const btnSel = document.getElementById('btnBoardSelectToggle');
	      const btnP = document.getElementById('btnBoardPromote');
	      const btnD = document.getElementById('btnBoardDemote');
	      const btnA = document.getElementById('btnBoardArchive');
	      const btnC = document.getElementById('btnBoardClear');
	      const info = document.getElementById('boardSelInfo');
	      if (btnSel) btnSel.textContent = boardSelectMode ? 'Select: on' : 'Select: off';
	      if (btnP) btnP.disabled = n === 0;
	      if (btnD) btnD.disabled = n === 0;
	      if (btnA) btnA.disabled = n === 0;
	      if (btnC) btnC.disabled = n === 0;
	      if (info) info.textContent = n ? `${n} selected` : '';
	    }

	    function setBoardSelectMode(on) {
	      boardSelectMode = !!on;
	      updateBoardToolbar();
	    }

	    function clearBoardSelection() {
	      selectedBoardIds = new Set();
	      document.querySelectorAll('.mem-card.selected').forEach(el => el.classList.remove('selected'));
	      updateBoardToolbar();
	    }

	    function toggleBoardSelection(id, el) {
	      if (!id) return;
	      if (selectedBoardIds.has(id)) {
	        selectedBoardIds.delete(id);
	        if (el) el.classList.remove('selected');
	      } else {
	        selectedBoardIds.add(id);
	        if (el) el.classList.add('selected');
	      }
	      updateBoardToolbar();
	    }

	    async function batchMove(ids, toLayer) {
	      const uniq = Array.from(new Set((ids || []).filter(Boolean)));
	      if (!uniq.length) return;
	      let ok = 0;
	      let fail = 0;
	      for (let i = 0; i < uniq.length; i++) {
	        const id = uniq[i];
	        const r = await jpost('/api/memory/move', {id, layer: toLayer});
	        if (r && r.ok) ok += 1; else fail += 1;
	      }
	      clearBoardSelection();
	      await loadInsights();
	      await loadMem();
	      await loadLayerStats();
	      toast('Batch', `${ok} moved → ${toLayer}${fail ? `, ${fail} failed` : ''}`, fail === 0);
	    }

	    function readSessionArchiveOpts() {
	      const fromRaw = (document.getElementById('sessArchiveFrom')?.value || 'instant,short').trim();
	      const from_layers = fromRaw.split(',').map(x => x.trim()).filter(Boolean);
	      const to_layer = (document.getElementById('sessArchiveTo')?.value || 'archive').trim() || 'archive';
	      const nRaw = Number(document.getElementById('sessArchiveLimit')?.value || 400);
	      const limit = Number.isFinite(nRaw) ? Math.max(1, Math.min(2000, Math.floor(nRaw))) : 400;
	      return { from_layers, to_layer, limit };
	    }

	    function readLiveIntervalMs() {
	      const el = document.getElementById('liveInterval');
	      const v = el ? Number(el.value) : 5000;
	      return Number.isFinite(v) ? Math.max(800, v) : 5000;
	    }

	    function renderLive() {
	      const btn = document.getElementById('btnLiveToggle');
	      if (btn) btn.textContent = liveOn ? 'Live: on' : 'Live: off';
	      const hint = document.getElementById('liveHint');
	      if (hint) hint.textContent = liveOn ? `Live refresh every ${Math.round(readLiveIntervalMs()/1000)}s (daemon + active tab)` : 'Live refresh is off';
	    }

	    async function liveTick() {
	      if (liveBusy) return;
	      liveBusy = true;
	      try {
	        await loadDaemon();
	        const active = document.querySelector('.panel.active')?.id || '';
	        if (active === 'insightsTab') {
	          const pid = document.getElementById('insProjectId')?.value?.trim() || '';
	          const sid = document.getElementById('insSessionId')?.value?.trim() || '';
	          await loadGovernance(pid, sid);
	          await loadTimeline(pid, sid);
	          await loadBoard(pid, sid);
	          await loadSessions(pid);
	          await loadEvents(pid, sid);
	          await loadEventStats(pid, sid);
	        } else if (active === 'memoryTab') {
	          await loadMem();
	          await loadLayerStats();
	        }
	      } catch (_) {
	        // keep quiet; UI already has error handler/toast paths for primary actions
	      } finally {
	        liveBusy = false;
	      }
	    }

	    function setLive(on) {
	      liveOn = !!on;
	      try { localStorage.setItem('omnimem.live_on', liveOn ? '1' : '0'); } catch (_) {}
	      if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
	      if (liveOn) {
	        const ms = readLiveIntervalMs();
	        liveTimer = setInterval(liveTick, ms);
	        // kick once immediately so UI feels responsive
	        liveTick();
	      }
	      renderLive();
	    }

	    function loadLiveFromStorage() {
	      try {
	        const on = (localStorage.getItem('omnimem.live_on') || '') === '1';
	        const ms = Number(localStorage.getItem('omnimem.live_ms') || '');
	        if (Number.isFinite(ms) && document.getElementById('liveInterval')) {
	          document.getElementById('liveInterval').value = String(ms);
	        }
	        setLive(on);
	      } catch (_) {
	        renderLive();
	      }
	    }

    document.getElementById('cfgForm').onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target;
      const payload = {};
      for (const k of ['home','markdown','jsonl','sqlite','remote_name','remote_url','branch']) payload[k] = f.elements[k].value;
      const d = await jpost('/api/config', payload);
      document.getElementById('status').innerHTML = d.ok ? `<span class="pill"><b class="ok">${t('cfg_saved')}</b></span>` : `<span class="pill"><b class="err">${t('cfg_failed')}</b></span>`;
      toast('Config', d.ok ? t('cfg_saved') : (d.error || t('cfg_failed')), !!d.ok);
      await loadCfg();
      await loadDaemon();
      await loadLayerStats();
      await loadInsights();
    };

    async function runSync(mode) {
      const d = await jpost('/api/sync', {mode});
      document.getElementById('syncOut').textContent = JSON.stringify(d, null, 2);
      toast('Sync', `<span class="mono">${escHtml(mode)}</span> ${d.ok ? '<span class="ok">ok</span>' : '<span class="err">fail</span>'}`, !!d.ok);
      await loadMem();
      await loadDaemon();
      await loadLayerStats();
      await loadInsights();
    }

    async function runConflictRecovery() {
      const modes = ['github-status', 'github-pull', 'github-push'];
      const out = [];
      for (const mode of modes) {
        const d = await jpost('/api/sync', {mode});
        out.push({ mode, ok: !!d.ok, message: d.message || d.error || '' });
        if (!d.ok) break;
      }
      document.getElementById('syncOut').textContent = JSON.stringify({ ok: out.every(x => x.ok), steps: out }, null, 2);
      await loadMem();
      await loadDaemon();
    }

    async function loadDaemon() {
      const d = await jget('/api/daemon');
      daemonCache = d;
      renderDaemonState();
    }

		    async function loadLayerStats() {
		      const project_id = document.getElementById('memProjectId')?.value?.trim() || '';
		      const session_id = document.getElementById('memSessionId')?.value?.trim() || '';
		      const d = await jget('/api/layer-stats?project_id=' + encodeURIComponent(project_id) + '&session_id=' + encodeURIComponent(session_id));
		      if (!d.ok) {
		        document.getElementById('layerStats').textContent = d.error || 'layer stats failed';
		        return;
		      }
	      const el = document.getElementById('layerStats');
	      const items = (d.items || []);
	      if (!el) return;
	      if (!items.length) { el.textContent = '(empty)'; return; }
	      el.innerHTML = items.map(x => {
	        const layer = String(x.layer || '');
	        const count = Number(x.count || 0);
	        const title = layerDesc(layer);
	        return `<a href=\"#\" class=\"pill\" data-layer=\"${escHtml(layer)}\" title=\"${escHtml(title)}\"><b>${escHtml(layer)}</b><span class=\"mono\">${escHtml(String(count))}</span></a>`;
	      }).join(' ');
	      el.querySelectorAll('a[data-layer]').forEach(a => {
	        a.onclick = async (e) => {
	          e.preventDefault();
	          const layer = a.dataset.layer || '';
	          const sel = document.getElementById('memLayer');
	          if (sel) sel.value = layer;
	          await loadMem();
	        };
	      });
	    }

    function layerDesc(layer) {
      if (layer === 'instant') return 'noisy, short-lived trial context';
      if (layer === 'short') return 'validated task context and near-term reuse';
      if (layer === 'long') return 'high-value, repeated, stable knowledge';
      if (layer === 'archive') return 'cold historical snapshots and references';
      return '';
    }

	    async function loadInsights() {
	      const project_id = document.getElementById('insProjectId')?.value?.trim() || '';
	      const session_id = document.getElementById('insSessionId')?.value?.trim() || '';
	      const d = await jget('/api/analytics?project_id=' + encodeURIComponent(project_id) + '&session_id=' + encodeURIComponent(session_id));
	      if (!d.ok) {
	        document.getElementById('insLayers').innerHTML = `<div class="small err">${escHtml(d.error || 'analytics failed')}</div>`;
	        return;
	      }

      const total = (d.layers || []).reduce((a, x) => a + (x.count || 0), 0) || 0;
      const layersEl = document.getElementById('insLayers');
      layersEl.innerHTML = '';
      (d.layers || []).forEach(x => {
        const pct = total ? Math.round((x.count / total) * 100) : 0;
        const div = document.createElement('div');
        div.className = 'card layer-card';
        div.innerHTML = `
          <div class="pill"><b>${escHtml(x.layer)}</b><span>${x.count}</span></div>
          <div class="small" style="margin-top:6px">${escHtml(layerDesc(x.layer))}</div>
          <div class="kpi">
            <div class="bar" style="flex:1"><i style="width:${pct}%"></i></div>
            <div class="mono">${pct}%</div>
          </div>
        `;
        div.onclick = () => {
          // Jump to Memory tab and apply layer filter
          document.getElementById('memLayer').value = x.layer;
          document.getElementById('memProjectId').value = project_id;
          document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
          document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
          document.querySelector('[data-tab="memoryTab"]').classList.add('active');
          document.getElementById('memoryTab').classList.add('active');
          loadMem();
          loadLayerStats();
        };
        layersEl.appendChild(div);
      });

      document.getElementById('insKinds').innerHTML = (d.kinds || []).map(x => `<span class="pill"><b>${escHtml(x.kind)}</b><span>${x.count}</span></span>`).join(' ') || '<span class="small">(empty)</span>';

      const act = (d.activity || []).slice().reverse();
      document.getElementById('insActivity').innerHTML = act.map(x => {
        const w = d.activity_max ? Math.round((x.count / d.activity_max) * 100) : 0;
        return `<div class="small"><span class="mono">${escHtml(x.day)}</span> <span class="pill"><b>${x.count}</b></span><div class="bar" style="margin-top:4px"><i style="width:${w}%"></i></div></div>`;
      }).join('') || '<span class="small">(empty)</span>';

      document.getElementById('insTags').innerHTML = (d.tags || []).map(x => `<span class="pill"><b>${escHtml(x.tag)}</b><span>${x.count}</span></span>`).join(' ') || '<span class="small">(empty)</span>';

	      document.getElementById('insCheckpoints').innerHTML = (d.checkpoints || []).map(x => `<div class="small"><span class="mono">${escHtml(x.updated_at || '')}</span> <b>${escHtml(x.summary || '')}</b></div>`).join('') || '<span class="small">(none)</span>';

	      await loadGovernance(project_id, session_id);
	      await loadTimeline(project_id, session_id);
	      await loadBoard(project_id, session_id);
	      await loadSessions(project_id);
	      await loadEvents(project_id, session_id);
	      await loadEventStats(project_id, session_id);
	    }
	
	    function boardColHtml(layer, count) {
	      return `<div class="col" data-layer="${escHtml(layer)}">
	        <div class="col-head">
	          <div class="col-title"><b>${escHtml(layer)}</b></div>
	          <div class="pill"><b>${count}</b><span>items</span></div>
	        </div>
	        <div class="col-body" id="col_${escHtml(layer)}"></div>
	      </div>`;
	    }
	
	    function renderBoardCard(x) {
	      const sig = x.signals || {};
	      const imp = Number(sig.importance_score || 0);
	      const stab = Number(sig.stability_score || 0);
	      const vol = Number(sig.volatility_score || 0);
	      const chips = [
	        `<span class="pill"><b>${escHtml(x.kind || '')}</b><span class="mono">${escHtml(String(x.id || '').slice(0,8))}</span></span>`,
	        `<span class="pill"><b>imp</b><span class="mono">${imp.toFixed(2)}</span></span>`,
	        `<span class="pill"><b>stab</b><span class="mono">${stab.toFixed(2)}</span></span>`,
	        `<span class="pill"><b>vol</b><span class="mono">${vol.toFixed(2)}</span></span>`,
	      ].join(' ');
	      const sel = selectedBoardIds.has(String(x.id || '')) ? ' selected' : '';
	      return `<div class="mem-card${sel}" draggable="true" data-id="${escHtml(x.id)}" data-layer="${escHtml(x.layer)}">
	        <div class="mem-card-title">${escHtml(x.summary || '')}</div>
	        <div class="mem-card-sub">${chips}</div>
	      </div>`;
	    }
	
	    async function loadBoard(project_id, session_id) {
	      const layers = ['instant','short','long','archive'];
	      const reqs = layers.map(layer => jget('/api/memories?limit=10&project_id=' + encodeURIComponent(project_id || '') + '&session_id=' + encodeURIComponent(session_id || '') + '&layer=' + encodeURIComponent(layer) + '&query='));
	      const res = await Promise.all(reqs);
	      const board = document.getElementById('layerBoard');
	      const itemsByLayer = {};
	      layers.forEach((layer, i) => {
	        itemsByLayer[layer] = (res[i] && res[i].ok) ? (res[i].items || []) : [];
	      });
	      board.innerHTML = layers.map(layer => boardColHtml(layer, itemsByLayer[layer].length)).join('');
	      layers.forEach(layer => {
	        const col = document.getElementById('col_' + layer);
	        if (!col) return;
	        col.innerHTML = itemsByLayer[layer].map(renderBoardCard).join('') || '<span class="small">(empty)</span>';
	      });
	
      board.querySelectorAll('.mem-card').forEach(card => {
        card.addEventListener('dragstart', (e) => {
          const id = card.dataset.id || '';
          const from = card.dataset.layer || '';
          // If the dragged card is part of the current selection, drag the whole selection.
          const dragIds = (selectedBoardIds.size > 0 && selectedBoardIds.has(id)) ? Array.from(selectedBoardIds) : [id];
          e.dataTransfer.setData('text/plain', JSON.stringify({ids: dragIds, id, from}));
          e.dataTransfer.effectAllowed = 'move';
        });
        card.onclick = async (e) => {
          const id = card.dataset.id;
          if (boardSelectMode) {
            e.preventDefault();
	            toggleBoardSelection(id, card);
	            return;
	          }
	          await openMemory(id);
	        };
	      });
	      updateBoardToolbar();
	
	      board.querySelectorAll('.col').forEach(col => {
	        col.addEventListener('dragover', (e) => {
	          e.preventDefault();
	          col.classList.add('drop-hot');
	          e.dataTransfer.dropEffect = 'move';
	        });
	        col.addEventListener('dragleave', () => col.classList.remove('drop-hot'));
        col.addEventListener('drop', async (e) => {
          e.preventDefault();
          col.classList.remove('drop-hot');
          let payload = null;
          try { payload = JSON.parse(e.dataTransfer.getData('text/plain') || '{}'); } catch (_) {}
          const ids = (payload && Array.isArray(payload.ids)) ? payload.ids : [];
          const id = payload && payload.id;
          const toLayer = col.dataset.layer;
          if (!id || !toLayer) return;
          if (ids.length > 1) {
            await batchMove(ids, toLayer);
            toast('Layer', `moved ${ids.length} items → ${toLayer}`, true);
          } else {
            await moveLayer(id, toLayer);
            toast('Layer', `moved ${id.slice(0,8)}… → ${toLayer}`, true);
          }
        });
      });
    }

    async function moveLayer(id, layer) {
      const d = await jpost('/api/memory/move', {id, layer});
      document.getElementById('status').innerHTML = d.ok ? `<span class=\"ok\">ok</span>` : `<span class=\"err\">${escHtml(d.error || 'failed')}</span>`;
      await loadInsights();
      await loadLayerStats();
      await loadMem();
    }

    function readThr(id, fallback) {
      const el = document.getElementById(id);
      if (!el) return fallback;
      const v = (el.type === 'range') ? el.value : el.value;
      const n = Number(v);
      return Number.isFinite(n) ? n : fallback;
    }
    function setText(id, v) {
      const el = document.getElementById(id);
      if (el) el.textContent = String(v);
    }
    function syncThrLabels() {
      setText('thrPImpV', readThr('thrPImp', 0.75).toFixed(2));
      setText('thrPConfV', readThr('thrPConf', 0.65).toFixed(2));
      setText('thrPStabV', readThr('thrPStab', 0.65).toFixed(2));
      setText('thrPVolV', readThr('thrPVol', 0.65).toFixed(2));
      setText('thrDVolV', readThr('thrDVol', 0.75).toFixed(2));
      setText('thrDStabV', readThr('thrDStab', 0.45).toFixed(2));
      setText('thrDReuseV', String(readThr('thrDReuse', 1)));
    }

    function loadThrFromStorage() {
      const keys = ['thrPImp','thrPConf','thrPStab','thrPVol','thrDVol','thrDStab','thrDReuse'];
      keys.forEach(k => {
        try {
          const v = localStorage.getItem('omnimem.' + k);
          if (v !== null && document.getElementById(k)) document.getElementById(k).value = v;
        } catch (_) {}
      });
      syncThrLabels();
    }
    function saveThrToStorage() {
      const keys = ['thrPImp','thrPConf','thrPStab','thrPVol','thrDVol','thrDStab','thrDReuse'];
      keys.forEach(k => {
        try {
          const el = document.getElementById(k);
          if (el) localStorage.setItem('omnimem.' + k, String(el.value));
        } catch (_) {}
      });
    }

    function renderCandidateRow(x, targetLayer) {
      const sig = x.signals || {};
      const s = `imp=${(sig.importance_score||0).toFixed(2)} conf=${(sig.confidence_score||0).toFixed(2)} stab=${(sig.stability_score||0).toFixed(2)} vol=${(sig.volatility_score||0).toFixed(2)} reuse=${sig.reuse_count||0}`;
      return `<div style="display:flex; gap:10px; align-items:flex-start; justify-content:space-between; margin:6px 0; padding:8px; border:1px solid var(--line); border-radius:12px; background:#fff;">
        <div>
          <div><span class="pill"><b>${escHtml(x.layer)}</b><span>${escHtml(x.kind)}</span></span> <b>${escHtml(x.summary || '')}</b></div>
          <div class="small mono" style="margin-top:4px">${escHtml(s)}</div>
        </div>
        <div><button data-id="${escHtml(x.id)}" data-layer="${escHtml(targetLayer)}">→ ${escHtml(targetLayer)}</button></div>
      </div>`;
    }

    async function loadGovernance(project_id, session_id) {
      syncThrLabels();
      const p_imp = readThr('thrPImp', 0.75);
      const p_conf = readThr('thrPConf', 0.65);
      const p_stab = readThr('thrPStab', 0.65);
      const p_vol = readThr('thrPVol', 0.65);
      const d_vol = readThr('thrDVol', 0.75);
      const d_stab = readThr('thrDStab', 0.45);
      const d_reuse = readThr('thrDReuse', 1);
      const d = await jget('/api/governance?project_id=' + encodeURIComponent(project_id || '') + '&session_id=' + encodeURIComponent(session_id || '') + '&limit=6'
        + '&p_imp=' + encodeURIComponent(p_imp)
        + '&p_conf=' + encodeURIComponent(p_conf)
        + '&p_stab=' + encodeURIComponent(p_stab)
        + '&p_vol=' + encodeURIComponent(p_vol)
        + '&d_vol=' + encodeURIComponent(d_vol)
        + '&d_stab=' + encodeURIComponent(d_stab)
        + '&d_reuse=' + encodeURIComponent(d_reuse)
      );
      const el = document.getElementById('insGovern');
      if (!d.ok) {
        el.innerHTML = `<span class="err">${escHtml(d.error || 'governance failed')}</span>`;
        return;
      }
      function whyPromote(x) {
        const s = x.signals || {};
        return `why: imp ${Number(s.importance_score||0).toFixed(2)}≥${p_imp.toFixed(2)}, conf ${Number(s.confidence_score||0).toFixed(2)}≥${p_conf.toFixed(2)}, stab ${Number(s.stability_score||0).toFixed(2)}≥${p_stab.toFixed(2)}, vol ${Number(s.volatility_score||0).toFixed(2)}≤${p_vol.toFixed(2)}`;
      }
      function whyDemote(x) {
        const s = x.signals || {};
        return `why: (vol ${Number(s.volatility_score||0).toFixed(2)}≥${d_vol.toFixed(2)} OR stab ${Number(s.stability_score||0).toFixed(2)}≤${d_stab.toFixed(2)}) AND reuse ${Number(s.reuse_count||0)}≤${d_reuse}`;
      }
      const promote = (d.promote || []).map(x => {
        const row = renderCandidateRow(x, 'long');
        return row.replace('</div></div></div>', `<div class="small mono" style="margin-top:4px">${escHtml(whyPromote(x))}</div></div></div>`);
      }).join('') || '<span class="small">(no promote candidates)</span>';
      const demote = (d.demote || []).map(x => {
        const row = renderCandidateRow(x, 'short');
        return row.replace('</div></div></div>', `<div class="small mono" style="margin-top:4px">${escHtml(whyDemote(x))}</div></div></div>`);
      }).join('') || '<span class="small">(no demote candidates)</span>';
      el.innerHTML = `<div class="small"><b>Promote</b></div>${promote}<div class="small" style="margin-top:10px"><b>Demote</b></div>${demote}`;
      el.querySelectorAll('button[data-id]').forEach(btn => {
        btn.onclick = () => moveLayer(btn.dataset.id, btn.dataset.layer);
      });
	    }

	    async function loadSessions(project_id) {
	      const d = await jget('/api/sessions?project_id=' + encodeURIComponent(project_id || '') + '&limit=20');
	      const body = document.getElementById('sessionsBody');
	      if (!body) return;
	      if (!d.ok) {
	        body.innerHTML = `<tr><td colspan="8" class="err">${escHtml(d.error || 'sessions failed')}</td></tr>`;
	        return;
	      }
	      const active = (document.getElementById('insSessionId')?.value || '').trim();
	      body.innerHTML = (d.items || []).map(x => {
	        const sid = x.session_id || '';
	        const badge = active && sid === active ? ' <span class="pill"><b>active</b></span>' : '';
	        const drift = (typeof x.avg_drift === 'number') ? x.avg_drift.toFixed(2) : '-';
	        return `<tr>
	          <td class="mono">${escHtml(String(sid).slice(0,18))}${badge}</td>
	          <td class="mono">${escHtml(x.last_updated_at || '')}</td>
	          <td>${escHtml(String(x.turns || 0))}</td>
	          <td>${escHtml(String(x.retrieves || 0))}</td>
	          <td>${escHtml(String(x.checkpoints || 0))}</td>
	          <td class="mono">${escHtml(drift)}</td>
	          <td>${escHtml(String(x.switches || 0))}</td>
	          <td>
	            <button class="secondary" style="margin-top:0" data-action="activate" data-session="${escHtml(sid)}">Activate</button>
	            <button class="danger" style="margin-top:0" data-action="archive" data-session="${escHtml(sid)}">Archive</button>
	          </td>
	        </tr>`;
	      }).join('') || `<tr><td colspan="8" class="small">(empty)</td></tr>`;
	      body.querySelectorAll('button[data-session]').forEach(btn => {
	        btn.onclick = async () => {
	          const sid = btn.dataset.session || '';
	          const action = btn.dataset.action || 'activate';
	          if (action === 'archive') {
	            const pid = document.getElementById('insProjectId')?.value?.trim() || '';
	            const opts = readSessionArchiveOpts();
	            if (!confirm(`Archive session ${sid.slice(0,12)}... from ${opts.from_layers.join('+')} -> ${opts.to_layer}?`)) return;
	            const r = await jpost('/api/session/archive', {
	              project_id: pid,
	              session_id: sid,
	              from_layers: opts.from_layers,
	              to_layer: opts.to_layer,
	              limit: opts.limit
	            });
	            if (!r.ok) {
	              toast('Session', r.error || 'archive failed', false);
	              return;
	            }
	            toast('Session', `archived ${r.moved || 0} items`, true);
	            await loadInsights();
	            await loadMem();
	            await loadLayerStats();
	            return;
	          }
	          setActiveSession(sid);
	          await loadInsights();
	          await loadMem();
	          await loadLayerStats();
	          toast('Session', `active=${sid.slice(0,12)}...`, true);
	        };
	      });
	    }

	    async function loadEvents(project_id, session_id) {
	      const et = (document.getElementById('evtType')?.value || '').trim();
	      safeSetEvtType(et);
	      lastEventsCtx = { project_id: project_id || '', session_id: session_id || '', event_type: et };
	      const d = await jget(
	        '/api/events?project_id=' + encodeURIComponent(project_id || '')
	        + '&session_id=' + encodeURIComponent(session_id || '')
	        + '&event_type=' + encodeURIComponent(et)
	        + '&limit=60'
	      );
	      const body = document.getElementById('eventsBody');
	      if (!body) return;
	      if (!d.ok) {
	        body.innerHTML = `<tr><td colspan="6" class="err">${escHtml(d.error || 'events failed')}</td></tr>`;
	        return;
	      }
	      eventsAll = d.items || [];
	      applyEventSearch();
	    }

	    function sortEvents(items) {
	      const key = (eventsSort && eventsSort.key) ? eventsSort.key : 'event_time';
	      const dir = (eventsSort && eventsSort.dir) ? eventsSort.dir : 'desc';
	      return items.slice().sort((a, b) => {
	        const av = String((a && a[key]) || '');
	        const bv = String((b && b[key]) || '');
	        if (av === bv) return 0;
	        const cmp = av < bv ? -1 : 1;
	        return dir === 'asc' ? cmp : -cmp;
	      });
	    }

	    function applyEventSearch() {
	      const q = (document.getElementById('evtSearch')?.value || '').trim().toLowerCase();
	      safeSetEvtSearch(q);
	      const base = sortEvents(eventsAll || []);
	      if (!q) {
	        eventsCache = base;
	      } else {
	        eventsCache = base.filter(x => {
	          const s = [
	            x.event_time || '',
	            x.event_type || '',
	            x.memory_id || '',
	            x.project_id || '',
	            x.session_id || '',
	            x.summary || ''
	          ].join(' ').toLowerCase();
	          return s.includes(q);
	        });
	      }
	      renderEventsTable();
	    }

	    function readDecayOpts() {
	      const pid = (document.getElementById('insProjectId')?.value || '').trim();
	      const days = parseInt(document.getElementById('decayDays')?.value || '14', 10) || 14;
	      const limit = parseInt(document.getElementById('decayLimit')?.value || '200', 10) || 200;
	      const rawLayers = (document.getElementById('decayLayers')?.value || 'instant,short,long').trim();
	      const layers = rawLayers.split(',').map(s => s.trim()).filter(Boolean);
	      return { project_id: pid, days, limit, layers };
	    }

	    function renderDecayOut(d) {
	      const out = document.getElementById('decayOut');
	      const hint = document.getElementById('decayHint');
	      if (hint) hint.textContent = d && d.ok ? (d.dry_run ? 'preview' : 'applied') : '';
	      if (!out) return;
	      if (!d || !d.ok) {
	        out.innerHTML = `<span class="err">${escHtml((d && d.error) || 'decay failed')}</span>`;
	        return;
	      }
	      const items = d.items || [];
	      const count = Number(d.count || items.length || 0);
	      const head = `<div class="small"><b>Decay</b> <span class="pill"><b>${count}</b><span>candidates</span></span> <span class="pill"><b>${escHtml(String(d.days||''))}</b><span>days</span></span> <span class="pill"><b>${escHtml(String((d.layers||[]).join(',')))}</b><span>layers</span></span></div>`;
	      const rows = items.slice(0, 60).map(x => {
	        const o = x.old || {};
	        const n = x.new || {};
	        const mid = x.id || '';
	        const age = String(x.age_days ?? '');
	        const reuse = String(x.reuse_count ?? '');
	        return `<tr>
	          <td class="mono">${escHtml(String(mid).slice(0,10))}...</td>
	          <td>${escHtml(x.layer || '')}</td>
	          <td class="mono">${escHtml(age)}</td>
	          <td class="mono">${escHtml(reuse)}</td>
	          <td class="mono">${escHtml(Number(o.confidence||0).toFixed(2))} → ${escHtml(Number(n.confidence||0).toFixed(2))}</td>
	          <td class="mono">${escHtml(Number(o.stability||0).toFixed(2))} → ${escHtml(Number(n.stability||0).toFixed(2))}</td>
	          <td class="mono">${escHtml(Number(o.volatility||0).toFixed(2))} → ${escHtml(Number(n.volatility||0).toFixed(2))}</td>
	          <td><a href="#" data-mid="${escHtml(mid)}">open</a></td>
	        </tr>`;
	      }).join('');
	      const table = `
	        <table style="margin-top:8px; table-layout:fixed">
	          <colgroup>
	            <col style="width:140px" />
	            <col style="width:90px" />
	            <col style="width:90px" />
	            <col style="width:90px" />
	            <col style="width:180px" />
	            <col style="width:180px" />
	            <col style="width:180px" />
	            <col style="width:80px" />
	          </colgroup>
	          <thead>
	            <tr>
	              <th>Memory</th>
	              <th>Layer</th>
	              <th>Age(d)</th>
	              <th>Reuse</th>
	              <th>Conf</th>
	              <th>Stab</th>
	              <th>Vol</th>
	              <th></th>
	            </tr>
	          </thead>
	          <tbody>${rows || `<tr><td colspan="8" class="small">(empty)</td></tr>`}</tbody>
	        </table>
	      `;
	      out.innerHTML = head + table + (count > 60 ? `<div class="small" style="margin-top:8px">(showing first 60)</div>` : '');
	      out.querySelectorAll('a[data-mid]').forEach(a => {
	        a.onclick = async (e) => {
	          e.preventDefault();
	          const mid = a.dataset.mid || '';
	          if (mid) await openMemory(mid);
	        };
	      });
	    }

	    async function runDecay(dry_run) {
	      const opts = readDecayOpts();
	      if (!dry_run) {
	        const ok = confirm(`Apply decay? days=${opts.days}, layers=${opts.layers.join(',')}, limit=${opts.limit}`);
	        if (!ok) return;
	      }
	      const d = await jpost('/api/maintenance/decay', Object.assign({}, opts, { dry_run: !!dry_run }));
	      renderDecayOut(d);
	      if (!d.ok) {
	        toast('Maintenance', d.error || 'decay failed', false);
	        return;
	      }
	      toast('Maintenance', (dry_run ? 'previewed ' : 'applied ') + String(d.count || 0), true);
	      // Applied decay changes signals; refresh boards and analytics.
	      if (!dry_run) {
	        await loadMem();
	        await loadLayerStats();
	        await loadEventStats(opts.project_id || '', (document.getElementById('insSessionId')?.value || '').trim());
	      }
	    }

	    async function renderEventsTable() {
	      selectedEventIdx = -1;
	      updateEventActions();
	      const view = document.getElementById('eventView');
	      if (view) view.textContent = '';

	      const body = document.getElementById('eventsBody');
	      if (!body) return;
	      body.innerHTML = (eventsCache || []).map(x => {
	        const mid = x.memory_id || '';
	        const sm = x.summary || '';
	        return `<tr>
	          <td class="mono">${escHtml(x.event_time || '')}</td>
	          <td class="mono">${escHtml(x.event_type || '')}</td>
	          <td class="mono"><a href="#" data-mid="${escHtml(mid)}">${escHtml(mid.slice(0,10))}...</a></td>
	          <td>${escHtml(x.project_id || '')}</td>
	          <td class="mono">${escHtml((x.session_id || '').slice(0,12))}</td>
	          <td>${escHtml(sm)}</td>
	        </tr>`;
	      }).join('') || `<tr><td colspan="6" class="small">(empty)</td></tr>`;

	      body.querySelectorAll('a[data-mid]').forEach(a => {
	        a.onclick = async (e) => {
	          e.preventDefault();
	          const mid = a.dataset.mid || '';
	          if (mid) await openMemory(mid);
	        };
	      });

	      async function selectEvent(i) {
	        const rows = body.querySelectorAll('tr');
	        if (!rows || !rows.length) return;
	        const idx = Math.max(0, Math.min(rows.length - 1, i));
	        selectedEventIdx = idx;
	        rows.forEach(r => r.classList.remove('row-selected'));
	        rows[idx].classList.add('row-selected');
	        rows[idx].scrollIntoView({block:'nearest'});

	        const it = (eventsCache || [])[idx];
	        if (!it || !it.event_id) return;
	        const ev = await jget('/api/event?event_id=' + encodeURIComponent(it.event_id));
	        const v = document.getElementById('eventView');
	        if (!ev.ok) {
	          currentEvent = null;
	          if (v) v.textContent = ev.error || 'event fetch failed';
	          updateEventActions();
	          return;
	        }
	        currentEvent = ev.item || null;
	        if (v) v.textContent = JSON.stringify(currentEvent || {}, null, 2);
	        updateEventActions();
	      }

	      body.querySelectorAll('tr').forEach((tr, idx) => {
	        tr.onclick = async (e) => {
	          if (e.target && e.target.tagName === 'A') return;
	          await selectEvent(idx);
	        };
	      });
	      if (eventsCache && eventsCache.length) await selectEvent(0);
	    }

	    async function loadEventStats(project_id, session_id) {
	      const d = await jget(
	        '/api/event-stats?project_id=' + encodeURIComponent(project_id || '')
	        + '&session_id=' + encodeURIComponent(session_id || '')
	        + '&days=14'
	        + '&limit=8000'
	      );
	      const el = document.getElementById('evtStats');
	      if (!el) return;
	      if (!d.ok) {
	        el.innerHTML = `<span class="err">${escHtml(d.error || 'event stats failed')}</span>`;
	        return;
	      }
	      const types = d.types || [];
	      const days = d.days || [];
	      const total = Number(d.total || 0);
	      const maxDay = Math.max(...days.map(x => Number(x.count || 0)), 0) || 0;
	      const maxType = Math.max(...types.map(x => Number(x.count || 0)), 0) || 0;

	      const typePills = types.slice(0, 10).map(x => {
	        const et = x.event_type || '';
	        const c = Number(x.count || 0);
	        const w = maxType ? Math.round((c / maxType) * 100) : 0;
	        return `<div style="flex:1; min-width:180px; border:1px solid var(--line); border-radius:14px; padding:10px; background:#fff; cursor:pointer" data-et="${escHtml(et)}">
	          <div class="small"><b class="mono">${escHtml(et)}</b> <span class="pill"><b>${c}</b></span></div>
	          <div class="bar" style="margin-top:6px"><i style="width:${w}%"></i></div>
	        </div>`;
	      }).join('');

	      const dayBars = days.slice().reverse().map(x => {
	        const c = Number(x.count || 0);
	        const w = maxDay ? Math.round((c / maxDay) * 100) : 0;
	        return `<div class="small"><span class="mono">${escHtml(x.day || '')}</span> <span class="pill"><b>${c}</b></span><div class="bar" style="margin-top:4px"><i style="width:${w}%"></i></div></div>`;
	      }).join('') || '<span class="small">(empty)</span>';

	      el.innerHTML = `
	        <div class="small"><b>Last 14 days</b> <span class="pill"><b>${total}</b><span>events</span></span></div>
	        <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:10px">${typePills || '<span class="small">(no event types)</span>'}</div>
	        <div class="divider"></div>
	        <div class="small"><b>Daily Volume</b></div>
	        <div style="margin-top:8px">${dayBars}</div>
	      `;

	      el.querySelectorAll('[data-et]').forEach(div => {
	        div.onclick = async () => {
	          const et = div.dataset.et || '';
	          const sel = document.getElementById('evtType');
	          if (sel) sel.value = et;
	          await loadEvents(project_id, session_id);
	        };
	      });
	    }

	    function deriveEventContext(ev) {
	      const payload = (ev && ev.payload) || {};
	      const env = payload && payload.envelope;
	      const scope = (env && env.scope) || {};
	      const source = (env && env.source) || {};
	      const project_id = String(scope.project_id || payload.project_id || '').trim();
	      const session_id = String(source.session_id || payload.session_id || '').trim();
	      return { project_id, session_id };
	    }

	    function canRevertPromote(ev) {
	      if (!ev || ev.event_type !== 'memory.promote') return false;
	      const p = ev.payload || {};
	      const from_layer = String(p.from_layer || '').trim();
	      const to_layer = String(p.to_layer || '').trim();
	      const mid = String(ev.memory_id || '').trim();
	      if (!mid || !from_layer || !to_layer) return false;
	      return from_layer !== to_layer;
	    }

	    function updateEventActions() {
	      const openBtn = document.getElementById('btnEventOpenMem');
	      const actBtn = document.getElementById('btnEventActivate');
	      const showBtn = document.getElementById('btnEventShowSession');
	      const revBtn = document.getElementById('btnEventRevert');
	      const copyBtn = document.getElementById('btnEventCopy');
	      const hint = document.getElementById('eventHint');
	      const ev = currentEvent;
	      const mid = ev ? String(ev.memory_id || '') : '';
	      const ctx = ev ? deriveEventContext(ev) : { project_id:'', session_id:'' };
	      if (openBtn) openBtn.disabled = !mid;
	      if (actBtn) actBtn.disabled = !ctx.session_id;
	      if (showBtn) showBtn.disabled = !ctx.session_id;
	      if (revBtn) revBtn.disabled = !canRevertPromote(ev);
	      if (copyBtn) copyBtn.disabled = !ev;
	      if (hint) {
	        const parts = [];
	        if (ev && ev.event_type) parts.push(ev.event_type);
	        if (ctx.project_id) parts.push(`project=${ctx.project_id}`);
	        if (ctx.session_id) parts.push(`session=${ctx.session_id.slice(0,12)}...`);
	        hint.textContent = parts.join(' | ');
	      }
	    }

	    function renderWorksetHint() {
	      const w = safeGetWorkset();
	      const el = document.getElementById('pinHint');
	      if (!el) return;
	      if (!w.project_id && !w.session_id) {
	        el.textContent = 'workset: (none)';
	        return;
	      }
	      const parts = [];
	      if (w.project_id) parts.push(`project=${w.project_id}`);
	      if (w.session_id) parts.push(`session=${w.session_id.slice(0,12)}...`);
	      el.textContent = 'workset: ' + parts.join(' ');
	    }

	    function refreshWorksetSelect() {
	      const sel = document.getElementById('worksetSelect');
	      if (!sel) return;
	      const items = safeLoadWorksets();
	      const active = safeGetActiveWorksetName();
	      const opts = [`<option value="">Workset: (none)</option>`].concat(
	        items
	          .slice()
	          .sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')))
	          .map(w => `<option value="${escHtml(w.name || '')}">${escHtml(w.name || '')}</option>`)
	      );
	      sel.innerHTML = opts.join('');
	      if (active) sel.value = active;
	    }

	    async function applyWorksetByName(name) {
	      const items = safeLoadWorksets();
	      const w = items.find(x => (x && x.name) === name);
	      if (!w) return;
	      applyConsolePrefs(w.prefs || {});
	      if (w.project_id) {
	        document.getElementById('insProjectId').value = w.project_id;
	        document.getElementById('memProjectId').value = w.project_id;
	      }
	      if (w.session_id) setActiveSession(w.session_id);
	      safeSetActiveWorksetName(name);
	      refreshWorksetSelect();
	      renderWorksetHint();
	      // Apply search immediately in case user is already on events tab view.
	      applyEventSearch();
	      await loadInsights();
	      await loadMem();
	      await loadLayerStats();
	    }

	    function upsertWorkset(name, project_id, session_id) {
	      const nm = String(name || '').trim();
	      if (!nm) return { ok:false, error:'missing name' };
	      const pid = String(project_id || '').trim();
	      const sid = String(session_id || '').trim();
	      const prefs = snapshotConsolePrefs();
	      const items = safeLoadWorksets();
	      const now = new Date().toISOString();
	      const idx = items.findIndex(x => (x && x.name) === nm);
	      const obj = { name: nm, project_id: pid, session_id: sid, prefs, updated_at: now };
	      if (idx >= 0) items[idx] = obj; else items.push(obj);
	      safeSaveWorksets(items);
	      safeSetActiveWorksetName(nm);
	      return { ok:true };
	    }

	    function deleteWorkset(name) {
	      const nm = String(name || '').trim();
	      if (!nm) return { ok:false, error:'missing name' };
	      const items = safeLoadWorksets().filter(x => (x && x.name) !== nm);
	      safeSaveWorksets(items);
	      if (safeGetActiveWorksetName() === nm) safeSetActiveWorksetName('');
	      return { ok:true };
	    }

	    function importWorksetObject(obj) {
	      if (!obj || typeof obj !== 'object') return { ok:false, error:'invalid object' };
	      const nm = String(obj.name || '').trim() || `shared-${new Date().toISOString().slice(0,10)}`;
	      const pid = String(obj.project_id || '').trim();
	      const sid = String(obj.session_id || '').trim();
	      const prefs = obj.prefs && typeof obj.prefs === 'object' ? obj.prefs : snapshotConsolePrefs();
	      const items = safeLoadWorksets();
	      const now = new Date().toISOString();
	      const idx = items.findIndex(x => (x && x.name) === nm);
	      const w = { name: nm, project_id: pid, session_id: sid, prefs, updated_at: now };
	      if (idx >= 0) items[idx] = w; else items.push(w);
	      safeSaveWorksets(items);
	      safeSetActiveWorksetName(nm);
	      return { ok:true, name: nm };
	    }

	    function pickShareMode() {
	      const m = (document.getElementById('shareMode')?.value || 'full').trim();
	      return (m === 'prefs') ? 'prefs' : 'full';
	    }

	    function worksetForShare(w) {
	      const mode = pickShareMode();
	      if (mode === 'prefs') {
	        return {
	          name: String(w.name || '').trim() || 'shared',
	          prefs: w.prefs || snapshotConsolePrefs(),
	          updated_at: new Date().toISOString(),
	        };
	      }
	      return w;
	    }

		    function currentConsoleState() {
		      const pid = (document.getElementById('insProjectId')?.value || '').trim();
		      const sid = (document.getElementById('insSessionId')?.value || '').trim();
		      const prefs = snapshotConsolePrefs();
		      return { project_id: pid, session_id: sid, prefs };
		    }

		    function readWsApplyOpts() {
		      const ap = document.getElementById('wsApplyProject');
		      const as = document.getElementById('wsApplySession');
		      const af = document.getElementById('wsApplyPrefs');
		      return {
		        project: ap ? !!ap.checked : true,
		        session: as ? !!as.checked : true,
		        prefs: af ? !!af.checked : true,
		      };
		    }

		    function updateWsImportPreview() {
		      const prev = document.getElementById('wsImportPreview');
		      if (!prev) return;
		      const obj = pendingWsImport || {};
		      const nm = (document.getElementById('wsImportName')?.value || '').trim() || String(obj.name || '').trim();
		      const opts = readWsApplyOpts();
		      const cur = currentConsoleState();
		      const w = {
		        name: nm || 'shared',
		        project_id: opts.project ? String(obj.project_id || '').trim() : '',
		        session_id: opts.session ? String(obj.session_id || '').trim() : '',
		        // If prefs not applied, set target prefs to current so diff view shows no prefs changes.
		        prefs: opts.prefs ? (obj.prefs || {}) : cur.prefs,
		      };
		      prev.textContent = describeWorksetApply(w);
		    }

		    async function applyWorksetSelective(obj, opts) {
		      const w = obj || {};
		      if (opts.prefs) applyConsolePrefs(w.prefs || {});
		      if (opts.project && w.project_id) {
		        document.getElementById('insProjectId').value = String(w.project_id || '').trim();
		        document.getElementById('memProjectId').value = String(w.project_id || '').trim();
		      }
		      if (opts.session && w.session_id) setActiveSession(String(w.session_id || '').trim());
		      applyEventSearch();
		      await loadInsights();
		      await loadMem();
		      await loadLayerStats();
		    }

		    function describeWorksetApply(w) {
		      const cur = currentConsoleState();
		      const tgt = {
		        project_id: String(w.project_id || '').trim(),
	        session_id: String(w.session_id || '').trim(),
	        prefs: w.prefs || {},
	      };
	      const lines = [];
	      if (tgt.project_id && tgt.project_id !== cur.project_id) lines.push(`project: ${cur.project_id || '(empty)'} -> ${tgt.project_id}`);
	      if (tgt.session_id && tgt.session_id !== cur.session_id) lines.push(`session: ${cur.session_id ? (cur.session_id.slice(0,12)+'...') : '(empty)'} -> ${tgt.session_id.slice(0,12)}...`);
	      const p = tgt.prefs || {};
	      if (String(p.evt_type || '').trim() !== String(cur.prefs.evt_type || '').trim()) lines.push(`evtType: ${cur.prefs.evt_type || '(all)'} -> ${p.evt_type || '(all)'}`);
	      if (String(p.evt_search || '').trim() !== String(cur.prefs.evt_search || '').trim()) lines.push(`evtSearch: "${cur.prefs.evt_search || ''}" -> "${p.evt_search || ''}"`);
	      if (String(p.evt_sort || '').trim() !== String(cur.prefs.evt_sort || '').trim()) lines.push(`evtSort: ${cur.prefs.evt_sort} -> ${p.evt_sort || cur.prefs.evt_sort}`);
	      if (typeof p.live_on === 'boolean' && p.live_on !== cur.prefs.live_on) lines.push(`live: ${cur.prefs.live_on ? 'on' : 'off'} -> ${p.live_on ? 'on' : 'off'}`);
	      if (Number(p.live_ms || 0) && Number(p.live_ms) !== Number(cur.prefs.live_ms)) lines.push(`liveInterval: ${Math.round(cur.prefs.live_ms/1000)}s -> ${Math.round(Number(p.live_ms)/1000)}s`);
	      return lines.length ? lines.join('\\n') : '(no changes)';
	    }

	    function applyInitialScope() {
	      const mode = safeGetScopeMode();
	      const sel = document.getElementById('scopeMode');
	      if (sel) sel.value = mode;
	      const pidEl = document.getElementById('insProjectId');
	      const mpEl = document.getElementById('memProjectId');
	      const sEl = document.getElementById('insSessionId');

	      const pinned = safeGetWorkset();
	      const activeName = safeGetActiveWorksetName();

	      const applyPinned = () => {
	        if (pinned.project_id) {
	          if (pidEl && !pidEl.value.trim()) pidEl.value = pinned.project_id;
	          if (mpEl && !mpEl.value.trim()) mpEl.value = pinned.project_id;
	        }
	        if (pinned.session_id) {
	          if (sEl && !sEl.value.trim()) setActiveSession(pinned.session_id);
	        }
	      };

	      if (mode === 'none') return;
	      if (mode === 'pin') { applyPinned(); return; }
	      if (mode === 'active') return; // active applied later (async)
	      // auto: apply pin as fallback, active later overrides
	      applyPinned();
	    }

	    function snapshotConsolePrefs() {
	      const evt_type = (document.getElementById('evtType')?.value || '').trim();
	      const evt_search = (document.getElementById('evtSearch')?.value || '').trim();
	      const evt_sort = `${eventsSort.key || 'event_time'}:${eventsSort.dir || 'desc'}`;
	      const live_ms = readLiveIntervalMs();
	      const live_on = !!liveOn;
	      return { evt_type, evt_search, evt_sort, live_ms, live_on };
	    }

	    function applyConsolePrefs(prefs) {
	      const p = prefs || {};
	      try {
	        const et = String(p.evt_type || '').trim();
	        const sel = document.getElementById('evtType');
	        if (sel) sel.value = et;
	        safeSetEvtType(et);
	      } catch (_) {}
	      try {
	        const q = String(p.evt_search || '').trim();
	        const el = document.getElementById('evtSearch');
	        if (el) el.value = q;
	        safeSetEvtSearch(q);
	      } catch (_) {}
	      try {
	        const raw = String(p.evt_sort || '').trim() || safeGetEvtSort();
	        const parts = raw.split(':');
	        const k = parts[0] || 'event_time';
	        const d = parts[1] || 'desc';
	        eventsSort = { key: k, dir: (d === 'asc' ? 'asc' : 'desc') };
	        safeSetEvtSort(`${eventsSort.key}:${eventsSort.dir}`);
	      } catch (_) {}
	      try {
	        const ms = Number(p.live_ms);
	        const sel = document.getElementById('liveInterval');
	        if (sel && Number.isFinite(ms)) sel.value = String(ms);
	        try { localStorage.setItem('omnimem.live_ms', String(readLiveIntervalMs())); } catch (_) {}
	      } catch (_) {}
	      try {
	        if (typeof p.live_on === 'boolean') setLive(!!p.live_on);
	      } catch (_) {}
	    }

	    function setActiveSession(sid) {
	      document.getElementById('insSessionId').value = sid || '';
	      document.getElementById('memSessionId').value = sid || '';
	      try { localStorage.setItem('omnimem.active_session', sid || ''); } catch (_) {}
	    }

	    async function loadTimeline(project_id, session_id) {
	      const d = await jget('/api/timeline?project_id=' + encodeURIComponent(project_id || '') + '&session_id=' + encodeURIComponent(session_id || '') + '&limit=80');
	      const el = document.getElementById('insTimeline');
	      if (!d.ok) {
	        el.innerHTML = `<span class="err">${escHtml(d.error || 'timeline failed')}</span>`;
	        return;
	      }
	      const groups = {};
	      (d.items || []).forEach(x => {
	        const sid = x.session_id || 'session-unknown';
	        (groups[sid] ||= []).push(x);
	      });
	      const sids = Object.keys(groups);
	      el.innerHTML = sids.map(sid => {
	        const rows = groups[sid].map(x => {
	          const drift = (typeof x.drift === 'number') ? ` drift=${x.drift.toFixed(2)}` : '';
	          const mark = x.kind === 'checkpoint' ? 'CP' : 'TRN';
	          const sw = x.switched ? ' <span class="pill"><b>switch</b></span>' : '';
	          return `<div style="display:flex; gap:10px; align-items:baseline; margin:4px 0;">
	            <span class="pill"><b>${mark}</b><span>${escHtml(x.layer)}</span></span>
	            <a href="#" data-id="${escHtml(x.id)}"><span class="mono">${escHtml(x.updated_at || '')}</span> ${escHtml(x.summary || '')}${escHtml(drift)}</a>${sw}
	          </div>`;
	        }).join('');
	        return `<div style="margin:10px 0; padding:10px; border:1px solid var(--line); border-radius:14px; background:#fff;">
	          <div class="small" style="display:flex; justify-content:space-between; gap:10px; align-items:baseline;">
	            <div><b>session</b> <span class="mono">${escHtml(sid)}</span></div>
	            <div class="row-btn" style="margin:0">
	              <button class="secondary" style="margin-top:0" data-session="${escHtml(sid)}">Activate</button>
	            </div>
	          </div>
	          <div style="margin-top:6px">${rows}</div>
	        </div>`;
	      }).join('') || '<span class="small">(empty)</span>';
	      el.querySelectorAll('a[data-id]').forEach(a => {
	        a.onclick = async (e) => {
	          e.preventDefault();
	          const id = a.dataset.id;
	          await openMemory(id);
	        };
	      });
	      el.querySelectorAll('button[data-session]').forEach(btn => {
	        btn.onclick = async () => {
	          const sid = btn.dataset.session || '';
	          setActiveSession(sid);
	          await loadInsights();
	          await loadMem();
	          await loadLayerStats();
	          toast('Session', `active=${sid.slice(0,12)}...`, true);
	        };
	      });
	    }

    async function toggleDaemon(enabled) {
      await jpost('/api/daemon/toggle', {enabled});
      await loadDaemon();
      toast('Daemon', enabled ? 'enabled' : 'disabled', true);
    }

    async function attachProject() {
      const project_path = document.getElementById('projectPath').value.trim();
      const project_id = document.getElementById('projectId').value.trim();
      const out = document.getElementById('projectOut');
      const d = await jpost('/api/project/attach', {project_path, project_id});
      out.textContent = JSON.stringify(d, null, 2);
      document.getElementById('status').innerHTML = d.ok ? `<span class=\"ok\">${t('project_attach_ok')}</span>` : `<span class=\"err\">${t('project_failed')}</span>`;
      toast('Project', d.ok ? t('project_attach_ok') : (d.error || t('project_failed')), !!d.ok);
      if (d.ok) {
        document.getElementById('memProjectId').value = d.project_id || project_id || '';
      }
      await loadMem();
      await loadProjects();
      await loadLayerStats();
      await loadInsights();
    }

    async function detachProject() {
      const project_path = document.getElementById('projectPath').value.trim();
      const out = document.getElementById('projectOut');
      const d = await jpost('/api/project/detach', {project_path});
      out.textContent = JSON.stringify(d, null, 2);
      document.getElementById('status').innerHTML = d.ok ? `<span class=\"ok\">${t('project_detach_ok')}</span>` : `<span class=\"err\">${t('project_failed')}</span>`;
      toast('Project', d.ok ? t('project_detach_ok') : (d.error || t('project_failed')), !!d.ok);
      await loadProjects();
      await loadLayerStats();
      await loadInsights();
    }

    function escHtml(v) {
      return String(v).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('\"', '&quot;');
    }

    async function listDirs(path) {
      const d = await jget('/api/fs/list?path=' + encodeURIComponent(path || ''));
      if (!d.ok) {
        document.getElementById('browserList').innerHTML = `<span class=\"err\">${escHtml(d.error || 'list failed')}</span>`;
        return;
      }
      browserPath = d.path || '';
      document.getElementById('browserPath').textContent = browserPath;
      const rows = (d.items || [])
        .map(x => `<div><a href=\"#\" data-path=\"${escHtml(x.path)}\">${escHtml(x.name)}/</a></div>`)
        .join('');
      document.getElementById('browserList').innerHTML = rows || '<span class=\"small\">(empty)</span>';
      document.querySelectorAll('#browserList a').forEach(a => {
        a.onclick = (e) => {
          e.preventDefault();
          listDirs(a.dataset.path || '');
        };
      });
    }

    async function loadProjects() {
      const d = await jget('/api/projects');
      const b = document.getElementById('projectsBody');
      b.innerHTML = '';
      (d.items || []).forEach(x => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${escHtml(x.project_id || '')}</td><td>${escHtml(x.project_path || '')}</td><td>${escHtml(x.updated_at || '')}</td><td><button data-action=\"use\" data-path=\"${escHtml(x.project_path || '')}\" data-id=\"${escHtml(x.project_id || '')}\">${t('btn_use')}</button> <button data-action=\"detach\" data-path=\"${escHtml(x.project_path || '')}\">${t('btn_detach')}</button></td>`;
        b.appendChild(tr);
      });
      document.querySelectorAll('#projectsBody button').forEach(btn => {
        btn.onclick = async () => {
          const action = btn.dataset.action || '';
          const path = btn.dataset.path || '';
          if (action === 'use') {
            document.getElementById('projectPath').value = path;
            document.getElementById('projectId').value = btn.dataset.id || '';
            document.getElementById('memProjectId').value = btn.dataset.id || '';
            await loadMem();
            return;
          }
          if (action === 'detach') {
            document.getElementById('projectPath').value = path;
            await detachProject();
          }
        };
      });
    }

	    function bindTabs() {
	      const btns = document.querySelectorAll('.tab-btn');
	      btns.forEach(btn => {
	        btn.onclick = () => {
	          btns.forEach(x => x.classList.remove('active'));
	          btn.classList.add('active');
	          document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
	          document.getElementById(btn.dataset.tab).classList.add('active');
	        };
	      });
	    }

	    function setActiveTab(tabId) {
	      const btns = document.querySelectorAll('.tab-btn');
	      btns.forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
	      document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id === tabId));
	    }

    document.getElementById('langSelect').onchange = (e) => {
      currentLang = e.target.value;
      safeSetLang(currentLang);
      applyI18n();
      loadCfg();
    };
    document.getElementById('btnToggleAdvanced').onclick = () => {
      advancedOn = !advancedOn;
      safeSetAdvanced(advancedOn);
      applyI18n();
    };

		    function bindActions() {
      document.getElementById('btnSyncStatus').onclick = () => runSync('github-status');
      document.getElementById('btnSyncBootstrap').onclick = () => runSync('github-bootstrap');
      document.getElementById('btnSyncPush').onclick = () => runSync('github-push');
      document.getElementById('btnSyncPull').onclick = () => runSync('github-pull');
      document.getElementById('btnDaemonOn').onclick = () => toggleDaemon(true);
      document.getElementById('btnDaemonOff').onclick = () => toggleDaemon(false);
      document.getElementById('btnConflictRecovery').onclick = () => runConflictRecovery();
	          document.getElementById('btnProjectAttach').onclick = () => attachProject();
	          document.getElementById('btnProjectDetach').onclick = () => detachProject();
	          document.getElementById('btnMemReload').onclick = () => loadMem();
	          document.getElementById('btnMemOpenBoard').onclick = async () => { setActiveTab('insightsTab'); await loadInsights(); };
	          document.getElementById('memLayer').onchange = () => loadMem();
          document.getElementById('memSessionId').onchange = () => { loadMem(); loadLayerStats(); };
          document.getElementById('memProjectId').onchange = () => { loadMem(); loadLayerStats(); };
          const mq = document.getElementById('memQuery');
          if (mq) {
            mq.onkeydown = (e) => { if (e.key === 'Enter') loadMem(); };
          }
          document.getElementById('btnInsightsReload').onclick = () => loadInsights();
          document.getElementById('insProjectId').onchange = () => loadInsights();
          document.getElementById('insSessionId').onchange = () => loadInsights();
          const gov = document.getElementById('btnGovernReload');
          if (gov) {
            gov.onclick = async () => {
              saveThrToStorage();
              await loadGovernance(
                document.getElementById('insProjectId').value.trim(),
                document.getElementById('insSessionId').value.trim()
              );
              toast('Governance', 'thresholds applied', true);
            };
          }
          ['thrPImp','thrPConf','thrPStab','thrPVol','thrDVol','thrDStab','thrDReuse'].forEach(id => {
            const el = document.getElementById(id);
            if (!el) return;
            el.oninput = () => syncThrLabels();
            el.onchange = () => saveThrToStorage();
          });
          document.getElementById('btnProjectsReload').onclick = () => loadProjects();
      document.getElementById('btnBrowseProject').onclick = async () => {
        document.getElementById('browserPanel').style.display = 'block';
        await listDirs(document.getElementById('projectPath').value.trim() || '');
      };
      document.getElementById('btnBrowserUp').onclick = async () => {
        if (!browserPath) return;
        const p = browserPath.replace(/\/+$/, '');
        const i = p.lastIndexOf('/');
        const up = i > 0 ? p.slice(0, i) : '/';
        await listDirs(up);
      };
      document.getElementById('btnBrowserSelect').onclick = () => {
        document.getElementById('projectPath').value = browserPath;
        const pid = document.getElementById('projectId');
        if (!pid.value.trim() && browserPath) {
          const s = browserPath.replace(/\/+$/, '').split('/');
          pid.value = s[s.length - 1] || 'project';
        }
      };
      document.getElementById('btnBrowserClose').onclick = () => {
        document.getElementById('browserPanel').style.display = 'none';
      };
      document.getElementById('btnUseCwd').onclick = async () => {
        const d = await jget('/api/fs/cwd');
        if (d.ok) {
          document.getElementById('projectPath').value = d.cwd;
          const pid = document.getElementById('projectId');
          if (!pid.value.trim()) {
            const s = d.cwd.replace(/\/+$/, '').split('/');
            pid.value = s[s.length - 1] || 'project';
          }
        }
      };
		      document.getElementById('btnDrawerClose').onclick = () => { setDrawerEditMode(false); showDrawer(false); };
		      document.getElementById('overlay').onclick = () => { setDrawerEditMode(false); showDrawer(false); };
		      const bEdit = document.getElementById('btnEdit');
		      const bSave = document.getElementById('btnSave');
		      const bCancel = document.getElementById('btnCancel');
		      if (bEdit) bEdit.onclick = () => setDrawerEditMode(true);
		      if (bCancel) bCancel.onclick = () => setDrawerEditMode(false);
		      if (bSave) bSave.onclick = () => saveDrawerEdit();
		      const mo = document.getElementById('modalOverlay');
	      if (mo) mo.onclick = () => { showWsModal(false); clearWsHash(); };
	      const mclose = document.getElementById('btnWsModalClose');
	      if (mclose) mclose.onclick = () => { showWsModal(false); clearWsHash(); };
	      const mCancel = document.getElementById('btnWsImportCancel');
	      if (mCancel) mCancel.onclick = () => { showWsModal(false); clearWsHash(); };
	      const mName = document.getElementById('wsImportName');
	      if (mName) mName.oninput = () => updateWsImportPreview();
	      ['wsApplyProject','wsApplySession','wsApplyPrefs'].forEach(id => {
	        const el = document.getElementById(id);
	        if (el) el.onchange = () => updateWsImportPreview();
	      });
	      const mOnly = document.getElementById('btnWsImportOnly');
	      if (mOnly) mOnly.onclick = async () => {
	        if (!pendingWsImport) return;
	        const opts = readWsApplyOpts();
	        const nm = (document.getElementById('wsImportName')?.value || '').trim();
	        const obj = Object.assign({}, pendingWsImport, { name: nm || pendingWsImport.name });
	        const r = importWorksetObject(obj);
	        if (!r.ok) { toast('Workset', r.error || 'import failed', false); return; }
	        refreshWorksetSelect();
	        renderWorksetHint();
	        showWsModal(false);
	        clearWsHash();
	        toast('Workset', 'imported', true);
	      };
	      const mApply = document.getElementById('btnWsImportApply');
	      if (mApply) mApply.onclick = async () => {
	        if (!pendingWsImport) return;
	        const opts = readWsApplyOpts();
	        const nm = (document.getElementById('wsImportName')?.value || '').trim();
	        const obj = Object.assign({}, pendingWsImport, { name: nm || pendingWsImport.name });
	        const r = importWorksetObject(obj);
	        if (!r.ok) { toast('Workset', r.error || 'import failed', false); return; }
	        refreshWorksetSelect();
	        renderWorksetHint();
	        showWsModal(false);
	        clearWsHash();
	        // Apply only the selected fields; always import the full workset for later use.
	        const stored = safeLoadWorksets().find(x => (x && x.name) === r.name) || obj;
	        await applyWorksetSelective(stored, opts);
	        toast('Workset', 'imported + applied', true);
	      };
	      const sessReload = document.getElementById('btnSessionsReload');
	      if (sessReload) sessReload.onclick = () => loadSessions(document.getElementById('insProjectId')?.value?.trim() || '');
	      const clearSess = document.getElementById('btnClearSession');
	      if (clearSess) clearSess.onclick = async () => {
	        setActiveSession('');
	        await loadInsights();
	        await loadMem();
	        await loadLayerStats();
	        toast('Session', 'cleared', true);
	      };
	      const archActive = document.getElementById('btnArchiveActiveSession');
	      if (archActive) archActive.onclick = async () => {
	        const pid = document.getElementById('insProjectId')?.value?.trim() || '';
	        const sid = (document.getElementById('insSessionId')?.value || '').trim();
	        if (!sid) {
	          toast('Session', 'no active session', false);
	          return;
	        }
	        const opts = readSessionArchiveOpts();
	        if (!confirm(`Archive active session ${sid.slice(0,12)}... from ${opts.from_layers.join('+')} -> ${opts.to_layer}?`)) return;
	        const r = await jpost('/api/session/archive', {
	          project_id: pid,
	          session_id: sid,
	          from_layers: opts.from_layers,
	          to_layer: opts.to_layer,
	          limit: opts.limit
	        });
	        if (!r.ok) {
	          toast('Session', r.error || 'archive failed', false);
	          return;
	        }
	        toast('Session', `archived ${r.moved || 0} items`, true);
	        await loadInsights();
	        await loadMem();
	        await loadLayerStats();
	      };
	      const evReload = document.getElementById('btnEventsReload');
	      if (evReload) evReload.onclick = () => loadEvents(
	        document.getElementById('insProjectId')?.value?.trim() || '',
	        document.getElementById('insSessionId')?.value?.trim() || ''
	      );
	      const dp = document.getElementById('btnDecayPreview');
	      if (dp) dp.onclick = () => runDecay(true);
	      const da = document.getElementById('btnDecayApply');
	      if (da) da.onclick = () => runDecay(false);
	      const evType = document.getElementById('evtType');
	      if (evType) evType.onchange = () => loadEvents(
	        document.getElementById('insProjectId')?.value?.trim() || '',
	        document.getElementById('insSessionId')?.value?.trim() || ''
	      );
	      const evSearch = document.getElementById('evtSearch');
	      if (evSearch) evSearch.oninput = () => applyEventSearch();
	      const pinBtn = document.getElementById('btnPinWorkset');
	      if (pinBtn) pinBtn.onclick = async () => {
	        const pid = document.getElementById('insProjectId')?.value?.trim() || '';
	        const sid = document.getElementById('insSessionId')?.value?.trim() || '';
	        safeSetWorkset(pid, sid);
	        renderWorksetHint();
	        toast('Workset', 'pinned', true);
	      };
	      const pinClr = document.getElementById('btnClearPin');
	      if (pinClr) pinClr.onclick = async () => {
	        safeSetWorkset('', '');
	        renderWorksetHint();
	        toast('Workset', 'cleared', true);
	      };
	      const wsSel = document.getElementById('worksetSelect');
	      if (wsSel) wsSel.onchange = async () => {
	        const name = wsSel.value || '';
	        if (!name) {
	          safeSetActiveWorksetName('');
	          return;
	        }
	        const items = safeLoadWorksets();
	        const w = items.find(x => (x && x.name) === name);
	        if (w && safeGetWsConfirm()) {
	          const msg = `Apply workset "${name}"?\n\n` + describeWorksetApply(w);
	          if (!confirm(msg)) {
	            wsSel.value = safeGetActiveWorksetName() || '';
	            return;
	          }
	        }
	        await applyWorksetByName(name);
	        toast('Workset', `applied ${name}`, true);
	      };
	      const wsSave = document.getElementById('btnWorksetSave');
	      if (wsSave) wsSave.onclick = async () => {
	        const name = document.getElementById('worksetName')?.value || '';
	        const pid = document.getElementById('insProjectId')?.value?.trim() || '';
	        const sid = document.getElementById('insSessionId')?.value?.trim() || '';
	        const r = upsertWorkset(name, pid, sid);
	        if (!r.ok) {
	          toast('Workset', r.error || 'save failed', false);
	          return;
	        }
	        refreshWorksetSelect();
	        renderWorksetHint();
	        toast('Workset', 'saved', true);
	      };
	      const wsDel = document.getElementById('btnWorksetDelete');
	      if (wsDel) wsDel.onclick = async () => {
	        const name = document.getElementById('worksetSelect')?.value || (document.getElementById('worksetName')?.value || '');
	        const nm = String(name || '').trim();
	        if (!nm) {
	          toast('Workset', 'missing name', false);
	          return;
	        }
	        if (!confirm(`Delete workset ${nm}?`)) return;
	        const r = deleteWorkset(nm);
	        if (!r.ok) {
	          toast('Workset', r.error || 'delete failed', false);
	          return;
	        }
	        refreshWorksetSelect();
	        renderWorksetHint();
	        toast('Workset', 'deleted', true);
	      };
	      const wsExp = document.getElementById('btnWorksetExport');
	      if (wsExp) wsExp.onclick = async () => {
	        const sel = document.getElementById('worksetSelect');
	        const name = sel ? (sel.value || '') : '';
	        const items = safeLoadWorksets();
	        const w = items.find(x => (x && x.name) === name);
	        if (!w) {
	          toast('Workset', 'select a workset to export', false);
	          return;
	        }
	        const txt = JSON.stringify(w, null, 2);
	        try {
	          await navigator.clipboard.writeText(txt);
	          toast('Workset', 'export copied to clipboard', true);
	        } catch (_) {
	          // Fallback: prompt for manual copy.
	          prompt('Workset export JSON (copy):', txt);
	        }
	      };
	      const wsImp = document.getElementById('btnWorksetImport');
	      if (wsImp) wsImp.onclick = async () => {
	        const raw = prompt('Paste workset JSON to import:', '');
	        if (!raw) return;
	        let obj = null;
	        try { obj = JSON.parse(raw); } catch (_) {}
	        if (!obj || typeof obj !== 'object') {
	          toast('Workset', 'invalid JSON', false);
	          return;
	        }
	        beginWorksetImportReview(obj, 'manual import');
	      };
	      const wsShare = document.getElementById('btnWorksetShare');
	      if (wsShare) wsShare.onclick = async () => {
	        const sel = document.getElementById('worksetSelect');
	        const name = sel ? (sel.value || '') : '';
	        const items = safeLoadWorksets();
	        const w = items.find(x => (x && x.name) === name);
	        if (!w) {
	          toast('Workset', 'select a workset to share', false);
	          return;
	        }
	        const txt = JSON.stringify(worksetForShare(w));
	        const hash = '#ws=' + b64urlEncode(txt);
	        const url = location.origin + location.pathname + hash;
	        try {
	          await navigator.clipboard.writeText(url);
	          toast('Workset', 'share link copied', true);
	        } catch (_) {
	          prompt('Workset share link (copy):', url);
	        }
	      };
	      const wsConfirm = document.getElementById('wsConfirm');
	      if (wsConfirm) {
	        wsConfirm.checked = safeGetWsConfirm();
	        wsConfirm.onchange = () => safeSetWsConfirm(!!wsConfirm.checked);
	      }
	      const scopeSel = document.getElementById('scopeMode');
	      if (scopeSel) scopeSel.onchange = () => {
	        safeSetScopeMode(scopeSel.value || 'auto');
	        applyInitialScope();
	        toast('Scope', String(scopeSel.value || 'auto'), true);
	      };
	      document.querySelectorAll('a[data-sort]').forEach(a => {
	        a.onclick = async (e) => {
	          e.preventDefault();
	          const key = a.dataset.sort || 'event_time';
	          const nextDir = (eventsSort.key === key && eventsSort.dir === 'desc') ? 'asc' : 'desc';
	          eventsSort = { key, dir: nextDir };
	          safeSetEvtSort(`${eventsSort.key}:${eventsSort.dir}`);
	          await loadEvents(
	            document.getElementById('insProjectId')?.value?.trim() || '',
	            document.getElementById('insSessionId')?.value?.trim() || ''
	          );
	        };
	      });
	      const evOpen = document.getElementById('btnEventOpenMem');
	      if (evOpen) evOpen.onclick = async () => {
	        if (!currentEvent || !currentEvent.memory_id) return;
	        await openMemory(currentEvent.memory_id);
	      };
	      const evAct = document.getElementById('btnEventActivate');
	      if (evAct) evAct.onclick = async () => {
	        if (!currentEvent) return;
	        const ctx = deriveEventContext(currentEvent);
	        if (!ctx.session_id) return;
	        setActiveSession(ctx.session_id);
	        await loadInsights();
	        await loadMem();
	        await loadLayerStats();
	        toast('Session', `active=${ctx.session_id.slice(0,12)}...`, true);
	      };
	      const evShow = document.getElementById('btnEventShowSession');
	      if (evShow) evShow.onclick = async () => {
	        if (!currentEvent) return;
	        const ctx = deriveEventContext(currentEvent);
	        if (!ctx.session_id) return;
	        // Keep active session in sync with the filter.
	        setActiveSession(ctx.session_id);
	        const sel = document.getElementById('evtType');
	        if (sel) sel.value = '';
	        await loadEvents(
	          document.getElementById('insProjectId')?.value?.trim() || '',
	          ctx.session_id
	        );
	        await loadEventStats(
	          document.getElementById('insProjectId')?.value?.trim() || '',
	          ctx.session_id
	        );
	        toast('Event', 'scoped log to session', true);
	      };
	      const evRev = document.getElementById('btnEventRevert');
	      if (evRev) evRev.onclick = async () => {
	        if (!canRevertPromote(currentEvent)) return;
	        const p = currentEvent.payload || {};
	        const mid = String(currentEvent.memory_id || '').trim();
	        const from_layer = String(p.from_layer || '').trim();
	        const to_layer = String(p.to_layer || '').trim();
	        if (!confirm(`Revert promote: ${mid.slice(0,12)}... ${to_layer} -> ${from_layer}?`)) return;
	        await moveLayer(mid, from_layer);
	        toast('Event', 'reverted promote', true);
	        // refresh event log to reflect state changes
	        await loadEvents(
	          document.getElementById('insProjectId')?.value?.trim() || '',
	          document.getElementById('insSessionId')?.value?.trim() || ''
	        );
	      };
	      const evCopy = document.getElementById('btnEventCopy');
	      if (evCopy) evCopy.onclick = async () => {
	        if (!currentEvent) return;
	        const txt = JSON.stringify(currentEvent, null, 2);
	        try {
	          await navigator.clipboard.writeText(txt);
	          toast('Clipboard', 'event payload copied', true);
	        } catch (_) {
	          toast('Clipboard', 'copy failed (permission)', false);
	        }
	      };
	      const bSel = document.getElementById('btnBoardSelectToggle');
	      if (bSel) bSel.onclick = () => setBoardSelectMode(!boardSelectMode);
	      const bP = document.getElementById('btnBoardPromote');
	      if (bP) bP.onclick = () => batchMove(Array.from(selectedBoardIds), 'long');
	      const bD = document.getElementById('btnBoardDemote');
	      if (bD) bD.onclick = () => batchMove(Array.from(selectedBoardIds), 'short');
	      const bA = document.getElementById('btnBoardArchive');
	      if (bA) bA.onclick = () => batchMove(Array.from(selectedBoardIds), 'archive');
	      const bC = document.getElementById('btnBoardClear');
	      if (bC) bC.onclick = () => clearBoardSelection();
	      const liveBtn = document.getElementById('btnLiveToggle');
	      if (liveBtn) liveBtn.onclick = () => setLive(!liveOn);
          const liveSel = document.getElementById('liveInterval');
          if (liveSel) {
            liveSel.onchange = () => {
              try { localStorage.setItem('omnimem.live_ms', String(readLiveIntervalMs())); } catch (_) {}
              if (liveOn) setLive(true);
              renderLive();
            };
          }
        }

	    window.addEventListener('keydown', (e) => {
	      if (e.key === 'Escape') showDrawer(false);
	    });
	
	    function shouldIgnoreKeys(e) {
	      const t = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
	      if (t === 'input' || t === 'textarea' || t === 'select') return true;
	      if (e.metaKey || e.ctrlKey || e.altKey) return true;
	      return false;
	    }

	    window.addEventListener('keydown', async (e) => {
	      if (shouldIgnoreKeys(e)) return;
	      const active = document.querySelector('.panel.active')?.id || '';
	      if (active !== 'insightsTab') return;
	      const body = document.getElementById('eventsBody');
	      if (!body) return;
	      if (!eventsCache || !eventsCache.length) return;
	      if (e.key === 'j' || e.key === 'ArrowDown') {
	        e.preventDefault();
	        const next = Math.min(eventsCache.length - 1, (selectedEventIdx < 0 ? 0 : selectedEventIdx + 1));
	        const tr = body.querySelectorAll('tr')[next];
	        if (tr) tr.click();
	      }
	      if (e.key === 'k' || e.key === 'ArrowUp') {
	        e.preventDefault();
	        const prev = Math.max(0, (selectedEventIdx < 0 ? 0 : selectedEventIdx - 1));
	        const tr = body.querySelectorAll('tr')[prev];
	        if (tr) tr.click();
	      }
	    });

    window.addEventListener('error', (e) => {
      const s = document.getElementById('status');
      if (s) s.innerHTML = `<span class=\"err\">UI error: ${e.message}</span>`;
    });

		    bindActions();
		    bindTabs();
		    applyI18n();
        loadBuildInfo();
		    loadThrFromStorage();
	    loadLiveFromStorage();
	    updateBoardToolbar();
	    updateEventActions();
	    renderWorksetHint();
	    refreshWorksetSelect();
	    applyInitialScope();
	    try {
	      const wsc = document.getElementById('wsConfirm');
	      if (wsc) wsc.checked = safeGetWsConfirm();
	    } catch (_) {}
	    try {
	      const raw = safeGetEvtSort();
	      const parts = String(raw).split(':');
	      const k = parts[0] || 'event_time';
	      const d = parts[1] || 'desc';
	      eventsSort = { key: k, dir: (d === 'asc' ? 'asc' : 'desc') };
	    } catch (_) {}
	    try {
	      const sid = localStorage.getItem('omnimem.active_session') || '';
	      if (sid) setActiveSession(sid);
	    } catch (_) {}
	    try {
	      const et = safeGetEvtType();
	      const sel = document.getElementById('evtType');
	      if (sel && et) sel.value = et;
	    } catch (_) {}
	    try {
	      const q = safeGetEvtSearch();
	      const el = document.getElementById('evtSearch');
	      if (el && q) el.value = q;
	    } catch (_) {}
	    // Pinned workset applied via applyInitialScope()
	    try {
	      const name = safeGetActiveWorksetName();
	      const mode = safeGetScopeMode();
	      if (name && (mode === 'auto' || mode === 'active')) applyWorksetByName(name);
	    } catch (_) {}
	    // Hash import: #ws=base64url(JSON)
	    try {
	      const h = (location.hash || '').trim();
	      if (h.startsWith('#ws=')) {
	        const raw = b64urlDecode(h.slice(4));
	        const obj = JSON.parse(raw);
	        beginWorksetImportReview(obj, 'share link');
	      }
	    } catch (_) {}
        loadCfg();
        loadMem();
        loadDaemon();
        loadLayerStats();
        loadInsights();
        loadProjects();
  </script>
</body>
</html>
"""


def _cfg_to_ui(cfg: dict[str, Any], cfg_path: Path) -> dict[str, Any]:
    storage = cfg.get("storage", {})
    gh = cfg.get("sync", {}).get("github", {})
    return {
        "ok": True,
        "initialized": cfg_path.exists(),
        "config_path": str(cfg_path),
        "home": cfg.get("home", ""),
        "markdown": storage.get("markdown", ""),
        "jsonl": storage.get("jsonl", ""),
        "sqlite": storage.get("sqlite", ""),
        "remote_name": gh.get("remote_name", "origin"),
        "remote_url": gh.get("remote_url", ""),
        "branch": gh.get("branch", "main"),
    }


def _projects_registry_path(home: str) -> Path:
    base = Path(home).expanduser().resolve() if home else (Path.home() / ".omnimem")
    return base / "projects.local.json"


def _load_projects_registry(home: str) -> list[dict[str, Any]]:
    fp = _projects_registry_path(home)
    if not fp.exists():
        return []
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        return []
    return []


def _save_projects_registry(home: str, items: list[dict[str, Any]]) -> None:
    fp = _projects_registry_path(home)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _register_project(home: str, project_id: str, project_path: str) -> None:
    now = utc_now()
    target = str(Path(project_path).expanduser().resolve())
    items = _load_projects_registry(home)
    for it in items:
        if str(it.get("project_path", "")) == target:
            it["project_id"] = project_id
            it["updated_at"] = now
            _save_projects_registry(home, items)
            return
    items.append(
        {
            "project_id": project_id,
            "project_path": target,
            "attached_at": now,
            "updated_at": now,
        }
    )
    _save_projects_registry(home, items)


def _unregister_project(home: str, project_path: str) -> None:
    target = str(Path(project_path).expanduser().resolve())
    items = _load_projects_registry(home)
    kept = [x for x in items if str(x.get("project_path", "")) != target]
    _save_projects_registry(home, kept)


def _upsert_managed_block(path: Path, block: str) -> None:
    start = "<!-- OMNIMEM:START -->"
    end = "<!-- OMNIMEM:END -->"
    managed = f"{start}\n{block.rstrip()}\n{end}\n"
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if start in old and end in old:
            left = old.split(start, 1)[0].rstrip()
            right = old.split(end, 1)[1].lstrip()
            new_text = f"{left}\n\n{managed}"
            if right:
                new_text += f"\n{right}"
            path.write_text(new_text, encoding="utf-8")
            return
        sep = "\n\n" if old and not old.endswith("\n\n") else ""
        path.write_text(old + sep + managed, encoding="utf-8")
        return
    path.write_text(managed, encoding="utf-8")


def _agent_protocol_block(project_id: str) -> str:
    return (
        "# OmniMem Memory Protocol\n"
        "\n"
        f"- Project ID: `{project_id}`\n"
        "- Session start: run `omnimem brief --project-id <PROJECT_ID> --limit 8` and use it as active context.\n"
        "- During task: when a stable decision/fact appears, run `omnimem write` with concise summary + evidence.\n"
        "- Phase end: run `omnimem checkpoint` with goal/result/next-step/risks.\n"
        "- If confidence is low or info is temporary, store in `instant`/`short`; promote to `long` only when repeated and stable.\n"
        "- Never write raw secrets. Use credential references only (for example `op://...` or `env://...`).\n"
    )


def _attach_project_in_webui(project_path: str, project_id: str, cfg_home: str) -> dict[str, Any]:
    if not project_path:
        return {"ok": False, "error": "project_path is required"}
    project = Path(project_path).expanduser().resolve()
    if not project.exists() or not project.is_dir():
        return {"ok": False, "error": f"project path not found: {project}"}
    if not project_id:
        project_id = project.name

    repo_root = Path(__file__).resolve().parent.parent
    tpl = repo_root / "templates" / "project-minimal"
    created: list[str] = []
    updated: list[str] = []

    files = [
        (tpl / ".omnimem.json", project / ".omnimem.json"),
        (tpl / ".omnimem-session.md", project / ".omnimem-session.md"),
        (tpl / ".omnimem-ignore", project / ".omnimem-ignore"),
    ]
    for src, dst in files:
        text = src.read_text(encoding="utf-8")
        text = text.replace("replace-with-project-id", project_id)
        text = text.replace("~/.omnimem", cfg_home or "~/.omnimem")
        exists = dst.exists()
        dst.write_text(text, encoding="utf-8")
        (updated if exists else created).append(str(dst))

    block = _agent_protocol_block(project_id=project_id)
    managed_targets = [
        project / "AGENTS.md",
        project / "CLAUDE.md",
        project / ".cursorrules",
    ]
    for fp in managed_targets:
        exists = fp.exists()
        _upsert_managed_block(fp, block)
        (updated if exists else created).append(str(fp))

    cursor_rule = project / ".cursor" / "rules" / "omnimem.mdc"
    cursor_exists = cursor_rule.exists()
    cursor_rule.parent.mkdir(parents=True, exist_ok=True)
    cursor_rule.write_text(
        (
            "---\n"
            "description: OmniMem project memory protocol\n"
            "alwaysApply: true\n"
            "---\n\n"
            + block
        ),
        encoding="utf-8",
    )
    (updated if cursor_exists else created).append(str(cursor_rule))

    return {
        "ok": True,
        "project_path": str(project),
        "project_id": project_id,
        "created": created,
        "updated": updated,
    }


def _detach_project_in_webui(project_path: str) -> dict[str, Any]:
    if not project_path:
        return {"ok": False, "error": "project_path is required"}
    project = Path(project_path).expanduser().resolve()
    if not project.exists() or not project.is_dir():
        return {"ok": False, "error": f"project path not found: {project}"}

    removed: list[str] = []
    for name in [
        ".omnimem.json",
        ".omnimem-session.md",
        ".omnimem-ignore",
        ".cursorrules",
        "CLAUDE.md",
        "AGENTS.md",
        ".cursor/rules/omnimem.mdc",
    ]:
        fp = project / name
        if fp.exists():
            txt = fp.read_text(encoding="utf-8", errors="ignore")
            if "<!-- OMNIMEM:START -->" in txt and "<!-- OMNIMEM:END -->" in txt:
                start = txt.index("<!-- OMNIMEM:START -->")
                end = txt.index("<!-- OMNIMEM:END -->") + len("<!-- OMNIMEM:END -->")
                new_txt = (txt[:start] + txt[end:]).strip()
                if new_txt:
                    fp.write_text(new_txt + "\n", encoding="utf-8")
                else:
                    fp.unlink()
                removed.append(str(fp))
                continue
            if fp.name in {".omnimem.json", ".omnimem-session.md", ".omnimem-ignore", "omnimem.mdc"}:
                fp.unlink()
                removed.append(str(fp))
    return {"ok": True, "project_path": str(project), "removed": removed}


def _is_local_bind_host(host: str) -> bool:
    v = host.strip().lower()
    return v in {"127.0.0.1", "localhost", "::1"}


def _resolve_auth_token(cfg: dict[str, Any], explicit_token: str | None) -> str:
    if explicit_token:
        return explicit_token
    env_token = os.getenv("OMNIMEM_WEBUI_TOKEN", "").strip()
    if env_token:
        return env_token
    token = str(cfg.get("webui", {}).get("auth_token", "")).strip()
    return token


def _validate_webui_bind_security(
    *,
    host: str,
    allow_non_localhost: bool,
    resolved_auth_token: str,
) -> None:
    is_local = _is_local_bind_host(host)
    if not allow_non_localhost and not is_local:
        raise ValueError(
            f"refuse to bind non-local host without --allow-non-localhost: {host}"
        )
    # If the user opted into a non-local bind, require auth so the API is not wide open on a LAN/WAN.
    if not is_local and not resolved_auth_token:
        raise ValueError(
            "non-local bind requires an API token; set OMNIMEM_WEBUI_TOKEN or pass --webui-token"
        )


def run_webui(
    *,
    host: str,
    port: int,
    cfg: dict[str, Any],
    cfg_path: Path,
    schema_sql_path: Path,
    sync_runner,
    daemon_runner=None,
    enable_daemon: bool = True,
    daemon_scan_interval: int = 8,
    daemon_pull_interval: int = 30,
    daemon_retry_max_attempts: int = 3,
    daemon_retry_initial_backoff: int = 1,
    daemon_retry_max_backoff: int = 8,
    auth_token: str | None = None,
    allow_non_localhost: bool = False,
) -> None:
    resolved_auth_token = _resolve_auth_token(cfg, auth_token)
    _validate_webui_bind_security(
        host=host,
        allow_non_localhost=allow_non_localhost,
        resolved_auth_token=resolved_auth_token,
    )
    paths = resolve_paths(cfg)
    ensure_storage(paths, schema_sql_path)
    daemon_state: dict[str, Any] = {
        "schema_version": "1.1.0",
        "initialized": cfg_path.exists(),
        "enabled": bool(enable_daemon and cfg_path.exists()),
        "manually_disabled": False,
        "running": False,
        "last_result": {},
        "scan_interval": daemon_scan_interval,
        "pull_interval": daemon_pull_interval,
        "retry_max_attempts": max(1, int(daemon_retry_max_attempts)),
        "retry_initial_backoff": max(1, int(daemon_retry_initial_backoff)),
        "retry_max_backoff": max(1, int(daemon_retry_max_backoff)),
        "cycles": 0,
        "success_count": 0,
        "failure_count": 0,
        "last_run_at": "",
        "last_success_at": "",
        "last_failure_at": "",
        "last_error": "",
        "last_error_kind": "none",
        "remediation_hint": "",
    }
    stop_event = threading.Event()

    def daemon_loop() -> None:
        if daemon_runner is None:
            return
        daemon_state["running"] = True
        while not stop_event.is_set():
            if not daemon_state.get("initialized", False):
                time.sleep(1)
                continue
            if not daemon_state.get("enabled", True):
                time.sleep(1)
                continue
            try:
                daemon_state["cycles"] = int(daemon_state.get("cycles", 0)) + 1
                daemon_state["last_run_at"] = utc_now()
                gh = cfg.get("sync", {}).get("github", {})
                result = daemon_runner(
                    paths=paths,
                    schema_sql_path=schema_sql_path,
                    remote_name=gh.get("remote_name", "origin"),
                    branch=gh.get("branch", "main"),
                    remote_url=gh.get("remote_url"),
                    scan_interval=daemon_scan_interval,
                    pull_interval=daemon_pull_interval,
                    retry_max_attempts=daemon_retry_max_attempts,
                    retry_initial_backoff=daemon_retry_initial_backoff,
                    retry_max_backoff=daemon_retry_max_backoff,
                    once=True,
                )
                daemon_state["last_result"] = result
                if result.get("ok"):
                    daemon_state["success_count"] = int(daemon_state.get("success_count", 0)) + 1
                    daemon_state["last_success_at"] = utc_now()
                    daemon_state["last_error"] = ""
                    daemon_state["last_error_kind"] = "none"
                    daemon_state["remediation_hint"] = ""
                else:
                    daemon_state["failure_count"] = int(daemon_state.get("failure_count", 0)) + 1
                    daemon_state["last_failure_at"] = utc_now()
                    daemon_state["last_error"] = str(result.get("error", "sync failed"))
                    daemon_state["last_error_kind"] = str(result.get("last_error_kind", "unknown"))
                    daemon_state["remediation_hint"] = str(
                        result.get("remediation_hint", sync_error_hint(daemon_state["last_error_kind"]))
                    )
            except Exception as exc:  # pragma: no cover
                daemon_state["last_result"] = {"ok": False, "error": str(exc)}
                daemon_state["failure_count"] = int(daemon_state.get("failure_count", 0)) + 1
                daemon_state["last_failure_at"] = utc_now()
                daemon_state["last_error"] = str(exc)
                daemon_state["last_error_kind"] = "unknown"
                daemon_state["remediation_hint"] = sync_error_hint("unknown")
            time.sleep(max(1, daemon_scan_interval))
        daemon_state["running"] = False

    daemon_thread: threading.Thread | None = None
    if enable_daemon and daemon_runner is not None:
        daemon_thread = threading.Thread(target=daemon_loop, name="omnimem-daemon", daemon=True)
        daemon_thread.start()

    # Micro-cache for expensive aggregations (ThreadingHTTPServer may call handlers concurrently).
    event_stats_cache: dict[tuple[str, str, int], tuple[float, dict[str, Any]]] = {}
    event_stats_lock = threading.Lock()
    events_cache: dict[tuple[str, str, str, int], tuple[float, dict[str, Any]]] = {}
    events_cache_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _authorized(self, parsed) -> bool:
            if parsed.path == "/api/health":
                return True
            if not parsed.path.startswith("/api/"):
                return True
            if not resolved_auth_token:
                return True
            supplied = self.headers.get("X-OmniMem-Token", "").strip()
            return supplied == resolved_auth_token

        def _send_json(self, data: dict[str, Any], code: int = 200) -> None:
            b = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _send_html(self, html: str, code: int = 200) -> None:
            b = html.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(HTML_PAGE)
                return

            if not self._authorized(parsed):
                self._send_json({"ok": False, "error": "unauthorized"}, 401)
                return

            if parsed.path == "/api/health":
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/version":
                self._send_json(
                    {
                        "ok": True,
                        "version": OMNIMEM_VERSION,
                        "webui_schema_version": str(daemon_state.get("schema_version", "")),
                    }
                )
                return

            if parsed.path == "/api/config":
                self._send_json(_cfg_to_ui(cfg, cfg_path))
                return

            if parsed.path == "/api/daemon":
                self._send_json({"ok": True, **daemon_state})
                return

            if parsed.path == "/api/fs/cwd":
                self._send_json({"ok": True, "cwd": str(Path.cwd())})
                return

            if parsed.path == "/api/fs/list":
                q = parse_qs(parsed.query)
                raw_path = q.get("path", [""])[0].strip()
                base = Path(raw_path).expanduser() if raw_path else Path.home()
                try:
                    p = base.resolve()
                    if not p.exists() or not p.is_dir():
                        self._send_json({"ok": False, "error": f"not a directory: {p}"}, 400)
                        return
                    items = []
                    for child in sorted(p.iterdir(), key=lambda x: x.name.lower()):
                        if child.is_dir() and not child.name.startswith("."):
                            items.append({"name": child.name, "path": str(child)})
                        if len(items) >= 200:
                            break
                    self._send_json({"ok": True, "path": str(p), "items": items})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/project/defaults":
                self._send_json(
                    {
                        "ok": True,
                        "project_path": "",
                        "project_id": "",
                    }
                )
                return

            if parsed.path == "/api/projects":
                items = _load_projects_registry(str(cfg.get("home", "")))
                for it in items:
                    p = Path(str(it.get("project_path", ""))).expanduser()
                    it["exists"] = p.exists() and p.is_dir()
                items.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
                self._send_json({"ok": True, "items": items})
                return

            if parsed.path == "/api/memories":
                q = parse_qs(parsed.query)
                limit = int(q.get("limit", ["20"])[0])
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                layer = q.get("layer", [""])[0].strip() or None
                query = q.get("query", [""])[0].strip()
                items = find_memories(
                    paths,
                    schema_sql_path,
                    query=query,
                    layer=layer,
                    limit=limit,
                    project_id=project_id,
                    session_id=session_id,
                )
                self._send_json({"ok": True, "items": items})
                return

            if parsed.path == "/api/layer-stats":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                try:
                    with sqlite3.connect(paths.sqlite_path) as conn:
                        where = ""
                        args: list[Any] = []
                        if project_id:
                            where = "WHERE json_extract(scope_json, '$.project_id') = ?"
                            args.append(project_id)
                        if session_id:
                            where = (where + " AND " if where else "WHERE ") + "COALESCE(json_extract(source_json, '$.session_id'), '') = ?"
                            args.append(session_id)
                        rows = conn.execute(
                            f"""
                            SELECT layer, count(*) AS c
                            FROM memories
                            {where}
                            GROUP BY layer
                            ORDER BY layer
                            """,
                            args,
                        ).fetchall()
                    items = [{"layer": r[0], "count": int(r[1])} for r in rows]
                    self._send_json({"ok": True, "project_id": project_id, "session_id": session_id, "items": items})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/governance":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                limit = int(q.get("limit", ["6"])[0])
                p_imp = float(q.get("p_imp", ["0.75"])[0])
                p_conf = float(q.get("p_conf", ["0.65"])[0])
                p_stab = float(q.get("p_stab", ["0.65"])[0])
                p_vol = float(q.get("p_vol", ["0.65"])[0])
                d_vol = float(q.get("d_vol", ["0.75"])[0])
                d_stab = float(q.get("d_stab", ["0.45"])[0])
                d_reuse = int(float(q.get("d_reuse", ["1"])[0]))
                try:
                    with sqlite3.connect(paths.sqlite_path) as conn:
                        conn.row_factory = sqlite3.Row
                        pid_where = ""
                        sid_where = ""
                        args: list[Any] = []
                        if project_id:
                            pid_where = "AND json_extract(scope_json, '$.project_id') = ?"
                            args.append(project_id)
                        if session_id:
                            sid_where = "AND COALESCE(json_extract(source_json, '$.session_id'), '') = ?"
                            args.append(session_id)

                        promote = conn.execute(
                            f"""
                            SELECT id, layer, kind, summary, updated_at,
                                   importance_score, confidence_score, stability_score, reuse_count, volatility_score
                            FROM memories
                            WHERE layer IN ('instant','short')
                              AND importance_score >= ?
                              AND confidence_score >= ?
                              AND stability_score >= ?
                              AND volatility_score <= ?
                              {pid_where}
                              {sid_where}
                            ORDER BY importance_score DESC, stability_score DESC, updated_at DESC
                            LIMIT ?
                            """,
                            (p_imp, p_conf, p_stab, p_vol, *args, limit),
                        ).fetchall()

                        demote = conn.execute(
                            f"""
                            SELECT id, layer, kind, summary, updated_at,
                                   importance_score, confidence_score, stability_score, reuse_count, volatility_score
                            FROM memories
                            WHERE layer = 'long'
                              AND (volatility_score >= ? OR stability_score <= ?)
                              AND reuse_count <= ?
                              {pid_where}
                              {sid_where}
                            ORDER BY volatility_score DESC, stability_score ASC, updated_at DESC
                            LIMIT ?
                            """,
                            (d_vol, d_stab, d_reuse, *args, limit),
                        ).fetchall()

                    def pack(rows):
                        out = []
                        for r in rows:
                            out.append(
                                {
                                    "id": r["id"],
                                    "layer": r["layer"],
                                    "kind": r["kind"],
                                    "summary": r["summary"],
                                    "updated_at": r["updated_at"],
                                    "signals": {
                                        "importance_score": float(r["importance_score"]),
                                        "confidence_score": float(r["confidence_score"]),
                                        "stability_score": float(r["stability_score"]),
                                        "reuse_count": int(r["reuse_count"]),
                                        "volatility_score": float(r["volatility_score"]),
                                    },
                                }
                            )
                        return out

                    self._send_json(
                        {
                            "ok": True,
                            "project_id": project_id,
                            "session_id": session_id,
                            "thresholds": {
                                "p_imp": p_imp,
                                "p_conf": p_conf,
                                "p_stab": p_stab,
                                "p_vol": p_vol,
                                "d_vol": d_vol,
                                "d_stab": d_stab,
                                "d_reuse": d_reuse,
                            },
                            "promote": pack(promote),
                            "demote": pack(demote),
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/timeline":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                limit = int(q.get("limit", ["80"])[0])

                def extract_drift(body_text: str) -> float | None:
                    m = re.search(r"\\bdrift=([0-9]*\\.?[0-9]+)\\b", body_text)
                    if not m:
                        return None
                    try:
                        return float(m.group(1))
                    except Exception:
                        return None

                try:
                    with sqlite3.connect(paths.sqlite_path) as conn:
                        conn.row_factory = sqlite3.Row
                        rows = conn.execute(
                            """
                            SELECT id, layer, kind, summary, updated_at, body_text, source_json, tags_json
                            FROM memories
                            WHERE (? = '' OR json_extract(scope_json, '$.project_id') = ?)
                              AND (? = '' OR COALESCE(json_extract(source_json, '$.session_id'), '') = ?)
                              AND (
                                kind = 'checkpoint'
                                OR EXISTS (SELECT 1 FROM json_each(memories.tags_json) WHERE value IN ('auto:turn','auto:checkpoint','auto:retrieve'))
                              )
                            ORDER BY updated_at DESC
                            LIMIT ?
                            """,
                            (project_id, project_id, session_id, session_id, limit),
                        ).fetchall()

                    items = []
                    for r in rows:
                        src = json.loads(r["source_json"] or "{}")
                        body = r["body_text"] or ""
                        drift = extract_drift(body)
                        switched = ("old_session_id" in body) or ("topic switch" in (r["summary"] or "").lower())
                        items.append(
                            {
                                "id": r["id"],
                                "layer": r["layer"],
                                "kind": r["kind"],
                                "summary": r["summary"],
                                "updated_at": r["updated_at"],
                                "session_id": src.get("session_id", ""),
                                "tool": src.get("tool", ""),
                                "drift": drift,
                                "switched": bool(switched),
                            }
                        )
                    self._send_json({"ok": True, "project_id": project_id, "session_id": session_id, "items": items})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/memory":
                q = parse_qs(parsed.query)
                mem_id = q.get("id", [""])[0]
                if not mem_id:
                    self._send_json({"ok": False, "error": "missing id"}, 400)
                    return
                try:
                    with sqlite3.connect(paths.sqlite_path) as conn:
                        conn.row_factory = sqlite3.Row
                        row = conn.execute(
                            """
                            SELECT id, layer, kind, summary, created_at, updated_at, body_md_path,
                                   tags_json, importance_score, confidence_score, stability_score, reuse_count, volatility_score,
                                   source_json, scope_json
                            FROM memories
                            WHERE id = ?
                            """,
                            (mem_id,),
                        ).fetchone()
                        refs = (
                            conn.execute(
                                "SELECT ref_type, target, note FROM memory_refs WHERE memory_id = ?",
                                (mem_id,),
                            ).fetchall()
                            if row
                            else []
                        )
                    if not row:
                        self._send_json({"ok": False, "error": "not found"}, 404)
                        return

                    md_path = paths.markdown_root / row["body_md_path"]
                    body = md_path.read_text(encoding="utf-8")
                    mem = {
                        "id": row["id"],
                        "layer": row["layer"],
                        "kind": row["kind"],
                        "summary": row["summary"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "body_md_path": row["body_md_path"],
                        "tags": json.loads(row["tags_json"] or "[]"),
                        "signals": {
                            "importance_score": float(row["importance_score"]),
                            "confidence_score": float(row["confidence_score"]),
                            "stability_score": float(row["stability_score"]),
                            "reuse_count": int(row["reuse_count"]),
                            "volatility_score": float(row["volatility_score"]),
                        },
                        "source": json.loads(row["source_json"] or "{}"),
                        "scope": json.loads(row["scope_json"] or "{}"),
                        "refs": [{"type": r["ref_type"], "target": r["target"], "note": r["note"]} for r in refs],
                    }
                    self._send_json({"ok": True, "memory": mem, "body": body})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/events":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                event_type = q.get("event_type", [""])[0].strip()
                limit = int(q.get("limit", ["60"])[0])
                limit = max(1, min(200, limit))
                fetch_limit = max(400, min(2000, limit * 20))
                cache_key = (project_id, session_id, event_type, limit)
                now = time.time()
                with events_cache_lock:
                    hit = events_cache.get(cache_key)
                    if hit and (now - float(hit[0]) <= 2.0):
                        self._send_json(hit[1])
                        return
                try:
                    with sqlite3.connect(paths.sqlite_path) as conn:
                        conn.row_factory = sqlite3.Row
                        args: list[Any] = []
                        where = ""
                        if event_type:
                            where = "WHERE event_type = ?"
                            args.append(event_type)
                        rows = conn.execute(
                            f"""
                            SELECT event_id, event_type, event_time, memory_id, payload_json
                            FROM memory_events
                            {where}
                            ORDER BY event_time DESC
                            LIMIT ?
                            """,
                            (*args, fetch_limit),
                        ).fetchall()

                    items = []
                    for r in rows:
                        try:
                            payload = json.loads(r["payload_json"] or "{}")
                        except Exception:
                            payload = {}
                        env = payload.get("envelope") if isinstance(payload, dict) else None
                        if not isinstance(env, dict):
                            env = {}
                        scope = env.get("scope") if isinstance(env.get("scope"), dict) else {}
                        source = env.get("source") if isinstance(env.get("source"), dict) else {}

                        pid = ""
                        sid = ""
                        if isinstance(payload, dict):
                            pid = str(scope.get("project_id", "") or payload.get("project_id", "") or "").strip()
                            sid = str(source.get("session_id", "") or payload.get("session_id", "") or "").strip()
                        if project_id and pid != project_id:
                            continue
                        if session_id and sid != session_id:
                            continue

                        summary = ""
                        if isinstance(payload, dict):
                            summary = str(payload.get("summary", "") or env.get("summary", "") or "")
                            if not summary and r["event_type"] == "memory.promote":
                                fr = payload.get("from_layer", "")
                                to = payload.get("to_layer", "")
                                summary = f"{fr}->{to}"
                            if not summary and r["event_type"] == "memory.reuse":
                                summary = f"delta={payload.get('delta','')}, count={payload.get('count','')}"
                            if not summary and r["event_type"] == "memory.sync":
                                d2 = payload.get("daemon") or {}
                                if isinstance(d2, dict):
                                    summary = f"ok={d2.get('ok')}, err={d2.get('last_error_kind','')}"

                        items.append(
                            {
                                "event_id": r["event_id"],
                                "event_type": r["event_type"],
                                "event_time": r["event_time"],
                                "memory_id": r["memory_id"],
                                "project_id": pid,
                                "session_id": sid,
                                "summary": summary,
                            }
                        )
                        if len(items) >= limit:
                            break

                    out = {
                        "ok": True,
                        "project_id": project_id,
                        "session_id": session_id,
                        "event_type": event_type,
                        "items": items,
                    }
                    with events_cache_lock:
                        events_cache[cache_key] = (now, out)
                    self._send_json(out)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/event":
                q = parse_qs(parsed.query)
                event_id = q.get("event_id", [""])[0].strip()
                if not event_id:
                    self._send_json({"ok": False, "error": "missing event_id"}, 400)
                    return
                try:
                    with sqlite3.connect(paths.sqlite_path) as conn:
                        conn.row_factory = sqlite3.Row
                        r = conn.execute(
                            """
                            SELECT event_id, event_type, event_time, memory_id, payload_json
                            FROM memory_events
                            WHERE event_id = ?
                            """,
                            (event_id,),
                        ).fetchone()
                    if not r:
                        self._send_json({"ok": False, "error": "not found"}, 404)
                        return
                    try:
                        payload = json.loads(r["payload_json"] or "{}")
                    except Exception:
                        payload = {}
                    self._send_json(
                        {
                            "ok": True,
                            "item": {
                                "event_id": r["event_id"],
                                "event_type": r["event_type"],
                                "event_time": r["event_time"],
                                "memory_id": r["memory_id"],
                                "payload": payload,
                            },
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/event-stats":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                days = int(float(q.get("days", ["14"])[0]))
                limit = int(float(q.get("limit", ["8000"])[0]))
                days = max(1, min(60, days))
                limit = max(200, min(20000, limit))
                cache_key = (project_id, session_id, days)
                now = time.time()
                with event_stats_lock:
                    hit = event_stats_cache.get(cache_key)
                    if hit and (now - float(hit[0]) <= 3.0):
                        self._send_json(hit[1])
                        return
                try:
                    with sqlite3.connect(paths.sqlite_path) as conn:
                        conn.row_factory = sqlite3.Row
                        rows = conn.execute(
                            """
                            SELECT event_type, event_time, payload_json
                            FROM memory_events
                            ORDER BY event_time DESC
                            LIMIT ?
                            """,
                            (limit,),
                        ).fetchall()

                    # Aggregate in Python because memory_events doesn't store project/session columns.
                    type_counts: dict[str, int] = {}
                    day_counts: dict[str, int] = {}
                    total = 0
                    day_allow: set[str] | None = None
                    # Only keep last N days keys if present; compute by seen days.
                    seen_days: list[str] = []

                    def accept_event(payload: dict[str, Any]) -> tuple[str, str]:
                        env = payload.get("envelope") if isinstance(payload, dict) else None
                        if not isinstance(env, dict):
                            env = {}
                        scope = env.get("scope") if isinstance(env.get("scope"), dict) else {}
                        source = env.get("source") if isinstance(env.get("source"), dict) else {}
                        pid = str(scope.get("project_id", "") or payload.get("project_id", "") or "").strip()
                        sid = str(source.get("session_id", "") or payload.get("session_id", "") or "").strip()
                        return pid, sid

                    for r in rows:
                        et = str(r["event_type"] or "")
                        ts = str(r["event_time"] or "")
                        day = ts[:10] if len(ts) >= 10 else ""
                        if not day:
                            continue
                        if day_allow is None:
                            if day not in seen_days:
                                seen_days.append(day)
                            if len(seen_days) > days:
                                day_allow = set(seen_days[:days])
                        if day_allow is not None and day not in day_allow:
                            continue

                        try:
                            payload = json.loads(r["payload_json"] or "{}")
                        except Exception:
                            payload = {}
                        pid, sid = accept_event(payload if isinstance(payload, dict) else {})
                        if project_id and pid != project_id:
                            continue
                        if session_id and sid != session_id:
                            continue

                    total += 1
                    type_counts[et] = type_counts.get(et, 0) + 1
                    day_counts[day] = day_counts.get(day, 0) + 1

                    types = [{"event_type": k, "count": int(v)} for k, v in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)]
                    days_out = [{"day": k, "count": int(v)} for k, v in sorted(day_counts.items(), key=lambda x: x[0])]
                    out = {
                        "ok": True,
                        "project_id": project_id,
                        "session_id": session_id,
                        "total": total,
                        "types": types,
                        "days": days_out,
                    }
                    with event_stats_lock:
                        event_stats_cache[cache_key] = (now, out)
                    self._send_json(out)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/sessions":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                limit = int(q.get("limit", ["20"])[0])

                def extract_drift(body_text: str) -> float | None:
                    m = re.search(r"\\bdrift=([0-9]*\\.?[0-9]+)\\b", body_text)
                    if not m:
                        return None
                    try:
                        return float(m.group(1))
                    except Exception:
                        return None

                try:
                    with sqlite3.connect(paths.sqlite_path) as conn:
                        conn.row_factory = sqlite3.Row
                        rows = conn.execute(
                            """
                            SELECT id, kind, summary, updated_at, body_text, source_json, scope_json, tags_json
                            FROM memories
                            WHERE (? = '' OR json_extract(scope_json, '$.project_id') = ?)
                              AND (
                                kind IN ('checkpoint','retrieve')
                                OR EXISTS (SELECT 1 FROM json_each(memories.tags_json) WHERE value IN ('auto:turn','auto:checkpoint','auto:retrieve'))
                              )
                            ORDER BY updated_at DESC
                            LIMIT 2000
                            """,
                            (project_id, project_id),
                        ).fetchall()

                    stats: dict[str, dict[str, Any]] = {}
                    for r in rows:
                        src = json.loads(r["source_json"] or "{}")
                        sid = (src.get("session_id") or "").strip() or "session-unknown"
                        st = stats.get(sid)
                        if st is None:
                            st = {
                                "session_id": sid,
                                "last_updated_at": r["updated_at"],
                                "turns": 0,
                                "retrieves": 0,
                                "checkpoints": 0,
                                "switches": 0,
                                "_drift_sum": 0.0,
                                "_drift_n": 0,
                            }
                            stats[sid] = st
                        if r["updated_at"] and str(r["updated_at"]) > str(st["last_updated_at"]):
                            st["last_updated_at"] = r["updated_at"]

                        body = r["body_text"] or ""
                        drift = extract_drift(body)
                        if drift is not None:
                            st["_drift_sum"] += float(drift)
                            st["_drift_n"] += 1

                        kind = (r["kind"] or "").lower()
                        tags = []
                        try:
                            tags = json.loads(r["tags_json"] or "[]")
                        except Exception:
                            tags = []
                        tags_set = set(str(t) for t in tags)
                        if kind == "retrieve" or "auto:retrieve" in tags_set:
                            st["retrieves"] += 1
                        if kind == "checkpoint" or "auto:checkpoint" in tags_set:
                            st["checkpoints"] += 1
                        if "auto:turn" in tags_set:
                            st["turns"] += 1
                        if "old_session_id" in body or "topic switch" in (r["summary"] or "").lower():
                            st["switches"] += 1

                    items = []
                    for sid, st in stats.items():
                        dn = int(st.pop("_drift_n", 0))
                        ds = float(st.pop("_drift_sum", 0.0))
                        st["avg_drift"] = (ds / dn) if dn > 0 else None
                        items.append(st)
                    items.sort(key=lambda x: str(x.get("last_updated_at", "")), reverse=True)
                    self._send_json({"ok": True, "project_id": project_id, "items": items[: max(1, limit)]})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/analytics":
                q = parse_qs(parsed.query)
                project_id = q.get("project_id", [""])[0].strip()
                session_id = q.get("session_id", [""])[0].strip()
                try:
                    with sqlite3.connect(paths.sqlite_path) as conn:
                        conn.row_factory = sqlite3.Row
                        where = ""
                        args: list[Any] = []
                        if project_id:
                            where = "WHERE json_extract(scope_json, '$.project_id') = ?"
                            args.append(project_id)
                        if session_id:
                            where = (where + " AND " if where else "WHERE ") + "COALESCE(json_extract(source_json, '$.session_id'), '') = ?"
                            args.append(session_id)

                        layers = conn.execute(
                            f"SELECT layer, count(*) AS c FROM memories {where} GROUP BY layer ORDER BY layer",
                            args,
                        ).fetchall()
                        kinds = conn.execute(
                            f"SELECT kind, count(*) AS c FROM memories {where} GROUP BY kind ORDER BY c DESC",
                            args,
                        ).fetchall()
                        activity = conn.execute(
                            f"""
                            SELECT substr(created_at,1,10) AS day, count(*) AS c
                            FROM memories
                            {where}
                            GROUP BY substr(created_at,1,10)
                            ORDER BY day DESC
                            LIMIT 14
                            """,
                            args,
                        ).fetchall()
                        tags = conn.execute(
                            f"""
                            SELECT value AS tag, count(*) AS c
                            FROM memories, json_each(memories.tags_json)
                            {where}
                            GROUP BY value
                            ORDER BY c DESC
                            LIMIT 20
                            """,
                            args,
                        ).fetchall()

                        chk_where = "WHERE kind='checkpoint'"
                        chk_args: list[Any] = []
                        if project_id:
                            chk_where += " AND json_extract(scope_json, '$.project_id') = ?"
                            chk_args.append(project_id)
                        if session_id:
                            chk_where += " AND COALESCE(json_extract(source_json, '$.session_id'), '') = ?"
                            chk_args.append(session_id)
                        checkpoints = conn.execute(
                            f"""
                            SELECT id, summary, updated_at
                            FROM memories
                            {chk_where}
                            ORDER BY updated_at DESC
                            LIMIT 6
                            """,
                            chk_args,
                        ).fetchall()

                    act_items = [{"day": r["day"], "count": int(r["c"])} for r in activity]
                    act_max = max([x["count"] for x in act_items], default=0)
                    self._send_json(
                        {
                            "ok": True,
                            "project_id": project_id,
                            "session_id": session_id,
                            "layers": [{"layer": r["layer"], "count": int(r["c"])} for r in layers],
                            "kinds": [{"kind": r["kind"], "count": int(r["c"])} for r in kinds],
                            "activity": act_items,
                            "activity_max": act_max,
                            "tags": [{"tag": r["tag"], "count": int(r["c"])} for r in tags],
                            "checkpoints": [dict(r) for r in checkpoints],
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            self._send_json({"ok": False, "error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if not self._authorized(parsed):
                self._send_json({"ok": False, "error": "unauthorized"}, 401)
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")

            if parsed.path == "/api/config":
                cfg["home"] = data.get("home", cfg.get("home", ""))
                cfg.setdefault("storage", {})
                cfg["storage"]["markdown"] = data.get("markdown", cfg["storage"].get("markdown", ""))
                cfg["storage"]["jsonl"] = data.get("jsonl", cfg["storage"].get("jsonl", ""))
                cfg["storage"]["sqlite"] = data.get("sqlite", cfg["storage"].get("sqlite", ""))
                cfg.setdefault("sync", {}).setdefault("github", {})
                cfg["sync"]["github"]["remote_name"] = data.get("remote_name", "origin")
                cfg["sync"]["github"]["remote_url"] = data.get("remote_url", "")
                cfg["sync"]["github"]["branch"] = data.get("branch", "main")
                try:
                    save_config(cfg_path, cfg)
                    nonlocal paths
                    paths = resolve_paths(cfg)
                    ensure_storage(paths, schema_sql_path)
                    was_initialized = daemon_state.get("initialized", False)
                    daemon_state["initialized"] = True
                    if not was_initialized and enable_daemon:
                        daemon_state["enabled"] = not daemon_state.get("manually_disabled", False)
                    self._send_json({"ok": True})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/sync":
                if not daemon_state.get("initialized", False):
                    self._send_json({"ok": False, "error": "config not initialized; save config first"}, 400)
                    return
                mode = data.get("mode", "github-status")
                gh = cfg.get("sync", {}).get("github", {})
                try:
                    out = sync_runner(
                        paths,
                        schema_sql_path,
                        mode,
                        remote_name=gh.get("remote_name", "origin"),
                        branch=gh.get("branch", "main"),
                        remote_url=gh.get("remote_url"),
                        commit_message="chore(memory): sync from webui",
                    )
                    self._send_json(out)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/daemon/toggle":
                desired = bool(data.get("enabled", True))
                daemon_state["manually_disabled"] = not desired
                daemon_state["enabled"] = bool(desired and daemon_state.get("initialized", False))
                self._send_json(
                    {
                        "ok": True,
                        "enabled": daemon_state["enabled"],
                        "initialized": daemon_state["initialized"],
                        "running": daemon_state["running"],
                        "last_result": daemon_state.get("last_result", {}),
                    }
                )
                return

            if parsed.path == "/api/maintenance/decay":
                try:
                    project_id = str(data.get("project_id", "")).strip()
                    days = int(data.get("days", 14))
                    limit = int(data.get("limit", 200))
                    dry_run = bool(data.get("dry_run", True))
                    layers = data.get("layers")
                    if layers is None:
                        raw = str(data.get("layers_csv", "")).strip()
                        layers = [x.strip() for x in raw.split(",") if x.strip()] if raw else None
                    if layers is not None and (not isinstance(layers, list) or not all(isinstance(x, (str, int, float)) for x in layers)):
                        self._send_json({"ok": False, "error": "layers must be a list of strings"}, 400)
                        return
                    if layers is not None:
                        layers = [str(x).strip() for x in layers if str(x).strip()]
                    out = apply_decay(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        days=days,
                        limit=limit,
                        project_id=project_id,
                        layers=layers,
                        dry_run=dry_run,
                        tool="webui",
                        session_id="webui-session",
                    )
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/project/attach":
                try:
                    project_path = str(data.get("project_path", "")).strip()
                    project_id = str(data.get("project_id", "")).strip()
                    out = _attach_project_in_webui(
                        project_path=project_path,
                        project_id=project_id,
                        cfg_home=str(cfg.get("home", "")).strip(),
                    )
                    if out.get("ok"):
                        pid = str(out.get("project_id", "")).strip() or "global"
                        _register_project(str(cfg.get("home", "")), pid, str(out.get("project_path", project_path)))
                        write_memory(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            layer="short",
                            kind="summary",
                            summary=f"Project attached: {pid}",
                            body=(
                                "Project integration completed via WebUI.\n\n"
                                f"- project_id: {pid}\n"
                                f"- project_path: {project_path}\n"
                            ),
                            tags=[f"project:{pid}", "integration:webui"],
                            refs=[],
                            cred_refs=[],
                            tool="webui",
                            account="default",
                            device="local",
                            session_id="webui-session",
                            project_id=pid,
                            workspace=project_path,
                            importance=0.7,
                            confidence=0.9,
                            stability=0.8,
                            reuse_count=0,
                            volatility=0.2,
                            event_type="memory.write",
                        )
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/project/detach":
                try:
                    proj_path = str(data.get("project_path", "")).strip()
                    out = _detach_project_in_webui(proj_path)
                    if out.get("ok"):
                        _unregister_project(str(cfg.get("home", "")), proj_path)
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/memory/move":
                try:
                    mem_id = str(data.get("id", "")).strip()
                    layer = str(data.get("layer", "")).strip()
                    if not mem_id or not layer:
                        self._send_json({"ok": False, "error": "id and layer are required"}, 400)
                        return
                    out = move_memory_layer(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        memory_id=mem_id,
                        new_layer=layer,
                        tool="webui",
                        account="default",
                        device="local",
                        session_id="webui-session",
                    )
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/memory/update":
                try:
                    mem_id = str(data.get("id", "")).strip()
                    summary = str(data.get("summary", "")).strip()
                    body = str(data.get("body", ""))
                    raw_tags = data.get("tags")
                    if raw_tags is None:
                        raw = str(data.get("tags_csv", "") or "")
                        tags = [x.strip() for x in raw.split(",") if x.strip()]
                    else:
                        if not isinstance(raw_tags, list):
                            self._send_json({"ok": False, "error": "tags must be a list of strings"}, 400)
                            return
                        tags = [str(x).strip() for x in raw_tags if str(x).strip()]
                    if not mem_id:
                        self._send_json({"ok": False, "error": "id is required"}, 400)
                        return
                    out = update_memory_content(
                        paths=paths,
                        schema_sql_path=schema_sql_path,
                        memory_id=mem_id,
                        summary=summary,
                        body=body,
                        tags=tags,
                        tool="webui",
                        account="default",
                        device="local",
                        session_id="webui-session",
                    )
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/session/archive":
                try:
                    project_id = str(data.get("project_id", "")).strip()
                    session_id = str(data.get("session_id", "")).strip()
                    to_layer = str(data.get("to_layer", "archive")).strip() or "archive"
                    from_layers = data.get("from_layers") or ["instant", "short"]
                    limit = int(data.get("limit", 400))
                    if not session_id:
                        self._send_json({"ok": False, "error": "session_id is required"}, 400)
                        return
                    if to_layer not in LAYER_SET:
                        self._send_json({"ok": False, "error": f"invalid to_layer: {to_layer}"}, 400)
                        return
                    if not isinstance(from_layers, list) or not from_layers:
                        self._send_json({"ok": False, "error": "from_layers must be a non-empty list"}, 400)
                        return
                    from_layers = [str(x).strip() for x in from_layers if str(x).strip()]
                    if any(x not in LAYER_SET for x in from_layers):
                        self._send_json({"ok": False, "error": "invalid from_layers"}, 400)
                        return
                    limit = max(1, min(2000, limit))

                    placeholders = ",".join(["?"] * len(from_layers))
                    ids: list[str] = []
                    with sqlite3.connect(paths.sqlite_path) as conn:
                        conn.row_factory = sqlite3.Row
                        ids = [
                            str(r["id"])
                            for r in conn.execute(
                                f"""
                                SELECT id
                                FROM memories
                                WHERE layer IN ({placeholders})
                                  AND (? = '' OR json_extract(scope_json, '$.project_id') = ?)
                                  AND COALESCE(json_extract(source_json, '$.session_id'), '') = ?
                                ORDER BY updated_at DESC
                                LIMIT ?
                                """,
                                (*from_layers, project_id, project_id, session_id, limit),
                            ).fetchall()
                        ]

                    moved = 0
                    failed: list[str] = []
                    for mid in ids:
                        out = move_memory_layer(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            memory_id=mid,
                            new_layer=to_layer,
                            tool="webui",
                            account="default",
                            device="local",
                            session_id="webui-session",
                        )
                        if out.get("ok"):
                            moved += 1
                        else:
                            failed.append(mid)

                    # Governance audit record (stored as a memory so it shows up in UI and sync).
                    try:
                        write_memory(
                            paths=paths,
                            schema_sql_path=schema_sql_path,
                            layer="archive",
	                            kind="summary",
	                            summary=f"Session archived: {session_id[:12]}… ({moved}/{len(ids)})",
	                            body=(
	                                "Session archive executed via WebUI.\n\n"
	                                f"- project_id: {project_id or '(all)'}\n"
	                                f"- session_id: {session_id}\n"
	                                f"- from_layers: {', '.join(from_layers)}\n"
	                                f"- to_layer: {to_layer}\n"
	                                f"- requested: {len(ids)}\n"
	                                f"- moved: {moved}\n"
	                                f"- failed_first20: {failed[:20]}\n"
	                            ),
                            tags=[
                                "governance:session-archive",
                                f"session:{session_id}",
                                *([f"project:{project_id}"] if project_id else []),
                            ],
                            refs=[],
                            cred_refs=[],
                            tool="webui",
                            account="default",
                            device="local",
                            session_id="webui-session",
                            project_id=project_id or "global",
                            workspace="",
                            importance=0.55,
                            confidence=0.9,
                            stability=0.8,
                            reuse_count=0,
                            volatility=0.15,
                            event_type="memory.write",
                        )
                    except Exception:
                        pass

                    self._send_json(
                        {
                            "ok": True,
                            "project_id": project_id,
                            "session_id": session_id,
                            "from_layers": from_layers,
                            "to_layer": to_layer,
                            "moved": moved,
                            "requested": len(ids),
                            "failed": failed[:20],
                        }
                    )
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            self._send_json({"ok": False, "error": "not found"}, 404)

    server = ThreadingHTTPServer((host, port), Handler)
    print(
        f"WebUI running on http://{host}:{port} "
        f"(daemon={'on' if enable_daemon else 'off'}, auth={'on' if resolved_auth_token else 'off'})"
    )
    try:
        server.serve_forever()
    finally:
        stop_event.set()
        if daemon_thread is not None:
            daemon_thread.join(timeout=1.5)
