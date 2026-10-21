'use strict';
const { contextBridge, ipcRenderer } = require('electron');
const on = (ch) => (cb) => ipcRenderer.on(ch, (_e, ...a) => cb(...a));
contextBridge.exposeInMainWorld('tessera', {
  state: () => ipcRenderer.invoke('state'),
  select: (id) => ipcRenderer.send('select', id),
  overlay: (on_) => ipcRenderer.send('overlay', on_),
  addService: (o) => ipcRenderer.send('add-service', o),
  removeService: (id) => ipcRenderer.send('remove-service', id),
  rename: (id, name) => ipcRenderer.send('rename', id, name),
  setSetting: (k, v) => ipcRenderer.send('set-setting', k, v),
  serviceMenu: (id) => ipcRenderer.send('service-menu', id),
  trayIcon: (dataUrl) => ipcRenderer.send('tray-icon', dataUrl),
  onState: on('state'), onRenderTray: on('render-tray'), onOpenAdd: on('open-add'),
  onOpenPrefs: on('open-prefs'), onOpenRename: on('open-rename'), onOpenRemove: on('open-remove'),
});
