'use strict';
const api = window.tessera;
let S = { services: [], current: null, settings: {}, presets: [] };
const $ = (s) => document.querySelector(s);
const el = (tag, props = {}, ...kids) => {
  const e = Object.assign(document.createElement(tag), props);
  for (const k of kids) e.append(k);
  return e;
};

function icon(svc, cls) {
  const box = el('div', { className: cls || 'ico' });
  box.style.background = svc.color || '#546e7a';
  if (svc.logo) {                       // monochrome brand glyph, tinted white on the brand colour
    const g = el('span', { className: 'glyph' });
    g.style.webkitMaskImage = `url(../../assets/logos/${svc.logo})`;
    box.append(g);
  } else if (svc.favicon) {
    const img = el('img', { src: svc.favicon, alt: '', draggable: false });
    img.onerror = () => { img.remove(); box.textContent = (svc.name || '?')[0].toUpperCase(); };
    box.style.background = '#fff';
    box.append(img);
  } else box.textContent = (svc.name || '?')[0].toUpperCase();
  return box;
}

function render() {
  const list = $('#services');
  list.replaceChildren(...S.services.map((s) => {
    const b = el('button', { className: 'svc' + (s.id === S.current ? ' active' : '') + (s.loaded ? '' : ' asleep'), title: s.name });
    b.append(icon(s));
    if (s.unread) b.append(el('span', { className: 'badge', textContent: s.unread > 99 ? '99+' : String(s.unread) }));
    b.onclick = () => api.select(s.id);
    b.oncontextmenu = (e) => { e.preventDefault(); api.serviceMenu(s.id); };
    return b;
  }));
  $('#empty').hidden = S.services.length > 0;
}

// ---- dialogs (the main process hides the service view while one is open)
function openDialog(content) {
  const d = $('#dialog');
  d.replaceChildren(...content);
  $('#modal').hidden = false;
  api.overlay(true);
}
function closeDialog() { $('#modal').hidden = true; api.overlay(false); }
$('#modal').addEventListener('mousedown', (e) => { if (e.target.id === 'modal') closeDialog(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#modal').hidden) closeDialog(); });
const buttons = (...b) => el('div', { className: 'btns' }, ...b);
const btn = (text, fn, cls = '') => el('button', { className: 'btn ' + cls, textContent: text, onclick: fn });

function openAdd() {
  let preset = null;
  const name = el('input', { type: 'text', placeholder: 'Name (optional)' });
  const url = el('input', { type: 'text', placeholder: 'https://example.com' });
  const urlField = el('label', { className: 'field' }, 'Address', url);
  urlField.hidden = true;
  // Google apps can share one login: pick an account that is already signed in, or a new one
  const account = el('select');
  const acctField = el('label', { className: 'field' }, 'Account', account);
  acctField.hidden = true;
  const fillAccounts = (group) => {
    const seen = new Set();
    account.replaceChildren(el('option', { value: '', textContent: 'New account (sign in again)' }));
    for (const x of S.services) {
      const g = (S.presets.find((q) => q.id === x.preset) || {}).group;
      const key = x.session || x.id;
      if (g === group && !seen.has(key)) {
        seen.add(key);
        account.append(el('option', { value: key, textContent: 'Same login as ' + x.name }));
      }
    }
    account.value = account.options.length > 1 ? account.options[1].value : '';
    acctField.hidden = !group;
  };
  const add = btn('Add', () => {
    if (!preset) return;
    api.addService({ preset, name: name.value, url: url.value, session: account.value || undefined });
    closeDialog();
  }, 'primary');
  add.disabled = true;
  const cards = S.presets.map((p) => {
    const c = el('button', { className: 'preset' });
    c.append(icon(p, 'ico'), p.name);
    c.onclick = () => {
      preset = p.id;
      cards.forEach((x) => x.classList.toggle('sel', x === c));
      urlField.hidden = p.id !== 'custom';
      fillAccounts(p.group);
      add.disabled = false;
      if (p.id === 'custom') url.focus(); else name.focus();
    };
    return c;
  });
  openDialog([el('h3', { textContent: 'Add a service' }), el('div', { className: 'grid' }, ...cards),
    el('label', { className: 'field' }, 'Name', name), urlField, acctField,
    el('small', { textContent: 'Add the same service several times for multiple accounts: each login is isolated.' }),
    buttons(btn('Cancel', closeDialog), add)]);
}

function openRename(id) {
  const s = S.services.find((x) => x.id === id);
  if (!s) return;
  const input = el('input', { type: 'text', value: s.name });
  const ok = () => { api.rename(id, input.value); closeDialog(); };
  input.onkeydown = (e) => { if (e.key === 'Enter') ok(); };
  openDialog([el('h3', { textContent: 'Rename' }), input, buttons(btn('Cancel', closeDialog), btn('Save', ok, 'primary'))]);
  input.focus(); input.select();
}

function openRemove(id) {
  const s = S.services.find((x) => x.id === id);
  if (!s) return;
  openDialog([el('h3', { textContent: `Remove ${s.name}?` }),
    el('p', { textContent: s.shared ? 'Other apps sharing this login stay signed in.'
      : 'You will be signed out and its local data deleted. This cannot be undone.' }),
    buttons(btn('Cancel', closeDialog), btn('Remove', () => { api.removeService(id); closeDialog(); }, 'danger'))]);
}

function openPrefs() {
  const st = S.settings;
  const check = (key, label, note) => {
    const c = el('input', { type: 'checkbox', checked: !!st[key] });
    c.onchange = () => api.setSetting(key, c.checked);
    return el('label', { className: 'row' }, el('span', { textContent: label + (note ? ` (${note})` : '') }), c);
  };
  const theme = el('select');
  for (const t of ['system', 'dark', 'light']) theme.append(el('option', { value: t, textContent: t, selected: st.theme === t }));
  theme.onchange = () => api.setSetting('theme', theme.value);
  theme.style.width = '120px';
  const mins = el('input', { type: 'number', min: 0, max: 600, value: st.hibernateMinutes });
  mins.onchange = () => api.setSetting('hibernateMinutes', Math.max(0, parseInt(mins.value, 10) || 0));
  openDialog([el('h3', { textContent: 'Preferences' }),
    check('closeToTray', 'Keep running in tray when closed'), check('startMinimized', 'Start minimised'),
    check('notifications', 'Desktop notifications'), check('hardwareAcceleration', 'GPU acceleration', 'restart needed'),
    el('label', { className: 'row' }, el('span', { textContent: 'Theme' }), theme),
    el('label', { className: 'row' }, el('span', { textContent: 'Sleep idle services after N min (0 = never)' }), mins),
    buttons(btn('Close', closeDialog, 'primary'))]);
}

// ---- tray icon with unread badge, drawn here and handed back to the main process
const base = new Image();
base.src = '../../assets/icons/64x64.png';
function drawTray(n) {
  const c = el('canvas', { width: 64, height: 64 });
  const g = c.getContext('2d');
  const go = () => {
    g.drawImage(base, 0, 0, 64, 64);
    if (n) {
      g.fillStyle = '#ef4444'; g.beginPath(); g.arc(46, 18, 18, 0, 7); g.fill();
      g.fillStyle = '#fff'; g.font = 'bold 22px sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
      g.fillText(n > 99 ? '99' : String(n), 46, 19);
    }
    api.trayIcon(c.toDataURL('image/png'));
  };
  base.complete ? go() : (base.onload = go);
}

api.onState((s) => { S = s; render(); });
api.onRenderTray(drawTray);
api.onOpenAdd(openAdd); api.onOpenPrefs(openPrefs); api.onOpenRename(openRename); api.onOpenRemove(openRemove);
$('#btn-add').onclick = openAdd;
$('#btn-prefs').onclick = openPrefs;
api.state().then((s) => { S = s; render(); });
