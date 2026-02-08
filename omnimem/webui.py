from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .core import ensure_storage, find_memories, resolve_paths, save_config


HTML_PAGE = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>OmniMem WebUI</title>
  <style>
    :root { --bg:#f3f4f6; --card:#ffffff; --ink:#0f172a; --muted:#475569; --line:#e2e8f0; --accent:#0f766e; --tab:#e6fffb; }
    body { margin:0; font-family: 'IBM Plex Sans', 'Helvetica Neue', sans-serif; background: radial-gradient(circle at top right,#ecfeff,#f8fafc 50%,#f3f4f6); color:var(--ink); }
    .wrap { max-width: 1080px; margin: 22px auto; padding: 0 16px 36px; }
    .hero { padding: 18px; border:1px solid var(--line); background:var(--card); border-radius: 14px; }
    h1 { margin: 0 0 6px; font-size: 28px; letter-spacing: .2px; }
    .small { font-size:12px; color:var(--muted); }
    .hero-head { display:flex; justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap; }
    .lang { border:1px solid var(--line); border-radius:10px; padding:6px 8px; background:#fff; }
    .tabs { display:flex; gap:8px; margin-top:14px; flex-wrap:wrap; }
    .tab-btn { border:1px solid var(--line); background:#fff; color:#0f172a; border-radius: 10px; padding:8px 12px; cursor:pointer; }
    .tab-btn.active { background:var(--tab); border-color:#99f6e4; color:#115e59; }
    .panel { display:none; margin-top:14px; }
    .panel.active { display:block; }
    .grid { display:grid; grid-template-columns: 1fr 1fr; gap:16px; }
    .card { border:1px solid var(--line); background:var(--card); border-radius: 14px; padding:16px; box-shadow: 0 4px 16px rgba(15,23,42,.03); }
    .wide { grid-column: 1 / -1; }
    label { display:block; font-size:12px; margin-top:8px; color:var(--muted); }
    input { width:100%; box-sizing:border-box; border:1px solid #cbd5e1; background:#fff; border-radius:10px; padding:9px 10px; margin-top:4px; }
    button { border:0; background:var(--accent); color:#fff; border-radius:10px; padding:10px 14px; margin-top:10px; cursor:pointer; }
    .row-btn { display:flex; gap:10px; flex-wrap:wrap; }
    table { width:100%; border-collapse: collapse; font-size: 14px; }
    th, td { padding:8px; border-bottom:1px solid var(--line); text-align:left; }
    .ok { color:#047857; }
    .err { color:#b91c1c; }
    .warn { color:#92400e; }
    @media (max-width: 920px) { .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"hero\">
      <div class=\"hero-head\">
        <div>
          <h1 data-i18n=\"title\">OmniMem WebUI</h1>
          <div class=\"small\" data-i18n=\"subtitle\">Simple mode: Status & Actions / Configuration / Memory</div>
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
        </div>
      </div>
      <div id=\"status\" class=\"small\"></div>
      <div id=\"daemonState\" class=\"small\"></div>
      <div class=\"tabs\">
        <button class=\"tab-btn active\" data-tab=\"statusTab\" data-i18n=\"tab_status\">Status & Actions</button>
        <button class=\"tab-btn\" data-tab=\"configTab\" data-i18n=\"tab_config\">Configuration</button>
        <button class=\"tab-btn\" data-tab=\"projectTab\" data-i18n=\"tab_project\">Project Integration</button>
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
          </div>
          <pre id=\"syncOut\" class=\"small\"></pre>
        </div>
      </div>
    </div>

    <div id=\"configTab\" class=\"panel\">
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

    <div id=\"projectTab\" class=\"panel\">
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
      </div>
    </div>

    <div id=\"memoryTab\" class=\"panel\">
      <div class=\"grid\">
        <div class=\"card wide\">
          <h3 data-i18n=\"mem_recent\">Recent Memories</h3>
          <div class=\"small\" data-i18n=\"mem_hint\">Click an ID to open full content</div>
          <table>
            <thead>
              <tr>
                <th data-i18n=\"th_id\">ID</th>
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

  <script>
    const I18N = {
      en: {
        title: 'OmniMem WebUI', subtitle: 'Simple mode: Status & Actions / Configuration / Memory', language: 'Language',
        tab_status: 'Status & Actions', tab_config: 'Configuration', tab_project: 'Project Integration', tab_memory: 'Memory',
        system_status: 'System Status', actions: 'Actions',
        btn_status: 'Check Sync Status', btn_bootstrap: 'Bootstrap Device Sync', btn_push: 'Push', btn_pull: 'Pull',
        btn_daemon_on: 'Enable Daemon', btn_daemon_off: 'Disable Daemon',
        config_title: 'Configuration', cfg_path: 'Config Path', cfg_home: 'Home', cfg_markdown: 'Markdown Path', cfg_jsonl: 'JSONL Path', cfg_sqlite: 'SQLite Path', cfg_remote_name: 'Git Remote Name', cfg_remote_url: 'Git Remote URL', cfg_branch: 'Git Branch', btn_save: 'Save Configuration',
        mem_recent: 'Recent Memories', mem_hint: 'Click an ID to open full content', mem_content: 'Memory Content',
        th_id: 'ID', th_layer: 'Layer', th_kind: 'Kind', th_summary: 'Summary', th_updated: 'Updated At',
        project_title: 'Project Integration', project_path: 'Project Path', project_id: 'Project ID',
        btn_browse_project: 'Browse Directory', btn_use_cwd: 'Use Server CWD',
        browser_title: 'Directory Browser', btn_browser_up: 'Up', btn_browser_select: 'Select This Directory', btn_browser_close: 'Close',
        btn_project_attach: 'Attach Project + Install Agent Rules', btn_project_detach: 'Detach Project',
        project_hint: 'Attach will create .omnimem files and inject managed memory protocol blocks into AGENTS.md / CLAUDE.md / .cursorrules.',
        cfg_saved: 'Configuration saved', cfg_failed: 'Save failed',
        project_attach_ok: 'Project attached', project_detach_ok: 'Project detached', project_failed: 'Project action failed',
        init_ok: 'Config state: initialized', init_hint_ok: 'Daemon runs quasi-realtime sync in background (can be disabled).',
        init_missing: 'Config state: not initialized (save configuration first)', init_hint_missing: 'Daemon is disabled until configuration is initialized.',
        daemon_state: (d) => `Daemon: ${d.running ? 'running' : 'stopped'}, enabled=${d.enabled}, initialized=${d.initialized}`
      },
      zh: {
        title: 'OmniMem 网页控制台', subtitle: '简洁模式：状态与动作 / 配置 / 记忆', language: '语言',
        tab_status: '状态与动作', tab_config: '配置', tab_memory: '记忆',
        system_status: '系统状态', actions: '动作',
        btn_status: '检查同步状态', btn_bootstrap: '首次设备对齐', btn_push: '推送', btn_pull: '拉取',
        btn_daemon_on: '开启守护', btn_daemon_off: '关闭守护',
        config_title: '配置', cfg_path: '配置路径', cfg_home: '主目录', cfg_markdown: 'Markdown 路径', cfg_jsonl: 'JSONL 路径', cfg_sqlite: 'SQLite 路径', cfg_remote_name: 'Git 远端名', cfg_remote_url: 'Git 远端 URL', cfg_branch: 'Git 分支', btn_save: '保存配置',
        mem_recent: '最近记忆', mem_hint: '点击 ID 查看正文', mem_content: '记忆正文',
        th_id: 'ID', th_layer: '层级', th_kind: '类型', th_summary: '摘要', th_updated: '更新时间',
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
    let currentLang = safeGetLang();
    if (!I18N[currentLang]) currentLang = 'en';
    let daemonCache = { running:false, enabled:false, initialized:false };
    let browserPath = '';

    function t(key) {
      const dict = I18N[currentLang] || I18N.en;
      return dict[key] || I18N.en[key] || key;
    }

    function applyI18n() {
      document.documentElement.lang = currentLang;
      document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        el.textContent = t(key);
      });
      document.getElementById('langSelect').value = currentLang;
      renderDaemonState();
    }

    async function jget(url) { const r = await fetch(url); return await r.json(); }
    async function jpost(url, obj) { const r = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(obj)}); return await r.json(); }

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
      document.getElementById('daemonState').textContent = fn(daemonCache);
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
      const d = await jget('/api/memories?limit=20');
      const b = document.getElementById('memBody');
      b.innerHTML = '';
      (d.items || []).forEach(x => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td><a href=\"#\" data-id=\"${x.id}\">${x.id.slice(0,10)}...</a></td><td>${x.layer}</td><td>${x.kind}</td><td>${x.summary}</td><td>${x.updated_at}</td>`;
        tr.querySelector('a').onclick = async (e) => {
          e.preventDefault();
          const m = await jget('/api/memory?id=' + encodeURIComponent(x.id));
          document.getElementById('memView').textContent = m.body || m.error || '';
        };
        b.appendChild(tr);
      });
    }

    document.getElementById('cfgForm').onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target;
      const payload = {};
      for (const k of ['home','markdown','jsonl','sqlite','remote_name','remote_url','branch']) payload[k] = f.elements[k].value;
      const d = await jpost('/api/config', payload);
      document.getElementById('status').innerHTML = d.ok ? `<span class=\"ok\">${t('cfg_saved')}</span>` : `<span class=\"err\">${t('cfg_failed')}</span>`;
      await loadCfg();
      await loadDaemon();
    };

    async function runSync(mode) {
      const d = await jpost('/api/sync', {mode});
      document.getElementById('syncOut').textContent = JSON.stringify(d, null, 2);
      await loadMem();
      await loadDaemon();
    }

    async function loadDaemon() {
      const d = await jget('/api/daemon');
      daemonCache = d;
      renderDaemonState();
    }

    async function toggleDaemon(enabled) {
      await jpost('/api/daemon/toggle', {enabled});
      await loadDaemon();
    }

    async function attachProject() {
      const project_path = document.getElementById('projectPath').value.trim();
      const project_id = document.getElementById('projectId').value.trim();
      const out = document.getElementById('projectOut');
      const d = await jpost('/api/project/attach', {project_path, project_id});
      out.textContent = JSON.stringify(d, null, 2);
      document.getElementById('status').innerHTML = d.ok ? `<span class=\"ok\">${t('project_attach_ok')}</span>` : `<span class=\"err\">${t('project_failed')}</span>`;
    }

    async function detachProject() {
      const project_path = document.getElementById('projectPath').value.trim();
      const out = document.getElementById('projectOut');
      const d = await jpost('/api/project/detach', {project_path});
      out.textContent = JSON.stringify(d, null, 2);
      document.getElementById('status').innerHTML = d.ok ? `<span class=\"ok\">${t('project_detach_ok')}</span>` : `<span class=\"err\">${t('project_failed')}</span>`;
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

    document.getElementById('langSelect').onchange = (e) => {
      currentLang = e.target.value;
      safeSetLang(currentLang);
      applyI18n();
      loadCfg();
    };

    function bindActions() {
      document.getElementById('btnSyncStatus').onclick = () => runSync('github-status');
      document.getElementById('btnSyncBootstrap').onclick = () => runSync('github-bootstrap');
      document.getElementById('btnSyncPush').onclick = () => runSync('github-push');
      document.getElementById('btnSyncPull').onclick = () => runSync('github-pull');
      document.getElementById('btnDaemonOn').onclick = () => toggleDaemon(true);
      document.getElementById('btnDaemonOff').onclick = () => toggleDaemon(false);
      document.getElementById('btnProjectAttach').onclick = () => attachProject();
      document.getElementById('btnProjectDetach').onclick = () => detachProject();
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
    }

    window.addEventListener('error', (e) => {
      const s = document.getElementById('status');
      if (s) s.innerHTML = `<span class=\"err\">UI error: ${e.message}</span>`;
    });

    bindActions();
    bindTabs();
    applyI18n();
    loadCfg();
    loadMem();
    loadDaemon();
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
) -> None:
    paths = resolve_paths(cfg)
    ensure_storage(paths, schema_sql_path)
    daemon_state: dict[str, Any] = {
        "initialized": cfg_path.exists(),
        "enabled": bool(enable_daemon and cfg_path.exists()),
        "manually_disabled": False,
        "running": False,
        "last_result": {},
        "scan_interval": daemon_scan_interval,
        "pull_interval": daemon_pull_interval,
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
                gh = cfg.get("sync", {}).get("github", {})
                result = daemon_runner(
                    paths=paths,
                    schema_sql_path=schema_sql_path,
                    remote_name=gh.get("remote_name", "origin"),
                    branch=gh.get("branch", "main"),
                    remote_url=gh.get("remote_url"),
                    scan_interval=daemon_scan_interval,
                    pull_interval=daemon_pull_interval,
                    once=True,
                )
                daemon_state["last_result"] = result
            except Exception as exc:  # pragma: no cover
                daemon_state["last_result"] = {"ok": False, "error": str(exc)}
            time.sleep(max(1, daemon_scan_interval))
        daemon_state["running"] = False

    daemon_thread: threading.Thread | None = None
    if enable_daemon and daemon_runner is not None:
        daemon_thread = threading.Thread(target=daemon_loop, name="omnimem-daemon", daemon=True)
        daemon_thread.start()

    class Handler(BaseHTTPRequestHandler):
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

            if parsed.path == "/api/memories":
                q = parse_qs(parsed.query)
                limit = int(q.get("limit", ["20"])[0])
                items = find_memories(paths, schema_sql_path, query="", layer=None, limit=limit)
                self._send_json({"ok": True, "items": items})
                return

            if parsed.path == "/api/memory":
                q = parse_qs(parsed.query)
                mem_id = q.get("id", [""])[0]
                if not mem_id:
                    self._send_json({"ok": False, "error": "missing id"}, 400)
                    return
                try:
                    with sqlite3.connect(paths.sqlite_path) as conn:
                        row = conn.execute(
                            "SELECT body_md_path FROM memories WHERE id = ?",
                            (mem_id,),
                        ).fetchone()
                    if not row:
                        self._send_json({"ok": False, "error": "not found"}, 404)
                        return
                    md_path = paths.markdown_root / row[0]
                    self._send_json({"ok": True, "body": md_path.read_text(encoding="utf-8")})
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            self._send_json({"ok": False, "error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
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

            if parsed.path == "/api/project/attach":
                try:
                    out = _attach_project_in_webui(
                        project_path=str(data.get("project_path", "")).strip(),
                        project_id=str(data.get("project_id", "")).strip(),
                        cfg_home=str(cfg.get("home", "")).strip(),
                    )
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            if parsed.path == "/api/project/detach":
                try:
                    out = _detach_project_in_webui(str(data.get("project_path", "")).strip())
                    self._send_json(out, 200 if out.get("ok") else 400)
                except Exception as exc:  # pragma: no cover
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            self._send_json({"ok": False, "error": "not found"}, 404)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"WebUI running on http://{host}:{port} (daemon={'on' if enable_daemon else 'off'})")
    try:
        server.serve_forever()
    finally:
        stop_event.set()
        if daemon_thread is not None:
            daemon_thread.join(timeout=1.5)
