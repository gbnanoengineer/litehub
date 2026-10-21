'use strict';
const { app, BrowserWindow, WebContentsView, Menu, Tray, nativeImage, session, shell, ipcMain,
        desktopCapturer, Notification, nativeTheme } = require('electron');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');

const SIDEBAR = 64;
const DEBUG = process.argv.includes('--tessera-debug');

const GOOGLE = ['google.com', 'gmail.com', 'googleusercontent.com', 'gstatic.com', 'googleapis.com', 'youtube.com'];
// Presets: name, url, accent colour, logo file, domains that stay in-app, keep running in background by default
const PRESETS = {
  whatsapp:  { name: 'WhatsApp',  url: 'https://web.whatsapp.com/',     color: '#25d366', logo: 'whatsapp.svg',  domains: ['whatsapp.com', 'whatsapp.net'], keep: true },
  telegram:  { name: 'Telegram',  url: 'https://web.telegram.org/a/',   color: '#26a5e4', logo: 'telegram.svg',  domains: ['telegram.org'], keep: true },
  slack:     { name: 'Slack',     url: 'https://app.slack.com/client',  color: '#4a154b', logo: 'slack.svg',     domains: ['slack.com', 'slack-edge.com'], keep: true },
  discord:   { name: 'Discord',   url: 'https://discord.com/app',       color: '#5865f2', logo: 'discord.svg',   domains: ['discord.com', 'discordapp.com'], keep: true },
  messenger: { name: 'Messenger', url: 'https://www.messenger.com/',    color: '#0084ff', logo: 'messenger.svg', domains: ['messenger.com', 'facebook.com'], keep: true },
  instagram: { name: 'Instagram', url: 'https://www.instagram.com/',    color: '#e4405f', logo: 'instagram.svg', domains: ['instagram.com'], keep: false },
  gmail:     { name: 'Gmail',     url: 'https://mail.google.com/',      color: '#ea4335', logo: 'gmail.svg',      domains: GOOGLE, keep: true,  group: 'google' },
  gmeet:     { name: 'Google Meet', url: 'https://meet.google.com/',    color: '#00897b', logo: 'googlemeet.svg', domains: GOOGLE, keep: false, group: 'google' },
  gcal:      { name: 'Google Calendar', url: 'https://calendar.google.com/', color: '#4285f4', logo: null,        domains: GOOGLE, keep: false, group: 'google' },
  gdrive:    { name: 'Google Drive', url: 'https://drive.google.com/',  color: '#fbbc04', logo: null,             domains: GOOGLE, keep: false, group: 'google' },
  custom:    { name: 'Custom site', url: 'https://',                    color: '#546e7a', logo: null,            domains: [], keep: false },
};
// sign-in popups that must stay in-app even when they are not the service's own domain
const AUTH_HOSTS = ['accounts.google.com', 'login.microsoftonline.com', 'login.live.com', 'appleid.apple.com',
                    'facebook.com', 'okta.com', 'auth0.com', 'github.com', 'login.microsoft.com'];

const DEFAULTS = {
  services: [],
  closeToTray: true,
  startMinimized: false,
  notifications: true,
  hardwareAcceleration: true,
  hibernateMinutes: 30,       // idle services not set to "keep running" are unloaded; 0 = never
  theme: 'system',            // system | dark | light
  last: null,
};

// ---- chromium flags (before ready)
app.setName('tessera');
app.commandLine.appendSwitch('ozone-platform-hint', 'auto');
app.commandLine.appendSwitch('enable-features', 'WebRTCPipeWireCapturer');
app.commandLine.appendSwitch('disable-features', 'Vulkan');   // Vulkan + Wayland logs a harmless error on some GPUs
if (!DEBUG) app.commandLine.appendSwitch('log-level', '3');

const CHROME_MAJOR = process.versions.chrome.split('.')[0];
const CHROME_UA = `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${CHROME_MAJOR}.0.0.0 Safari/537.36`;
app.userAgentFallback = CHROME_UA;

// ---- config
let cfg = null;
const cfgFile = () => path.join(app.getPath('userData'), 'settings.json');
function readJson(p, d) { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return d; } }
function saveCfg() {
  fs.mkdirSync(path.dirname(cfgFile()), { recursive: true });
  fs.writeFileSync(cfgFile(), JSON.stringify(cfg, null, 2));
}
function makeService(preset, name, url, sess) {
  const p = PRESETS[preset] || PRESETS.custom;
  const n = cfg.services.filter(s => s.preset === preset).length;
  url = url || p.url;
  let domains = p.domains;
  if (preset === 'custom') {
    const host = safeHost(url);
    domains = host ? [host.split('.').slice(-2).join('.')] : [];
  }
  const svc = { id: crypto.randomBytes(4).toString('hex'), preset, name: name || (n ? `${p.name} ${n + 1}` : p.name),
           url, color: p.color, domains, keepAlive: p.keep, notifications: true };
  if (sess) svc.session = sess;
  return svc;
}
function loadCfg() {
  cfg = Object.assign(JSON.parse(JSON.stringify(DEFAULTS)), readJson(cfgFile(), {}));
  if (!cfg.services.length && !fs.existsSync(cfgFile())) {
    // first run: carry over the service list of the old Qt version (logins cannot move; scan the QR/sign in again)
    const old = readJson(path.join(app.getPath('userData'), 'config.json'), null);
    const keep = old && Array.isArray(old.services) ? old.services.filter(s => s.type !== 'mail' && /^https?:/.test(s.url || '')) : [];
    for (const s of keep) {
      cfg.services.push(Object.assign(makeService(PRESETS[s.preset] ? s.preset : 'custom', s.name, s.url), { id: s.id }));
    }
    if (!cfg.services.length) cfg.services.push(makeService('whatsapp'));
    saveCfg();
  }
}
const find = id => cfg.services.find(s => s.id === id);
const sessionKey = s => s.session || s.id;                 // services with the same key share one login (e.g. Google apps)
const partitionOf = s => 'persist:svc-' + sessionKey(s);
function safeHost(u) { try { return new URL(u).hostname; } catch { return ''; } }
const hostMatches = (host, doms) => doms.some(d => host === d || host.endsWith('.' + d));

// ---- state
let win = null, tray = null, ui = null;
let overlay = false;                      // a dialog is open in the UI: hide the service view
const views = new Map();
const wcService = new Map();             // webContents.id -> service id (a session can serve several services)
const svcOf = wc => (wc && find(wcService.get(wc.id))) || null;                  // id -> {view, unread, lastActive, favicon, ses}
let current = null;
app.isQuitting = false;

if (!app.requestSingleInstanceLock()) { app.quit(); process.exit(0); }
app.on('second-instance', () => showWindow());

// ---- sessions
const sessionReady = new WeakSet();
function setupSession(ses) {
  if (sessionReady.has(ses)) return;
  sessionReady.add(ses);
  ses.setUserAgent(CHROME_UA);
  const allowed = new Set(['media', 'clipboard-read', 'clipboard-sanitized-write', 'fullscreen', 'display-capture',
                           'pointerLock', 'notifications', 'mediaKeySystem', 'speaker-selection', 'window-management']);
  const ok = (wc, perm) => {
    if (!allowed.has(perm)) return false;
    if (perm === 'notifications') return cfg.notifications && (svcOf(wc) || {}).notifications !== false;
    return true;
  };
  ses.setPermissionRequestHandler((wc, perm, cb) => cb(ok(wc, perm)));
  ses.setPermissionCheckHandler((wc, perm) => ok(wc, perm));
  // screen sharing: Wayland shows the system portal picker; on X11 the first screen is used
  ses.setDisplayMediaRequestHandler(async (_req, cb) => {
    try {
      const sources = await desktopCapturer.getSources({ types: ['screen', 'window'] });
      cb(sources.length ? { video: sources[0], audio: 'loopback' } : {});
    } catch { cb({}); }
  });
  ses.on('will-download', (_e, item, wc) => {
    const s = svcOf(wc) || { name: 'Tessera' };
    const dir = app.getPath('downloads');
    let target = path.join(dir, item.getFilename());
    const { name, ext } = path.parse(target);
    for (let i = 1; fs.existsSync(target); i++) target = path.join(dir, `${name} (${i})${ext}`);
    item.setSavePath(target);
    item.once('done', (_ev, state) => {
      if (state !== 'completed') return;
      const n = new Notification({ title: 'Download finished', body: `${path.basename(target)} - ${s.name}` });
      n.on('click', () => shell.showItemInFolder(target));
      n.show();
    });
  });
}

function customCss(id) {
  const dir = app.getPath('userData');
  return ['custom.css', path.join('services', id + '.css')].map(f => { try { return fs.readFileSync(path.join(dir, f), 'utf8'); } catch { return ''; } }).join('\n').trim();
}

// ---- service views
function createView(s) {
  const ses = session.fromPartition(partitionOf(s));
  setupSession(ses);
  const view = new WebContentsView({ webPreferences: { session: ses, sandbox: true, contextIsolation: true, spellcheck: false } });
  const wc = view.webContents;
  wcService.set(wc.id, s.id);
  const rec = { view, unread: 0, lastActive: Date.now(), favicon: null };
  views.set(s.id, rec);
  wc.setUserAgent(s.ua || CHROME_UA);

  wc.setWindowOpenHandler(({ url }) => {
    const host = safeHost(url);
    const own = hostMatches(host, s.domains || []) || hostMatches(host, AUTH_HOSTS);
    if (own) return { action: 'allow', overrideBrowserWindowOptions: { parent: win, width: 520, height: 720, autoHideMenuBar: true } };
    if (/^(https?|mailto):/.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  wc.on('page-title-updated', (_e, title) => {
    const m = /^[(\[](\d+)[)\]]/.exec(title) || /\((\d+)\)\s*$/.exec(title) || /^Inbox \((\d+)\)/.exec(title);
    const n = m ? parseInt(m[1], 10) : 0;
    if (n !== rec.unread) { rec.unread = n; pushState(); updateTray(); }
  });
  wc.on('page-favicon-updated', (_e, favs) => { if (favs[0] && favs[0] !== rec.favicon) { rec.favicon = favs[0]; pushState(); } });
  wc.on('dom-ready', () => {
    const css = customCss(s.id);
    if (css) wc.insertCSS(css).catch(() => {});
    wc.setZoomFactor(s.zoom || 1);
  });
  wc.on('did-fail-load', (_e, code, desc, url, isMain) => {
    if (!isMain || code === -3) return;
    const html = `<body style="font:15px sans-serif;background:#1b1d23;color:#ddd;display:grid;place-content:center;text-align:center;height:100vh;margin:0">
      <div><h2>Can't reach ${s.name}</h2><p>${desc}</p><p>Press Ctrl+R to retry.</p></div></body>`;
    wc.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html)).catch(() => {});
  });
  wc.on('context-menu', (_e, p) => {
    const items = [];
    if (p.linkURL) items.push({ label: 'Open link in browser', click: () => shell.openExternal(p.linkURL) },
                              { label: 'Copy link', click: () => require('electron').clipboard.writeText(p.linkURL) }, { type: 'separator' });
    if (p.isEditable) items.push({ role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' });
    else if (p.selectionText) items.push({ role: 'copy' });
    if (p.mediaType === 'image') items.push({ label: 'Save image as…', click: () => wc.downloadURL(p.srcURL) });
    if (DEBUG) items.push({ type: 'separator' }, { label: 'Inspect', click: () => wc.inspectElement(p.x, p.y) });
    if (items.length) Menu.buildFromTemplate(items).popup({ window: win });
  });
  wc.loadURL(s.url, { userAgent: s.ua || CHROME_UA });
  win.contentView.addChildView(view);
  layout();
  return rec;
}

function destroyView(id) {
  const rec = views.get(id);
  if (!rec) return;
  try { win.contentView.removeChildView(rec.view); } catch {}
  try { wcService.delete(rec.view.webContents.id); rec.view.webContents.close(); } catch {}
  views.delete(id);
  pushState();
}

function layout() {
  if (!win) return;
  const [w, h] = win.getContentSize();
  for (const [id, rec] of views) {
    rec.view.setBounds({ x: SIDEBAR, y: 0, width: Math.max(0, w - SIDEBAR), height: h });
    rec.view.setVisible(!overlay && current === id);
  }
}

function select(id) {
  const s = find(id);
  if (!s) return;
  const prev = current;
  current = id;
  const rec = views.get(id) || createView(s);
  rec.lastActive = Date.now();
  if (prev && views.has(prev)) views.get(prev).lastActive = Date.now();
  layout();
  if (!overlay) rec.view.webContents.focus();
  cfg.last = id;
  saveCfg();
  pushState();
  updateTitle();
}
const selectIndex = i => cfg.services[i] && select(cfg.services[i].id);
function cycle(d) {
  const ids = cfg.services.map(s => s.id);
  if (ids.length) select(ids[(Math.max(0, ids.indexOf(current)) + d + ids.length) % ids.length]);
}
const curWc = () => (current && views.get(current) ? views.get(current).view.webContents : null);

function hibernateTick() {
  const mins = cfg.hibernateMinutes;
  if (!mins) return;
  const now = Date.now();
  for (const [id, rec] of views) {
    const s = find(id);
    if (id !== current && s && !s.keepAlive && now - rec.lastActive > mins * 60000) destroyView(id);
  }
}

// ---- window / tray / ui
function totalUnread() { let n = 0; for (const r of views.values()) n += r.unread; return n; }
function updateTitle() {
  if (!win) return;
  const s = find(current), n = totalUnread();
  win.setTitle(`${n ? `(${n}) ` : ''}${s ? s.name + ' - ' : ''}Tessera`);
}

function snapshot() {
  return {
    services: cfg.services.map(s => {
      const r = views.get(s.id);
      const p = PRESETS[s.preset] || {};
      return Object.assign({}, s, { unread: r ? r.unread : 0, loaded: !!r, favicon: r ? r.favicon : null, logo: p.logo || null, shared: cfg.services.filter(x => sessionKey(x) === sessionKey(s)).length > 1 });
    }),
    current,
    settings: { closeToTray: cfg.closeToTray, startMinimized: cfg.startMinimized, notifications: cfg.notifications,
                hardwareAcceleration: cfg.hardwareAcceleration, hibernateMinutes: cfg.hibernateMinutes, theme: cfg.theme },
    presets: Object.entries(PRESETS).map(([id, p]) => ({ id, name: p.name, url: p.url, color: p.color, logo: p.logo, group: p.group || null })),
  };
}
function pushState() {
  if (ui && !ui.isDestroyed()) ui.send('state', snapshot());
  updateTitle();
}

function showWindow() {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280, height: 820, minWidth: 700, minHeight: 480, show: false, title: 'Tessera',
    icon: path.join(__dirname, '..', 'assets', 'icons', '512x512.png'),
    backgroundColor: '#1b1d23', autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true },
  });
  ui = win.webContents;
  if (DEBUG) ui.on('console-message', (_e, ...a) => console.log('[ui]', ...a));
  win.loadFile(path.join(__dirname, 'ui', 'index.html'));
  win.on('resize', layout);
  win.on('close', (e) => {
    if (!app.isQuitting && cfg.closeToTray && tray) { e.preventDefault(); win.hide(); }
  });
  win.on('focus', () => { const wc = curWc(); if (wc && !overlay) wc.focus(); });
  ui.once('did-finish-load', () => {
    pushState();
    if (cfg.services.length) select(find(cfg.last) ? cfg.last : cfg.services[0].id);
    if (!(cfg.startMinimized || process.argv.includes('--minimized')) || !tray) win.show();
  });
}

function trayMenu() {
  const items = cfg.services.map(s => {
    const r = views.get(s.id);
    return { label: s.name + (r && r.unread ? `  (${r.unread})` : ''), click: () => { showWindow(); select(s.id); } };
  });
  return Menu.buildFromTemplate([
    { label: 'Show Tessera', click: showWindow }, { type: 'separator' }, ...items, { type: 'separator' },
    { label: 'Quit', click: () => { app.isQuitting = true; app.quit(); } },
  ]);
}
function createTray() {
  try {
    tray = new Tray(nativeImage.createFromPath(path.join(__dirname, '..', 'assets', 'icons', '64x64.png')));
    tray.setToolTip('Tessera');
    tray.on('click', () => (win.isVisible() && win.isFocused() ? win.hide() : showWindow()));
    tray.setContextMenu(trayMenu());
  } catch { tray = null; }
}
function updateTray() {
  const n = totalUnread();
  app.setBadgeCount(n);
  if (!tray) return;
  tray.setToolTip(n ? `Tessera - ${n} unread` : 'Tessera');
  tray.setContextMenu(trayMenu());
  if (ui && !ui.isDestroyed()) ui.send('render-tray', n);   // the UI draws the badge on a canvas and returns a PNG
}

function buildMenu() {
  const cur = () => curWc();
  const zoom = (d, reset) => {
    const wc = cur(), s = find(current);
    if (!wc || !s) return;
    s.zoom = reset ? 1 : Math.min(3, Math.max(0.5, Math.round(((s.zoom || 1) + d) * 100) / 100));
    wc.setZoomFactor(s.zoom);
    saveCfg();
  };
  const t = [
    { label: 'App', submenu: [
      { label: 'Add service', accelerator: 'CmdOrCtrl+N', click: () => { showWindow(); ui.send('open-add'); } },
      { label: 'Preferences', accelerator: 'CmdOrCtrl+,', click: () => { showWindow(); ui.send('open-prefs'); } },
      { label: 'Next service', accelerator: 'Ctrl+Tab', click: () => cycle(1) },
      { label: 'Previous service', accelerator: 'Ctrl+Shift+Tab', click: () => cycle(-1) },
      { label: 'Reload', accelerator: 'CmdOrCtrl+R', click: () => cur() && cur().reload() },
      { label: 'Hard reload', accelerator: 'CmdOrCtrl+Shift+R', click: () => cur() && cur().reloadIgnoringCache() },
      { label: 'Zoom in', accelerator: 'CmdOrCtrl+=', click: () => zoom(0.1) },
      { label: 'Zoom in (+)', accelerator: 'CmdOrCtrl+Plus', visible: false, click: () => zoom(0.1) },
      { label: 'Zoom out', accelerator: 'CmdOrCtrl+-', click: () => zoom(-0.1) },
      { label: 'Reset zoom', accelerator: 'CmdOrCtrl+0', click: () => zoom(0, true) },
      { label: 'Hide window', accelerator: 'CmdOrCtrl+W', click: () => win.hide() },
      { label: 'Developer tools', accelerator: 'F12', click: () => cur() && cur().openDevTools({ mode: 'detach' }) },
      { label: 'Quit', accelerator: 'CmdOrCtrl+Q', click: () => { app.isQuitting = true; app.quit(); } },
      ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map(i => ({ label: 'Service ' + i, accelerator: 'Alt+' + i, visible: false, click: () => selectIndex(i - 1) })),
    ] },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(t));
}

// ---- IPC
function mutate(fn) { fn(); saveCfg(); pushState(); updateTray(); }

ipcMain.handle('state', () => snapshot());
ipcMain.on('select', (_e, id) => select(id));
ipcMain.on('overlay', (_e, on) => { overlay = !!on; layout(); const wc = curWc(); if (!overlay && wc) wc.focus(); });
ipcMain.on('add-service', (_e, { preset, name, url, session: sess }) => {
  if (!PRESETS[preset]) return;
  if (preset === 'custom') {
    if (!/^https?:\/\//.test(url || '')) url = 'https://' + (url || '').replace(/^\/+/, '');
    if (!safeHost(url)) return;
  }
  let s;
  mutate(() => { // join an existing login only if it belongs to the same account group (e.g. Google)
    const group = PRESETS[preset].group;
    const host = group && cfg.services.find(x => sessionKey(x) === sess && (PRESETS[x.preset] || {}).group === group);
    s = makeService(preset, (name || '').trim(), preset === 'custom' ? url : undefined, host ? sessionKey(host) : undefined);
    cfg.services.push(s); });
  select(s.id);
});
ipcMain.on('rename', (_e, id, name) => { const s = find(id); if (s && name.trim()) mutate(() => { s.name = name.trim(); }); });
ipcMain.on('set-setting', (_e, key, value) => {
  if (!(key in DEFAULTS) || key === 'services' || key === 'last') return;
  mutate(() => { cfg[key] = value; });
  if (key === 'theme') nativeTheme.themeSource = value;
});
ipcMain.on('tray-icon', (_e, dataUrl) => {
  if (tray && typeof dataUrl === 'string' && dataUrl.startsWith('data:image/png')) tray.setImage(nativeImage.createFromDataURL(dataUrl));
});
ipcMain.on('service-menu', (_e, id) => {
  const s = find(id), rec = views.get(id);
  if (!s) return;
  const i = cfg.services.indexOf(s);
  const move = d => mutate(() => { const j = i + d; if (j >= 0 && j < cfg.services.length) { [cfg.services[i], cfg.services[j]] = [cfg.services[j], cfg.services[i]]; } });
  Menu.buildFromTemplate([
    { label: 'Reload', click: () => { select(id); const wc = curWc(); wc && wc.reload(); } },
    { label: 'Sleep (free RAM)', enabled: !!rec && id !== current, click: () => destroyView(id) },
    { label: 'Keep running in background', type: 'checkbox', checked: !!s.keepAlive, click: m => mutate(() => { s.keepAlive = m.checked; }) },
    { label: 'Notifications from this app', type: 'checkbox', checked: s.notifications !== false, click: m => mutate(() => { s.notifications = m.checked; }) },
    { type: 'separator' },
    { label: 'Rename…', click: () => ui.send('open-rename', id) },
    { label: 'Move up', enabled: i > 0, click: () => move(-1) },
    { label: 'Move down', enabled: i < cfg.services.length - 1, click: () => move(1) },
    { label: 'Remove…', click: () => ui.send('open-remove', id) },
  ]).popup({ window: win });
});
ipcMain.on('remove-service', (_e, id) => {
  const s = find(id);
  if (!s) return;
  destroyView(id);
  const shared = cfg.services.some(x => x.id !== id && sessionKey(x) === sessionKey(s));
  if (!shared) session.fromPartition(partitionOf(s)).clearStorageData().catch(() => {});   // keep the login while other apps still use it
  mutate(() => { cfg.services = cfg.services.filter(x => x.id !== id); });
  if (current === id) { current = null; if (cfg.services[0]) select(cfg.services[0].id); else layout(); }
});

// ---- boot
if (process.env.TESSERA_DATA) app.setPath('userData', process.env.TESSERA_DATA);   // developer aid: isolated profile
loadCfg();
if (!cfg.hardwareAcceleration) app.disableHardwareAcceleration();

app.whenReady().then(() => {
  nativeTheme.themeSource = cfg.theme;
  buildMenu();
  createWindow();
  createTray();
  setInterval(hibernateTick, 60000);
  if (process.env.TESSERA_SHOT) {          // developer aid: print the UA + client hints a site sees, save a screenshot, quit
    setTimeout(async () => {
      const wc = curWc();
      if (wc) console.log('PROBE', JSON.stringify(await wc.executeJavaScript(
        `({ua:navigator.userAgent, brands:navigator.userAgentData&&navigator.userAgentData.brands, rtc:typeof RTCPeerConnection, h264:MediaRecorder.isTypeSupported('video/mp4;codecs=avc1')})`)));
      ui.send('open-add'); await new Promise(r => setTimeout(r, 600));
      console.log('MODAL', await ui.executeJavaScript(`document.querySelector('#modal').hidden + ' ' + document.querySelectorAll('.preset').length`));
      fs.writeFileSync(process.env.TESSERA_SHOT, (await win.capturePage()).toPNG());
      if (wc) fs.writeFileSync(process.env.TESSERA_SHOT + '.view.png', (await wc.capturePage()).toPNG());
      app.isQuitting = true; app.quit();
    }, 9000);
  }
});
app.on('before-quit', () => { app.isQuitting = true; });
app.on('window-all-closed', () => { /* tray keeps the app alive; quit is explicit */ if (!tray) app.quit(); });
