#!/usr/bin/python3
"""Tessera - lightweight all-in-one messenger hub (Qt + Chromium engine).

WhatsApp (linked device), Telegram, Slack, Discord, Gmail, Outlook, Teams...
Every service instance has its own isolated login, so you can run several
WhatsApps, Gmails, Outlooks side by side. Calls, video and screen sharing work
(Chromium WebRTC). Config: ~/.config/tessera/
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from urllib.parse import urlparse

from PyQt6.QtCore import (QBuffer, QByteArray, QCoreApplication, QModelIndex, QPointF, QProcess, QRectF, QSize, Qt,
                          QTimer, QUrl, pyqtSignal)
from PyQt6.QtGui import (QAction, QColor, QDesktopServices, QFont, QIcon, QImageReader, QKeySequence, QPainter,
                         QPainterPath, QPalette, QPen, QPixmap, QShortcut)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWebEngineCore import (QWebEngineDownloadRequest, QWebEnginePage, QWebEngineProfile,
                                   QWebEngineScript, QWebEngineSettings, QWebEnginePermission)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                             QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QListView, QListWidget, QListWidgetItem, QMainWindow,
                             QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox,
                             QStackedWidget, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget)

APP_NAME = "Tessera"          # <- rename the app here (also see build.sh / packaging/)
APP_SLUG = "tessera"
APP_ID = "io.github.tessera"
REPO = "gbnanoengineer/tessera"
VERSION = "0.6.0"
ICON_NAME = os.environ.get("FLATPAK_ID", APP_SLUG)   # Flatpak installs icon/desktop file under its app id

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", HOME + "/.config"), APP_SLUG)
DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME", HOME + "/.local/share"), APP_SLUG)
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME", HOME + "/.cache"), APP_SLUG)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
CSS_FILE = os.path.join(CONFIG_DIR, "custom.css")
JS_FILE = os.path.join(CONFIG_DIR, "custom.js")
SVC_STYLE_DIR = os.path.join(CONFIG_DIR, "services")   # <id>.css / <id>.js per service
STATE_FILE = os.path.join(CONFIG_DIR, "state.json")

def migrate_legacy():
    """Move LiteHub data (logins, config) to the Tessera folders on first run."""
    for base_new in (CONFIG_DIR, DATA_DIR, CACHE_DIR):
        old = os.path.join(os.path.dirname(base_new), "lite" + "hub")
        if os.path.isdir(old) and not os.path.exists(base_new):
            try:
                shutil.move(old, base_new)
            except OSError as e:
                print("migration failed:", e, file=sys.stderr)


# key: (label, url, colour, in-app link domains, keep running in background)
PRESETS = {
    "whatsapp": ("WhatsApp", "https://web.whatsapp.com/", "#25d366", ["whatsapp.com", "whatsapp.net"], True),
    "telegram": ("Telegram", "https://web.telegram.org/a/", "#26a5e4", ["telegram.org"], True),
    "slack": ("Slack", "https://app.slack.com/client", "#4a154b", ["slack.com", "slack-edge.com"], True),
    "discord": ("Discord", "https://discord.com/app", "#5865f2", ["discord.com", "discordapp.com"], True),
    "gmail": ("Gmail", "https://mail.google.com/mail/", "#ea4335", ["google.com", "gmail.com", "gstatic.com"], True),
    "outlook": ("Outlook", "https://outlook.office.com/mail/", "#0078d4",
                ["microsoft.com", "microsoftonline.com", "live.com", "office.com", "office365.com"], True),
    "teams": ("Teams", "https://teams.microsoft.com/", "#6264a7",
              ["microsoft.com", "microsoftonline.com", "live.com", "office.com", "teams.microsoft.com"], True),
    "messenger": ("Messenger", "https://www.messenger.com/", "#0084ff", ["messenger.com", "facebook.com"], True),
    "instagram": ("Instagram", "https://www.instagram.com/", "#e4405f", ["instagram.com"], False),
    "google-meet": ("Google Meet", "https://meet.google.com/", "#00897b", ["google.com"], False),
    "custom": ("Custom site", "https://", "#546e7a", [], False),
}
# sign-in popups that must stay in-app even though they are not the service's own domain
AUTH_HOSTS = ("accounts.google.com", "login.microsoftonline.com", "login.live.com", "appleid.apple.com",
              "facebook.com", "okta.com", "auth0.com", "github.com", "login.microsoft.com")

DEFAULTS = {
    "services": [],
    "zoom": 1.0,
    "close_to_tray": True,
    "start_minimized": False,
    "notifications": True,
    "allow_microphone": True,
    "allow_camera": True,
    "hardware_acceleration": True,
    "smooth_scrolling": False,
    "spellcheck": False,
    "theme": "system",             # system | dark | light
    "font_family": "",
    "font_size_px": 0,
    "download_dir": "~/Downloads",
    "hibernate_minutes": 30,      # idle services NOT set to "keep running" are unloaded; 0 = never
    "inject_css": True,
    "inject_js": True,
    "check_updates": True,         # tell me when a new Tessera release is on GitHub
}

CSS_TEMPLATE = """/* %s custom CSS - injected into every service. Edit, then Ctrl+R.
   Per-service files: ~/.config/%s/services/<id>.css
   Example:  body { font-family: 'Inter' !important; } */
""" % (APP_NAME, APP_SLUG)
JS_TEMPLATE = "// %s custom JS - runs in every service on load. Edit, then Ctrl+R.\n" % APP_NAME


# ---------------------------------------------------------------- helpers
def load_json(path, default):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def read_text(path, template=None):
    """Read a file; if missing and a template is given, create it from it."""
    if not os.path.exists(path):
        if template is None:
            return ""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(template)
        return ""
    with open(path, errors="replace") as f:
        return f.read()


def host_in(host, suffixes):
    host = (host or "").lower()
    return any(host == s or host.endswith("." + s) for s in suffixes)


def initials(name):
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        return "?"
    return (words[0][0] + (words[1][0] if len(words) > 1 else "")).upper()


def make_service(preset, name=None, url=None, existing=()):
    label, purl, color, domains, keep = PRESETS[preset]
    if not name:
        n = sum(1 for s in existing if s.get("preset") == preset)
        name = label if n == 0 else "%s %d" % (label, n + 1)
    url = url or purl
    if preset == "custom":
        host = urlparse(url).hostname or ""
        domains = [".".join(host.split(".")[-2:])] if host else []
    return {"id": uuid.uuid4().hex[:8], "name": name, "preset": preset, "url": url,
            "color": color, "domains": domains, "keep_alive": keep, "notifications": True}


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.0f %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024


def find_icon_path():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in ("/app/share/icons/hicolor/scalable/apps/%s.svg" % ICON_NAME,
              "/usr/share/icons/hicolor/scalable/apps/%s.svg" % APP_SLUG,
              os.path.join(here, "..", "packaging", APP_SLUG + ".svg")):
        if os.path.exists(p):
            return os.path.abspath(p)
    return ""


def apply_chromium_flags(cfg):
    flags = ["--enable-features=WebRTCPipeWireCapturer,UseOzonePlatform",
             "--disable-features=Translate,MediaRouter,OptimizationHints",
             "--renderer-process-limit=8"]
    if not cfg["hardware_acceleration"]:
        flags.append("--disable-gpu")
    if not cfg["smooth_scrolling"]:
        flags.append("--disable-smooth-scrolling")
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(flags) + " " + os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    os.environ.setdefault("MALLOC_ARENA_MAX", "2")


PT = QWebEnginePermission.PermissionType


def open_url(url):
    QDesktopServices.openUrl(url if isinstance(url, QUrl) else QUrl(url))


def open_local(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


# ---------------------------------------------------------- notifications
class Notifier:
    """Desktop notifications with action buttons via notify-send (libnotify)."""

    def __init__(self, tray):
        self.tray, self.procs = tray, []
        self.have = shutil.which("notify-send") is not None
        self.gdbus = shutil.which("gdbus")

    def notify(self, title, body, actions, on_action, timeout=8000):
        """actions: [(id, label)]; first one is also the click action."""
        if not self.have and self.gdbus:      # e.g. inside Flatpak: plain notification, no buttons
            subprocess.Popen([self.gdbus, "call", "--session", "--dest", "org.freedesktop.Notifications",
                              "--object-path", "/org/freedesktop/Notifications",
                              "--method", "org.freedesktop.Notifications.Notify",
                              APP_NAME, "0", ICON_NAME, title, body, "[]", "{}", str(timeout)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if not self.have:
            if self.tray and self.tray.isVisible():
                self.tray.showMessage(title, body)
            return
        args = ["-a", APP_NAME, "-i", ICON_NAME, "-t", str(timeout), "--wait"]
        for i, (aid, label) in enumerate(actions):
            if i == 0:
                args += ["-A", "default=" + label]
            args += ["-A", "%s=%s" % (aid, label)]
        proc = QProcess()
        proc.setProgram("notify-send")
        proc.setArguments(args + [title, body])
        proc.finished.connect(lambda *_a, p=proc: self._done(p, on_action))
        self.procs.append(proc)
        proc.start()
        QTimer.singleShot(timeout * 6, lambda p=proc: p.state() != QProcess.ProcessState.NotRunning and p.kill())

    def _done(self, proc, on_action):
        out = bytes(proc.readAllStandardOutput()).decode().strip()
        if proc in self.procs:
            self.procs.remove(proc)
        if out and on_action:
            on_action("first" if out == "default" else out)


# ---------------------------------------------------------- download manager
class DownloadRow(QFrame):
    def __init__(self, mgr, dl, source):
        super().__init__()
        self.mgr, self.dl, self.source, self.path, self.done = mgr, dl, source, "", False
        self.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QHBoxLayout(self)
        col = QVBoxLayout()
        lay.addLayout(col, 1)
        self.name = QLabel(dl.downloadFileName() or "Starting…")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(8)
        self.status = QLabel(source)
        self.status.setStyleSheet("color: gray")
        for w in (self.name, self.bar, self.status):
            col.addWidget(w)
        self.b_open = QPushButton("Open")
        self.b_dir = QPushButton("Show in folder")
        self.b_x = QPushButton("Cancel")
        for b in (self.b_open, self.b_dir):
            b.setEnabled(False)
        self.b_open.clicked.connect(lambda: open_local(self.path))
        self.b_dir.clicked.connect(lambda: open_local(os.path.dirname(self.path)))
        self.b_x.clicked.connect(self.on_x)
        for b in (self.b_open, self.b_dir, self.b_x):
            lay.addWidget(b)
        dl.receivedBytesChanged.connect(self.on_progress)
        dl.totalBytesChanged.connect(self.on_progress)
        dl.stateChanged.connect(self.on_state)

    def on_progress(self):
        total, got = self.dl.totalBytes(), self.dl.receivedBytes()
        self.bar.setRange(0, 1000 if total > 0 else 0)
        if total > 0:
            self.bar.setValue(int(1000 * got / total))
        self.status.setText("%s — %s%s" % (self.source, human(got), " / " + human(total) if total > 0 else ""))

    def on_state(self, state):
        S = QWebEngineDownloadRequest.DownloadState
        if state == S.DownloadCompleted:
            self.done = True
            self.path = os.path.join(self.dl.downloadDirectory(), self.dl.downloadFileName())
            self.bar.setRange(0, 1000)
            self.bar.setValue(1000)
            self.status.setText("%s — done" % self.source)
            self.b_open.setEnabled(True)
            self.b_dir.setEnabled(True)
            self.b_x.setText("Remove")
            self.mgr.hub.finished_download(self)
        elif state in (S.DownloadCancelled, S.DownloadInterrupted):
            self.status.setText("%s — %s" % (self.source, "cancelled" if state == S.DownloadCancelled else "failed"))
            self.b_x.setText("Remove")
            self.mgr.hub.refresh_downloads_badge()

    def on_x(self):
        if self.b_x.text() == "Cancel":
            self.dl.cancel()
        else:
            self.mgr.remove(self)


class DownloadManager(QDialog):
    """One download list shared by every service."""

    def __init__(self, hub):
        super().__init__(hub)
        self.hub = hub
        self.setWindowTitle("%s — Downloads" % APP_NAME)
        self.resize(640, 440)
        v = QVBoxLayout(self)
        self.listbox = QVBoxLayout()
        self.listbox.addStretch(1)
        inner = QWidget()
        inner.setLayout(self.listbox)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(inner)
        v.addWidget(sc, 1)
        self.empty = QLabel("No downloads yet")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.empty)
        bar = QHBoxLayout()
        b1 = QPushButton("Open downloads folder")
        b1.clicked.connect(lambda: open_local(self.dest_dir()))
        b2 = QPushButton("Clear finished")
        b2.clicked.connect(self.clear_finished)
        bar.addWidget(b1)
        bar.addStretch(1)
        bar.addWidget(b2)
        v.addLayout(bar)

    def rows(self):
        return [self.listbox.itemAt(i).widget() for i in range(self.listbox.count() - 1)]

    def dest_dir(self):
        d = os.path.expanduser(self.hub.cfg["download_dir"])
        os.makedirs(d, exist_ok=True)
        return d

    def handle(self, dl, source):
        name = os.path.basename(dl.downloadFileName() or dl.suggestedFileName()) or "download"
        base, ext = os.path.splitext(name)
        path, i = os.path.join(self.dest_dir(), name), 1
        while os.path.exists(path):
            path = os.path.join(self.dest_dir(), "%s (%d)%s" % (base, i, ext))
            i += 1
        dl.setDownloadDirectory(os.path.dirname(path))
        dl.setDownloadFileName(os.path.basename(path))
        row = DownloadRow(self, dl, source)
        row.path = path
        self.listbox.insertWidget(0, row)
        self.empty.hide()
        dl.accept()
        self.hub.refresh_downloads_badge()

    def remove(self, row):
        self.listbox.removeWidget(row)
        row.deleteLater()
        self.empty.setVisible(not self.rows() or len(self.rows()) == 1 and self.rows()[0] is row)
        QTimer.singleShot(0, self.hub.refresh_downloads_badge)

    def clear_finished(self):
        for r in self.rows():
            if r.b_x.text() == "Remove":
                self.remove(r)

    def active_count(self):
        return sum(1 for r in self.rows() if r.b_x.text() == "Cancel")


# ----------------------------------------------------------- web pages
class PopupPage(QWebEnginePage):
    """window.open() target (OAuth sign-in etc.): small window sharing the session."""

    def __init__(self, sv, profile, dialog):
        super().__init__(profile, dialog)
        self.sv, self.dialog, self.first = sv, dialog, True
        self.windowCloseRequested.connect(dialog.close)

    def acceptNavigationRequest(self, url, ntype, is_main):
        if self.first and is_main and url.scheme() in ("http", "https"):
            self.first = False
            host = url.host()
            if not (host_in(host, self.sv.svc.get("domains", [])) or host_in(host, AUTH_HOSTS)):
                open_url(url)
                self.dialog.close()
                return False
            self.dialog.show()
        return True


class ServicePage(QWebEnginePage):
    def __init__(self, sv, profile, parent):
        super().__init__(profile, parent)
        self.sv = sv

    def acceptNavigationRequest(self, url, ntype, is_main):
        if url.scheme() in ("mailto", "tel", "sms"):
            open_url(url)
            return False
        if (ntype == QWebEnginePage.NavigationType.NavigationTypeLinkClicked and is_main
                and url.scheme() in ("http", "https")):
            host = url.host()
            if not (host_in(host, self.sv.svc.get("domains", [])) or host_in(host, AUTH_HOSTS)):
                open_url(url)
                return False
        return True

    def createWindow(self, wtype):
        dlg = QDialog(self.sv.hub)
        dlg.setWindowTitle(self.sv.svc["name"])
        dlg.resize(520, 700)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        view = QWebEngineView(dlg)
        page = PopupPage(self.sv, self.profile(), dlg)
        view.setPage(page)
        page.titleChanged.connect(dlg.setWindowTitle)
        lay.addWidget(view)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        return page


class ServiceView:
    """One service instance: isolated Chromium profile, created lazily."""

    def __init__(self, hub, svc):
        self.hub, self.svc = hub, svc
        self.view = self.page = self.profile = None
        self.unread = 0
        self.last_active = 0
        self.notes = {}

    @property
    def id(self):
        return self.svc["id"]

    def load(self):
        if self.view:
            return
        cfg = self.hub.cfg
        ddir = os.path.join(DATA_DIR, "services", self.id)
        cdir = os.path.join(CACHE_DIR, "services", self.id)
        os.makedirs(ddir, exist_ok=True)
        os.makedirs(cdir, exist_ok=True)
        prof = QWebEngineProfile("svc-" + self.id, self.hub)
        prof.setPersistentStoragePath(ddir)
        prof.setCachePath(cdir)
        prof.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        prof.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        prof.setHttpCacheMaximumSize(150 * 1024 * 1024)
        prof.setHttpUserAgent(self.svc.get("ua") or re.sub(r"\s*QtWebEngine/\S+", "", prof.httpUserAgent()))
        prof.setSpellCheckEnabled(bool(cfg["spellcheck"]))
        if cfg["spellcheck"]:
            prof.setSpellCheckLanguages(["en-US"])
        prof.setNotificationPresenter(self.on_notification)
        prof.downloadRequested.connect(lambda dl: self.hub.downloads.handle(dl, self.svc["name"]))
        s = prof.settings()
        A = QWebEngineSettings.WebAttribute
        for attr, val in ((A.ScreenCaptureEnabled, True), (A.JavascriptCanAccessClipboard, True),
                          (A.PlaybackRequiresUserGesture, False), (A.FullScreenSupportEnabled, True),
                          (A.WebRTCPublicInterfacesOnly, False), (A.ScrollAnimatorEnabled, bool(cfg["smooth_scrolling"]))):
            s.setAttribute(attr, val)
        self.profile = prof

        view = QWebEngineView(self.hub)
        page = ServicePage(self, prof, view)
        view.setPage(page)
        page.permissionRequested.connect(self.on_permission)
        page.desktopMediaRequested.connect(self.on_desktop_media)
        page.titleChanged.connect(self.on_title)
        page.iconChanged.connect(lambda ic: self.hub.set_favicon(self.svc, ic, page.url().host()))
        page.fullScreenRequested.connect(self.on_fullscreen)
        page.setUrl(QUrl(self.svc["url"]))
        view.setZoomFactor(float(cfg["zoom"]))
        self.add_scripts(page)
        self.view, self.page = view, page
        self.hub.stack.addWidget(view)
        if self.hub.args.debug:
            page.loadFinished.connect(lambda ok: QTimer.singleShot(8000, self.probe))
        self.hub.refresh_button(self)

    def add_scripts(self, page):
        cfg, css = self.hub.cfg, []
        if cfg["font_family"]:
            css.append("body, body * { font-family: %s !important; }" % json.dumps(cfg["font_family"]))
        if cfg["font_size_px"]:
            css.append("html { font-size: %dpx !important; }" % int(cfg["font_size_px"]))
        js = []
        if cfg["inject_css"]:
            css.append(read_text(CSS_FILE, CSS_TEMPLATE))
            css.append(read_text(os.path.join(SVC_STYLE_DIR, self.id + ".css")))
        if cfg["inject_js"]:
            js += [read_text(JS_FILE, JS_TEMPLATE), read_text(os.path.join(SVC_STYLE_DIR, self.id + ".js"))]
        code = "".join(css).strip()
        if code:
            js.insert(0, "(function(){var s=document.createElement('style');s.textContent=%s;"
                         "(document.head||document.documentElement).appendChild(s);})();" % json.dumps(code))
        src = "\n".join(j for j in js if j.strip())
        if src.strip():
            sc = QWebEngineScript()
            sc.setName("tessera-custom")
            sc.setSourceCode(src)
            sc.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
            sc.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            page.scripts().insert(sc)

    def hibernate(self):
        if not self.view:
            return
        self.hub.stack.removeWidget(self.view)
        self.view.setPage(None)
        self.page.deleteLater()
        self.view.deleteLater()
        self.profile.deleteLater()
        self.view = self.page = self.profile = None
        self.set_unread(0)
        self.hub.refresh_button(self)

    # -- callbacks --
    def on_permission(self, perm):
        cfg, t = self.hub.cfg, perm.permissionType()
        allow = {
            PT.MediaAudioCapture: cfg["allow_microphone"],
            PT.MediaVideoCapture: cfg["allow_camera"],
            PT.MediaAudioVideoCapture: cfg["allow_microphone"] and cfg["allow_camera"],
            PT.DesktopVideoCapture: True, PT.DesktopAudioVideoCapture: True,
            PT.Notifications: cfg["notifications"] and self.svc.get("notifications", True),
            PT.ClipboardReadWrite: True,
        }.get(t, False)
        (perm.grant if allow else perm.deny)()

    def on_desktop_media(self, req):
        """Screen / window picker for screen sharing."""
        items, targets = [], []
        for kind, model in (("Screen", req.screensModel()), ("Window", req.windowsModel())):
            for r in range(model.rowCount()):
                idx = model.index(r, 0)
                items.append("%s: %s" % (kind, model.data(idx) or r + 1))
                targets.append((kind, idx))
        if not items:
            req.cancel()
            return
        if len(items) == 1:
            choice = 0
        else:
            text, ok = QInputDialog.getItem(self.hub, "Share your screen", "Choose what to share:", items, 0, False)
            if not ok:
                req.cancel()
                return
            choice = items.index(text)
        kind, idx = targets[choice]
        (req.selectScreen if kind == "Screen" else req.selectWindow)(idx)

    def on_fullscreen(self, req):
        req.accept()
        self.hub.set_video_fullscreen(req.toggleOn(), self)

    def on_notification(self, note):
        if not (self.hub.cfg["notifications"] and self.svc.get("notifications", True)):
            return
        key = uuid.uuid4().hex
        self.notes[key] = note
        note.show()
        note.closed.connect(lambda k=key: self.notes.pop(k, None))
        self.hub.notifier.notify("%s: %s" % (self.svc["name"], note.title()), note.message(),
                                 [("open", "Open")],
                                 lambda _a, n=note: (self.hub.show_service(self.id), n.click()))

    def on_title(self, title):
        m = re.search(r"\((\d+)\)", title or "")
        self.set_unread(int(m.group(1)) if m else 0)
        if self.hub.current is self:
            self.hub.update_title()

    def set_unread(self, n):
        if n != self.unread:
            self.unread = n
            self.hub.refresh_button(self)
            self.hub.update_unread()

    def probe(self):
        if self.page:
            self.page.runJavaScript(
                "[typeof RTCPeerConnection, navigator.mediaDevices && typeof navigator.mediaDevices.getDisplayMedia, "
                "document.title].join(' | ')", lambda r, n=self.svc["name"]: print("[debug] %s: %s" % (n, r), flush=True))


# ------------------------------------------------------------ theme + icons
THEMES = {
    "dark": dict(dark=True, bg="#1b1d21", side="#131417", surface="#262a30", text="#e8eaed", muted="#9aa0a6",
                 accent="#5b8def", hover="#2b2f36", border="#33383f"),
    "light": dict(dark=False, bg="#f4f6f8", side="#e6eaef", surface="#ffffff", text="#1f2328", muted="#656d76",
                  accent="#2563eb", hover="#d9e0e8", border="#d0d7de"),
}
DPR = 1.0
# Brand logo paths from Simple Icons (CC0, https://simpleicons.org); Outlook/Teams are drawn (not in that set)
LOGOS = {
    "whatsapp": "M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z",
    "telegram": "M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z",
    "slack": "M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z",
    "discord": "M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c.1202.099.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.2986 12.2986 0 01-1.873.8914.0766.0766 0 00-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189Z",
    "gmail": "M24 5.457v13.909c0 .904-.732 1.636-1.636 1.636h-3.819V11.73L12 16.64l-6.545-4.91v9.273H1.636A1.636 1.636 0 0 1 0 19.366V5.457c0-2.023 2.309-3.178 3.927-1.964L5.455 4.64 12 9.548l6.545-4.91 1.528-1.145C21.69 2.28 24 3.434 24 5.457z",
    "messenger": "M12 0C5.24 0 0 4.952 0 11.64c0 3.499 1.434 6.521 3.769 8.61a.96.96 0 0 1 .323.683l.065 2.135a.96.96 0 0 0 1.347.85l2.381-1.053a.96.96 0 0 1 .641-.046A13 13 0 0 0 12 23.28c6.76 0 12-4.952 12-11.64S18.76 0 12 0m6.806 7.44c.522-.03.971.567.63 1.094l-4.178 6.457a.707.707 0 0 1-.977.208l-3.87-2.504a.44.44 0 0 0-.49.007l-4.363 3.01c-.637.438-1.415-.317-.995-.966l4.179-6.457a.706.706 0 0 1 .977-.21l3.87 2.505c.15.097.344.094.491-.007l4.362-3.008a.7.7 0 0 1 .364-.13",
    "instagram": "M7.0301.084c-1.2768.0602-2.1487.264-2.911.5634-.7888.3075-1.4575.72-2.1228 1.3877-.6652.6677-1.075 1.3368-1.3802 2.127-.2954.7638-.4956 1.6365-.552 2.914-.0564 1.2775-.0689 1.6882-.0626 4.947.0062 3.2586.0206 3.6671.0825 4.9473.061 1.2765.264 2.1482.5635 2.9107.308.7889.72 1.4573 1.388 2.1228.6679.6655 1.3365 1.0743 2.1285 1.38.7632.295 1.6361.4961 2.9134.552 1.2773.056 1.6884.069 4.9462.0627 3.2578-.0062 3.668-.0207 4.9478-.0814 1.28-.0607 2.147-.2652 2.9098-.5633.7889-.3086 1.4578-.72 2.1228-1.3881.665-.6682 1.0745-1.3378 1.3795-2.1284.2957-.7632.4966-1.636.552-2.9124.056-1.2809.0692-1.6898.063-4.948-.0063-3.2583-.021-3.6668-.0817-4.9465-.0607-1.2797-.264-2.1487-.5633-2.9117-.3084-.7889-.72-1.4568-1.3876-2.1228C21.2982 1.33 20.628.9208 19.8378.6165 19.074.321 18.2017.1197 16.9244.0645 15.6471.0093 15.236-.005 11.977.0014 8.718.0076 8.31.0215 7.0301.0839m.1402 21.6932c-1.17-.0509-1.8053-.2453-2.2287-.408-.5606-.216-.96-.4771-1.3819-.895-.422-.4178-.6811-.8186-.9-1.378-.1644-.4234-.3624-1.058-.4171-2.228-.0595-1.2645-.072-1.6442-.079-4.848-.007-3.2037.0053-3.583.0607-4.848.05-1.169.2456-1.805.408-2.2282.216-.5613.4762-.96.895-1.3816.4188-.4217.8184-.6814 1.3783-.9003.423-.1651 1.0575-.3614 2.227-.4171 1.2655-.06 1.6447-.072 4.848-.079 3.2033-.007 3.5835.005 4.8495.0608 1.169.0508 1.8053.2445 2.228.408.5608.216.96.4754 1.3816.895.4217.4194.6816.8176.9005 1.3787.1653.4217.3617 1.056.4169 2.2263.0602 1.2655.0739 1.645.0796 4.848.0058 3.203-.0055 3.5834-.061 4.848-.051 1.17-.245 1.8055-.408 2.2294-.216.5604-.4763.96-.8954 1.3814-.419.4215-.8181.6811-1.3783.9-.4224.1649-1.0577.3617-2.2262.4174-1.2656.0595-1.6448.072-4.8493.079-3.2045.007-3.5825-.006-4.848-.0608M16.953 5.5864A1.44 1.44 0 1 0 18.39 4.144a1.44 1.44 0 0 0-1.437 1.4424M5.8385 12.012c.0067 3.4032 2.7706 6.1557 6.173 6.1493 3.4026-.0065 6.157-2.7701 6.1506-6.1733-.0065-3.4032-2.771-6.1565-6.174-6.1498-3.403.0067-6.156 2.771-6.1496 6.1738M8 12.0077a4 4 0 1 1 4.008 3.9921A3.9996 3.9996 0 0 1 8 12.0077",
    "google-meet": "M5.53 2.13 0 7.75h5.53zm.398 0v5.62h7.608v3.65l5.47-4.45c-.014-1.22.031-2.25-.025-3.46-.148-1.09-1.287-1.47-2.236-1.36zM23.1 4.32c-.802.295-1.358.995-2.047 1.49-2.506 2.05-4.982 4.12-7.468 6.19 3.025 2.59 6.04 5.18 9.065 7.76 1.218.671 1.428-.814 1.328-1.64v-13a.828.828 0 0 0-.877-.825zM.038 8.15v7.7h5.53v-7.7zm13.577 8.1H6.008v5.62c3.864-.006 7.737.011 11.58-.009 1.02-.07 1.618-1.12 1.468-2.07v-2.51l-5.47-4.68v3.65zm-13.577 0c.02 1.44-.041 2.88.033 4.31.162.948 1.158 1.43 2.047 1.31h3.464v-5.62z",
}

# simple original brand-style glyphs on a 24x24 grid; {fg} = glyph colour, {bg} = tile colour (for cut-outs)
GLYPHS = {
    "whatsapp": '<path fill="{fg}" d="M12 2.5a9.4 9.4 0 0 0-8 14.3L2.6 21.500l4.800-1.300A9.400 9.400 0 1 0 12 2.500z"/>'
                '<path fill="{bg}" d="M8.600 7.400c-.5 0-1 .6-1.100 1.300-.200 2.300 3 6 6.600 7 .9.2 1.600-.3 1.800-1l-1.800-1.100-1 .9c-1.300-.5-2.500-1.700-3.100-3l.9-.8z"/>',
    "telegram": '<path fill="{fg}" d="M21 3.300 2.700 10.400c-.8.300-.8 1.400 0 1.700l4.600 1.500 1.800 5.600c.2.600 1 .8 1.400.3l2.500-2.500 4.500 3.300c.6.400 1.400.1 1.600-.6l3.100-15.500c.2-.8-.6-1.500-1.400-1.200z"/>'
                '<path stroke="{bg}" stroke-width="1.300" stroke-linecap="round" fill="none" d="M9.200 13.800 17.800 7.800"/>',
    "slack": '<g stroke="{fg}" stroke-width="2.700" stroke-linecap="round" fill="none"><path d="M9.500 3.800 8 20.200M16 3.800l-1.500 16.400M4 9h16.500M3.500 15h16.500"/></g>',
    "discord": '<path fill="{fg}" d="M19.600 5.600a16 16 0 0 0-4-1.300l-.5 1a14 14 0 0 0-4.200 0l-.5-1a16 16 0 0 0-4 1.300C4 9.400 3.300 13 3.600 16.600a16 16 0 0 0 4.900 2.500l1-1.600-1.500-.8.400-.3a11 11 0 0 0 9.200 0l.4.300-1.500.8 1 1.600a16 16 0 0 0 4.900-2.500c.4-4.200-.7-7.900-2.800-11z"/>'
               '<circle cx="9.200" cy="12" r="1.700" fill="{bg}"/><circle cx="14.800" cy="12" r="1.700" fill="{bg}"/>',
    "gmail": '<rect x="2.500" y="5" width="19" height="14" rx="2.200" fill="{fg}"/>'
             '<path d="M3.500 7 12 13.500 20.500 7" stroke="{bg}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
    "outlook": '<rect x="2.500" y="4" width="19" height="16" rx="2.500" fill="{fg}"/><circle cx="12" cy="12" r="4" stroke="{bg}" stroke-width="2.400" fill="none"/>',
    "teams": '<rect x="2.500" y="4" width="19" height="16" rx="3" fill="{fg}"/><path d="M7.500 8.500h9M12 8.500v8" stroke="{bg}" stroke-width="2.600" stroke-linecap="round" fill="none"/>',
    "messenger": '<path fill="{fg}" d="M12 2.400c-5.300 0-9.400 3.900-9.400 9.100 0 2.700 1.200 5 3 6.600v3.400l3.200-1.800c.9.200 1.800.4 2.800.4 5.300 0 9.400-3.900 9.400-9.100S17.300 2.400 12 2.400z"/>'
                 '<path fill="{bg}" d="m6.500 14.300 3.500-3.700 2.400 2.400 3.600-2.500-3.600 4.500-2.400-2.300z"/>',
    "instagram": '<g fill="none" stroke="{fg}" stroke-width="2.100"><rect x="3.500" y="3.500" width="17" height="17" rx="5"/><circle cx="12" cy="12" r="4"/></g><circle cx="17.200" cy="6.800" r="1.200" fill="{fg}"/>',
    "google-meet": '<rect x="2.500" y="6" width="12" height="12" rx="2.500" fill="{fg}"/><path fill="{fg}" d="m16.500 10.500 5-3.200v9.400l-5-3.200z"/>',
    "custom": '<g fill="none" stroke="{fg}" stroke-width="1.900" stroke-linecap="round"><circle cx="12" cy="12" r="8.500"/><path d="M3.500 12h17M12 3.500c3 3 3 14 0 17M12 3.500c-3 3-3 14 0 17"/></g>',
}
UI_ICONS = {
    "download": '<path d="M12 3.500v11M7.500 10.500 12 15l4.500-4.500M4.500 19.500h15"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "settings": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.500v2.200M12 19.300v2.200M2.500 12h2.200M19.300 12h2.200M5.300 5.300l1.500 1.500M17.200 17.200l1.500 1.500M5.300 18.700l1.500-1.500M17.200 6.800l1.500-1.500"/>',
    "moon": '<path d="M20.500 13.500A8.500 8.500 0 1 1 10.500 3.500a6.800 6.800 0 0 0 10 10z"/>',
}


def render_svg(svg, size):
    """Render an SVG string to a crisp QPixmap of logical size `size` (no QtSvg module needed)."""
    ba = QByteArray(svg.encode())
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.ReadOnly)
    rd = QImageReader(buf, b"svg")
    px = max(1, int(size * DPR))
    rd.setScaledSize(QSize(px, px))
    pm = QPixmap.fromImage(rd.read())
    pm.setDevicePixelRatio(DPR)
    return pm


def ui_icon(name, color, size=22):
    return render_svg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%s" '
                      'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">%s</svg>'
                      % (color, UI_ICONS[name]), size)


def glyph_svg(preset, fg, bg):
    if preset in LOGOS:
        body = '<path fill="%s" d="%s"/>' % (fg, LOGOS[preset])
    else:
        body = GLYPHS.get(preset, GLYPHS["custom"]).format(fg=fg, bg=bg)
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">%s</svg>' % body


def tile_pixmap(svc, size, fav=None):
    """Rounded app tile: real favicon on white if we have one, else brand colour + glyph."""
    px = int(size * DPR)
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(DPR)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.27, size * 0.27)
    p.setClipPath(path)
    if fav is not None and not fav.isNull():
        p.fillPath(path, QColor("#ffffff"))
        inner = size * 0.66
        scaled = fav.scaled(int(inner * DPR), int(inner * DPR), Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        w, h = scaled.width() / DPR, scaled.height() / DPR
        p.drawPixmap(QPointF((size - w) / 2, (size - h) / 2), scaled)
    else:
        color = brand_color(svc)
        p.fillPath(path, QColor(color))
        g = render_svg(glyph_svg(svc.get("preset", "custom"), "#ffffff", color), size * 0.58)
        o = size * 0.21
        p.drawPixmap(QPointF(o, o), g)
    p.end()
    return pm


def brand_color(svc):
    pr = svc.get("preset")
    return PRESETS[pr][2] if pr in PRESETS and pr != "custom" else svc["color"]


def fav_key(svc):
    return svc["id"] if svc.get("preset") == "custom" else svc["preset"]


def make_palette(t):
    pal = QPalette()
    C = QColor
    for role, col in ((QPalette.ColorRole.Window, t["bg"]), (QPalette.ColorRole.WindowText, t["text"]),
                      (QPalette.ColorRole.Base, t["surface"]), (QPalette.ColorRole.AlternateBase, t["bg"]),
                      (QPalette.ColorRole.Text, t["text"]), (QPalette.ColorRole.Button, t["surface"]),
                      (QPalette.ColorRole.ButtonText, t["text"]), (QPalette.ColorRole.ToolTipBase, t["surface"]),
                      (QPalette.ColorRole.ToolTipText, t["text"]), (QPalette.ColorRole.Highlight, t["accent"]),
                      (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.PlaceholderText, t["muted"]),
                      (QPalette.ColorRole.Link, t["accent"]), (QPalette.ColorRole.BrightText, "#ffffff")):
        pal.setColor(role, C(col))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, C(t["muted"]))
    return pal


def resolve_theme(name):
    app = QApplication.instance()
    if name in THEMES:
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark if THEMES[name]["dark"] else Qt.ColorScheme.Light)
        return name
    app.styleHints().setColorScheme(Qt.ColorScheme.Unknown)
    return "light" if app.styleHints().colorScheme() == Qt.ColorScheme.Light else "dark"


class SvcButton(QWidget):
    """Sidebar tile: icon, active bar, unread badge, dimmed when sleeping."""
    clicked = pyqtSignal()
    menu = pyqtSignal(object)

    def __init__(self, hub):
        super().__init__()
        self.hub, self.pm, self.active, self.awake, self.unread, self.hover = hub, None, False, False, 0, False
        self.setFixedSize(72, 54)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        elif e.button() == Qt.MouseButton.RightButton:
            self.menu.emit(e.globalPosition().toPoint())

    def paintEvent(self, e):
        t = self.hub.t
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        if self.active or self.hover:
            h = 30 if self.active else 14
            p.setBrush(QColor(t["accent"] if self.active else t["muted"]))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(-4, (self.height() - h) / 2, 8, h), 4, 4)
        if self.pm is not None:
            p.setOpacity(1.0 if (self.awake or self.active or self.hover) else 0.5)
            p.drawPixmap(QPointF(14, 5), self.pm)
            p.setOpacity(1.0)
        if self.active:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(t["accent"]), 2))
            p.drawRoundedRect(QRectF(13, 4, 46, 46), 13, 13)
        if self.unread:
            txt = str(self.unread) if self.unread < 100 else "99+"
            f = QFont(self.font())
            f.setPixelSize(10)
            f.setBold(True)
            p.setFont(f)
            w = max(18, p.fontMetrics().horizontalAdvance(txt) + 10)
            r = QRectF(58 - w + 4, 1, w, 17)
            p.setBrush(QColor("#e53935"))
            p.setPen(QPen(QColor(t["side"]), 2))
            p.drawRoundedRect(r, 8.5, 8.5)
            p.setPen(QColor("#ffffff"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, txt)


class IconButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, hub, tip, cb):
        super().__init__()
        self.hub, self.pm, self.hover, self.count = hub, None, False, 0
        self.setFixedSize(72, 44)
        self.setToolTip(tip)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(cb)

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, e):
        t = self.hub.t
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing)
        if self.hover:
            p.setBrush(QColor(t["hover"]))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(14, 2, 44, 40), 12, 12)
        if self.pm is not None:
            p.drawPixmap(QPointF(36 - 11, 22 - 11), self.pm)
        if self.count:
            f = QFont(self.font())
            f.setPixelSize(10)
            f.setBold(True)
            p.setFont(f)
            r = QRectF(40, 3, 17, 16)
            p.setBrush(QColor("#e53935"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 8, 8)
            p.setPen(QColor("#ffffff"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(self.count))

    def set_icon(self, name, color):
        self.pm = ui_icon(name, color)
        self.update()


# ----------------------------------------------------------- main window
class Prefs(QDialog):
    def __init__(self, hub):
        super().__init__(hub)
        self.setWindowTitle("%s Preferences" % APP_NAME)
        self.hub, self.w = hub, {}
        cfg = hub.cfg
        form = QFormLayout(self)
        for key, label in [("close_to_tray", "Keep running in tray when closed"),
                           ("start_minimized", "Start minimised"),
                           ("notifications", "Desktop notifications"),
                           ("allow_microphone", "Allow microphone (calls, voice notes)"),
                           ("allow_camera", "Allow camera (video calls)"),
                           ("hardware_acceleration", "GPU acceleration (off = less GPU RAM, more CPU)"),
                           ("smooth_scrolling", "Smooth scrolling"),
                           ("spellcheck", "Spell checking (en-US)"),
                           ("inject_css", "Apply custom CSS"), ("inject_js", "Apply custom JS")]:
            w = QCheckBox()
            w.setChecked(bool(cfg[key]))
            form.addRow(label, w)
            self.w[key] = w
        th = QComboBox()
        th.addItems(["system", "dark", "light"])
        th.setCurrentText(cfg["theme"] if cfg["theme"] in ("system", "dark", "light") else "system")
        form.addRow("Theme", th)
        self.w["theme"] = th
        z = QDoubleSpinBox()
        z.setRange(0.5, 3.0)
        z.setSingleStep(0.1)
        z.setValue(float(cfg["zoom"]))
        form.addRow("Zoom", z)
        self.w["zoom"] = z
        for key, label, hi in [("font_size_px", "Base font size px (0 = default)", 30),
                               ("hibernate_minutes", "Sleep idle services after N min (0 = never)", 600)]:
            sp = QSpinBox()
            sp.setRange(0, hi)
            sp.setValue(int(cfg[key]))
            form.addRow(label, sp)
            self.w[key] = sp
        for key, label in [("font_family", "Font family"), ("download_dir", "Download folder")]:
            e = QLineEdit(cfg[key])
            form.addRow(label, e)
            self.w[key] = e
        row = QHBoxLayout()
        for text, path, tpl in [("Edit global CSS", CSS_FILE, CSS_TEMPLATE), ("Edit global JS", JS_FILE, JS_TEMPLATE),
                                ("Open config folder", CONFIG_DIR, None)]:
            b = QPushButton(text)
            b.clicked.connect(lambda _c, p=path, t=tpl: hub.open_path(p, t))
            row.addWidget(b)
        form.addRow(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        ok = bb.addButton("Save && restart", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self):
        out = {}
        for k, w in self.w.items():
            if isinstance(w, QCheckBox):
                out[k] = w.isChecked()
            elif isinstance(w, QDoubleSpinBox):
                out[k] = round(w.value(), 2)
            elif isinstance(w, QSpinBox):
                out[k] = w.value()
            elif isinstance(w, QComboBox):
                out[k] = w.currentText()
            else:
                out[k] = w.text()
        return out


class Hub(QMainWindow):
    update_found = pyqtSignal(str, str)

    def __init__(self, args, cfg):
        super().__init__()
        self.args, self.cfg = args, cfg
        self.views, self.buttons, self.current, self.favs = {}, {}, None, {}
        self.really_quit = False
        self.tname = resolve_theme(cfg["theme"])
        self.t = THEMES[self.tname]
        self.icon = QIcon.fromTheme(ICON_NAME)
        if self.icon.isNull() and find_icon_path():
            self.icon = QIcon(find_icon_path())
        self.setWindowIcon(self.icon)
        self.setWindowTitle(APP_NAME)
        st = load_json(STATE_FILE, {})
        self.resize(st.get("w", 1200), st.get("h", 780))
        self.start_max = bool(st.get("max"))

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.icon, self)
            self.tray_menu = QMenu()
            self.tray_menu.aboutToShow.connect(self.build_tray_menu)
            self.tray.setContextMenu(self.tray_menu)
            self.tray.activated.connect(lambda r: self.show_window() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
            self.tray.show()
        self.notifier = Notifier(self.tray)
        self.downloads = DownloadManager(self)

        root = QWidget()
        self.setCentralWidget(root)
        hl = QHBoxLayout(root)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        self.side = QWidget()
        self.side.setObjectName("side")
        self.side.setFixedWidth(72)
        sl = QVBoxLayout(self.side)
        sl.setContentsMargins(0, 10, 0, 10)
        sl.setSpacing(2)
        self.svc_layout = QVBoxLayout()
        self.svc_layout.setSpacing(4)
        sl.addLayout(self.svc_layout)
        sl.addStretch(1)
        self.theme_btn = IconButton(self, "Switch dark / light theme", self.toggle_theme)
        self.dl_btn = IconButton(self, "Downloads (Ctrl+Shift+D)", self.show_downloads)
        self.add_btn = IconButton(self, "Add service (Ctrl+N)", self.add_service_dialog)
        self.prefs_btn = IconButton(self, "Preferences (Ctrl+,)", self.show_prefs)
        for b in (self.theme_btn, self.dl_btn, self.add_btn, self.prefs_btn):
            sl.addWidget(b)
        hl.addWidget(self.side)
        self.stack = QStackedWidget()
        self.welcome = self.build_welcome()
        self.stack.addWidget(self.welcome)
        hl.addWidget(self.stack, 1)

        self.shortcuts()
        self.rebuild()
        self.apply_theme()
        self.update_found.connect(self.on_update_found)
        if cfg["check_updates"]:
            threading.Thread(target=self.check_update, daemon=True).start()
        QTimer(self, interval=60000, timeout=self.hibernate_tick).start()
    def build_welcome(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.w_title = QLabel("Welcome to %s" % APP_NAME)
        self.w_sub = QLabel("All your chats and mail in one light window. Pick a service to add —\n"
                            "you can add the same service several times for multiple accounts.")
        for lbl in (self.w_title, self.w_sub):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.w_title)
        lay.addWidget(self.w_sub)
        self.w_grid = QGridLayout()
        self.w_grid.setSpacing(14)
        wrap = QWidget()
        wrap.setLayout(self.w_grid)
        lay.addSpacing(18)
        lay.addWidget(wrap, 0, Qt.AlignmentFlag.AlignCenter)
        return w

    def fill_welcome(self):
        while self.w_grid.count():
            self.w_grid.takeAt(0).widget().deleteLater()
        for n, key in enumerate(k for k in PRESETS if k != "custom"):
            svc = {"preset": key, "color": PRESETS[key][2], "id": key}
            b = QToolButton()
            b.setIcon(QIcon(tile_pixmap(svc, 56, self.fav_pixmap(svc))))
            b.setIconSize(QSize(56, 56))
            b.setText(PRESETS[key][0])
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedSize(104, 100)
            b.setStyleSheet("QToolButton{border:none;border-radius:14px;color:%s;font-size:12px;}"
                            "QToolButton:hover{background:%s;}" % (self.t["text"], self.t["hover"]))
            b.clicked.connect(lambda _c, k=key: self.add_preset(k))
            self.w_grid.addWidget(b, n // 5, n % 5)

    def add_preset(self, key):
        svc = make_service(key, existing=self.cfg["services"])
        self.cfg["services"].append(svc)
        self.save()
        self.rebuild()
        self.select(svc["id"])

    # -- theme --
    def apply_theme(self):
        t = self.t
        QApplication.instance().setPalette(make_palette(t))
        self.side.setStyleSheet("#side{background:%s;} QToolTip{background:%s;color:%s;border:1px solid %s;padding:4px;}"
                                % (t["side"], t["surface"], t["text"], t["border"]))
        self.w_title.setStyleSheet("font-size:26px;font-weight:600;color:%s;" % t["text"])
        self.w_sub.setStyleSheet("font-size:13px;color:%s;" % t["muted"])
        self.welcome.setStyleSheet("background:%s;" % t["bg"])
        self.theme_btn.set_icon("sun" if t["dark"] else "moon", t["muted"])
        self.dl_btn.set_icon("download", t["muted"])
        self.add_btn.set_icon("plus", t["muted"])
        self.prefs_btn.set_icon("settings", t["muted"])
        self.fill_welcome()
        for sv in self.views.values():
            self.refresh_button(sv)
        self.update()

    def toggle_theme(self):
        self.cfg["theme"] = "light" if self.t["dark"] else "dark"
        self.tname = resolve_theme(self.cfg["theme"])
        self.t = THEMES[self.tname]
        self.save()
        self.apply_theme()

    # -- favicons: the real site icon, cached so it also shows while the service sleeps --
    def fav_pixmap(self, svc):
        if svc.get("preset") != "custom":      # known services use their fixed brand logo (tab icons change, e.g. unread counts)
            return None
        key = fav_key(svc)
        if key not in self.favs:
            path = os.path.join(CACHE_DIR, "icons", key + ".png")
            pm = QPixmap(path) if os.path.exists(path) else None
            self.favs[key] = pm if pm is not None and not pm.isNull() else None
        return self.favs[key]

    def set_favicon(self, svc, icon, host=""):
        if svc.get("preset") != "custom":
            return
        if host_in(host, AUTH_HOSTS):       # don't cache a sign-in page's icon (e.g. Google 'G' for Gmail)
            return
        sizes = icon.availableSizes()
        if not sizes:
            return
        big = max(sizes, key=lambda z: z.width())
        if big.width() < 32:
            return
        pm = icon.pixmap(big)
        key = fav_key(svc)
        os.makedirs(os.path.join(CACHE_DIR, "icons"), exist_ok=True)
        pm.save(os.path.join(CACHE_DIR, "icons", key + ".png"), "PNG")
        self.favs[key] = pm
        for sv in self.views.values():
            if fav_key(sv.svc) == key:
                self.refresh_button(sv)
        if self.tname:
            self.fill_welcome()
    def shortcuts(self):
        for keys, fn in [("Ctrl+R", self.reload), ("F5", self.reload), ("Ctrl+,", self.show_prefs),
                         ("Ctrl+Shift+D", self.show_downloads), ("Ctrl+N", self.add_service_dialog),
                         ("Ctrl+=", lambda: self.zoom(0.1)), ("Ctrl++", lambda: self.zoom(0.1)),
                         ("Ctrl+-", lambda: self.zoom(-0.1)), ("Ctrl+0", lambda: self.zoom(0, True)),
                         ("Ctrl+Q", self.quit_app), ("Ctrl+Tab", lambda: self.cycle(1)),
                         ("Ctrl+Shift+Tab", lambda: self.cycle(-1))]:
            QShortcut(QKeySequence(keys), self, activated=fn)
        for i in range(9):
            QShortcut(QKeySequence("Alt+%d" % (i + 1)), self, activated=lambda n=i: self.select_index(n))

    # -- sidebar --
    def rebuild(self):
        services = self.cfg["services"]
        ids = {s["id"] for s in services}
        for sid in list(self.views):
            if sid not in ids:
                self.views.pop(sid).hibernate()
        while self.svc_layout.count():
            w = self.svc_layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.buttons = {}
        for s in services:
            sv = self.views.setdefault(s["id"], ServiceView(self, s))
            sv.svc = s
            b = SvcButton(self)
            b.clicked.connect(lambda i=s["id"]: self.select(i))
            b.menu.connect(lambda pos, i=s["id"]: self.svc_menu(i, pos))
            self.svc_layout.addWidget(b)
            self.buttons[s["id"]] = b
        for sv in self.views.values():
            self.refresh_button(sv)
        self.refresh_downloads_badge()
        self.update_unread()
    def refresh_button(self, sv):
        b = self.buttons.get(sv.id)
        if not b:
            return
        b.pm = tile_pixmap(sv.svc, 44, self.fav_pixmap(sv.svc))
        b.awake, b.active, b.unread = sv.view is not None, self.current is sv, sv.unread
        muted = not sv.svc.get("notifications", True)
        b.setToolTip("%s%s%s" % (sv.svc["name"], "" if b.awake else "  (sleeping)", "  (notifications off)" if muted else ""))
        b.update()
    def refresh_downloads_badge(self):
        self.dl_btn.count = self.downloads.active_count()
        self.dl_btn.update()
    def finished_download(self, row):
        self.refresh_downloads_badge()
        self.notifier.notify("Download finished", "%s — %s" % (os.path.basename(row.path), row.source),
                             [("open", "Open"), ("folder", "Show in folder")],
                             lambda a, p=row.path: open_local(p) if a in ("first", "open") else open_local(os.path.dirname(p)))

    # -- selection --
    def select(self, sid):
        sv = self.views.get(sid)
        if not sv:
            return
        prev, self.current = self.current, sv
        sv.load()
        self.stack.setCurrentWidget(sv.view)
        if prev and prev is not sv and prev.page and not prev.svc.get("keep_alive"):
            prev.page.setLifecycleState(QWebEnginePage.LifecycleState.Frozen)
        sv.page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
        sv.view.setFocus()
        for v in (prev, sv):
            if v:
                v.last_active = int(time.monotonic())
                self.refresh_button(v)
        self.update_title()
        st = load_json(STATE_FILE, {})
        st["last"] = sid
        save_json(STATE_FILE, st)

    def show_service(self, sid):
        self.show_window()
        self.select(sid)

    def select_index(self, i):
        if 0 <= i < len(self.cfg["services"]):
            self.select(self.cfg["services"][i]["id"])

    def cycle(self, d):
        ids = [s["id"] for s in self.cfg["services"]]
        if ids and self.current:
            self.select(ids[(ids.index(self.current.id) + d) % len(ids)])

    def reload(self):
        if self.current and self.current.view:
            self.current.view.reload()

    def zoom(self, delta, reset=False):
        sv = self.current
        if not sv or not sv.view:
            return
        z = 1.0 if reset else max(0.5, min(3.0, round(sv.view.zoomFactor() + delta, 2)))
        for v in self.views.values():
            if v.view:
                v.view.setZoomFactor(z)
        self.cfg["zoom"] = z
        self.save()

    def update_title(self):
        sv = self.current
        self.setWindowTitle("%s%s — %s" % ("(%d) " % sv.unread if sv and sv.unread else "",
                                           sv.svc["name"] if sv else APP_NAME, APP_NAME))

    def update_unread(self):
        total = sum(v.unread for v in self.views.values() if v.svc.get("notifications", True))
        if self.tray:
            self.tray.setToolTip("%s — %d unread" % (APP_NAME, total) if total else APP_NAME)
            self.tray.setIcon(self.tray_icon(total))

    def check_update(self):
        """Background: compare with the latest GitHub release (tags like v0.5.1)."""
        try:
            req = urllib.request.Request("https://api.github.com/repos/%s/releases/latest" % REPO,
                                         headers={"User-Agent": APP_SLUG})
            data = json.load(urllib.request.urlopen(req, timeout=10))
            tag = data["tag_name"].lstrip("v")
            newer = tuple(int(x) for x in tag.split(".")) > tuple(int(x) for x in VERSION.split("."))
            if newer and load_json(STATE_FILE, {}).get("update_notified") != tag:
                self.update_found.emit(tag, data.get("html_url", "https://github.com/%s/releases" % REPO))
        except (OSError, ValueError, KeyError):
            pass

    def on_update_found(self, tag, url):
        st = load_json(STATE_FILE, {})
        st["update_notified"] = tag
        save_json(STATE_FILE, st)
        self.notifier.notify("%s %s is available" % (APP_NAME, tag), "You have %s. Click to open the download page." % VERSION,
                             [("open", "Download")], lambda _a: open_url(url), timeout=15000)

    def tray_icon(self, n):
        base = self.icon.pixmap(64, 64)
        if not n or base.isNull():
            return self.icon
        pm = QPixmap(base)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#e53935"))
        p.setPen(QPen(QColor("white"), 3))
        p.drawEllipse(QRectF(pm.width() * 0.5, 0, pm.width() * 0.5, pm.height() * 0.5))
        p.end()
        return QIcon(pm)

    def build_tray_menu(self):
        """Tray: jump to a service (with unread count) and choose which apps may notify you."""
        m = self.tray_menu
        m.clear()
        m.addAction("Show %s" % APP_NAME, self.show_window)
        m.addSeparator()
        for s in self.cfg["services"]:
            sv = self.views.get(s["id"])
            n = sv.unread if sv else 0
            act = m.addAction(QIcon(tile_pixmap(s, 20, self.fav_pixmap(s))),
                              "%s%s" % (s["name"], "   (%d)" % n if n else ""))
            act.triggered.connect(lambda _c, i=s["id"]: self.show_service(i))
        m.addSeparator()
        sub = m.addMenu("Notifications from…")
        g = sub.addAction("All notifications")
        g.setCheckable(True)
        g.setChecked(self.cfg["notifications"])
        g.toggled.connect(lambda v: (self.cfg.__setitem__("notifications", v), self.save()))
        sub.addSeparator()
        for s in self.cfg["services"]:
            a = sub.addAction(s["name"])
            a.setCheckable(True)
            a.setChecked(s.get("notifications", True))
            a.toggled.connect(lambda v, s=s: self.set_service_notifications(s, v))
        m.addAction("Downloads", self.show_downloads)
        m.addAction("Preferences", self.show_prefs)
        m.addSeparator()
        m.addAction("Quit", self.quit_app)

    def set_service_notifications(self, s, v):
        s["notifications"] = v
        self.save()
        sv = self.views.get(s["id"])
        if sv:
            self.refresh_button(sv)
        self.update_unread()
    def set_video_fullscreen(self, on, sv):
        self.showFullScreen() if on else self.showNormal()

    def start_background(self):
        """Stagger-load services that should keep running (notifications)."""
        for n, s in enumerate(self.cfg["services"], 1):
            if s.get("keep_alive") and not (self.current and self.current.id == s["id"]):
                QTimer.singleShot(2000 * n, lambda i=s["id"]: self.views[i].load() if i in self.views else None)

    def hibernate_tick(self):
        mins, now = self.cfg["hibernate_minutes"], int(time.monotonic())
        if mins:
            for sv in self.views.values():
                if sv.view and sv is not self.current and not sv.svc.get("keep_alive") and now - sv.last_active > mins * 60:
                    sv.hibernate()

    # -- service management --
    def save(self):
        save_json(CONFIG_FILE, self.cfg)

    def find(self, sid):
        return next(s for s in self.cfg["services"] if s["id"] == sid)

    def svc_menu(self, sid, pos):
        sv, s, m = self.views[sid], self.find(sid), QMenu(self)
        m.addAction("Reload", lambda: (sv.load(), sv.view.reload()))
        m.addAction("Sleep (free RAM)", sv.hibernate)
        a = m.addAction("Keep running in background")
        a.setCheckable(True)
        a.setChecked(s.get("keep_alive", False))
        a.toggled.connect(lambda v: (s.__setitem__("keep_alive", v), self.save()))
        a = m.addAction("Notifications from this app")
        a.setCheckable(True)
        a.setChecked(s.get("notifications", True))
        a.toggled.connect(lambda v: self.set_service_notifications(s, v))
        m.addSeparator()
        m.addAction("Rename…", lambda: self.rename_service(sid))
        m.addAction("Custom user agent…", lambda: self.set_user_agent(sid))
        m.addAction("Edit this service's CSS", lambda: self.open_path(os.path.join(SVC_STYLE_DIR, sid + ".css"), CSS_TEMPLATE))
        m.addAction("Move up", lambda: self.move_service(sid, -1))
        m.addAction("Move down", lambda: self.move_service(sid, 1))
        m.addAction("Remove…", lambda: self.remove_service(sid))
        m.exec(pos)
    def move_service(self, sid, d):
        sv = self.cfg["services"]
        i = next(k for k, s in enumerate(sv) if s["id"] == sid)
        if 0 <= i + d < len(sv):
            sv[i], sv[i + d] = sv[i + d], sv[i]
            self.save()
            self.rebuild()

    def rename_service(self, sid):
        s = self.find(sid)
        text, ok = QInputDialog.getText(self, "Rename", "Name:", text=s["name"])
        if ok and text.strip():
            s["name"] = text.strip()
            self.save()
            self.rebuild()

    def set_user_agent(self, sid):
        """Per-service user-agent override (empty = engine default). Your call; use only if a site rejects the engine."""
        s = self.find(sid)
        text, ok = QInputDialog.getText(self, "Custom user agent",
                                        "Leave empty for the default (Chromium %s).\nApplies after the service reloads:"
                                        % (re.search(r"Chrome/(\d+)", QWebEngineProfile.defaultProfile().httpUserAgent() or "") or [0, "?"])[1],
                                        text=s.get("ua", ""))
        if ok:
            s["ua"] = text.strip()
            if not s["ua"]:
                s.pop("ua")
            self.save()
            sv = self.views[sid]
            was_current = self.current is sv
            sv.hibernate()
            if was_current:
                self.select(sid)

    def remove_service(self, sid):
        s = self.find(sid)
        if QMessageBox.warning(self, "Remove “%s”?" % s["name"],
                               "Its login and local data on this computer will be deleted.\n"
                               "The account itself is not affected.",
                               QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
                               ) != QMessageBox.StandardButton.Ok:
            return
        self.views[sid].hibernate()
        self.cfg["services"] = [x for x in self.cfg["services"] if x["id"] != sid]
        for base in (DATA_DIR, CACHE_DIR):
            shutil.rmtree(os.path.join(base, "services", sid), ignore_errors=True)
        self.save()
        if self.current and self.current.id == sid:
            self.current = None
        self.rebuild()
        if self.cfg["services"]:
            self.select(self.cfg["services"][0]["id"])
        else:
            self.stack.setCurrentWidget(self.welcome)

    def add_service_dialog(self):
        self.show_window()
        dlg = QDialog(self)
        dlg.setWindowTitle("Add service")
        dlg.resize(560, 470)
        lay = QVBoxLayout(dlg)
        keys = list(PRESETS)
        lst = QListWidget()
        lst.setViewMode(QListView.ViewMode.IconMode)
        lst.setIconSize(QSize(52, 52))
        lst.setGridSize(QSize(100, 92))
        lst.setResizeMode(QListView.ResizeMode.Adjust)
        lst.setMovement(QListView.Movement.Static)
        lst.setSpacing(4)
        lst.setFrameShape(QFrame.Shape.NoFrame)
        for k in keys:
            svc = {"preset": k, "color": PRESETS[k][2], "id": k}
            it = QListWidgetItem(QIcon(tile_pixmap(svc, 52, self.fav_pixmap(svc))), PRESETS[k][0])
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            lst.addItem(it)
        lst.setCurrentRow(0)
        lay.addWidget(lst, 1)
        form = QFormLayout()
        name, url = QLineEdit(), QLineEdit(PRESETS[keys[0]][1])
        name.setPlaceholderText("auto — e.g. Gmail work")
        lst.currentRowChanged.connect(lambda i: url.setText(PRESETS[keys[i]][1]) if i >= 0 else None)
        form.addRow("Name", name)
        form.addRow("URL", url)
        lay.addLayout(form)
        note = QLabel("Every added service has its own separate login, so you can add the same one several times.")
        note.setWordWrap(True)
        note.setStyleSheet("color:%s" % self.t["muted"])
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec():
            u = url.text().strip()
            if u and "://" not in u:
                u = "https://" + u
            svc = make_service(keys[max(0, lst.currentRow())], name.text().strip() or None, u or None, self.cfg["services"])
            self.cfg["services"].append(svc)
            self.save()
            self.rebuild()
            self.select(svc["id"])
    def show_prefs(self):
        self.show_window()
        dlg = Prefs(self)
        if dlg.exec():
            self.cfg.update(dlg.values())
            self.save()
            self.restart()

    def restart(self):
        QProcess.startDetached("sh", ["-c", 'sleep 1; exec "$0" "$1"', sys.executable, os.path.abspath(sys.argv[0])])
        self.quit_app()

    @staticmethod
    def open_path(path, template=None):
        if template is not None:
            read_text(path, template)
        elif not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        open_local(path)

    # -- window --
    def show_window(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def show_downloads(self):
        self.downloads.show()
        self.downloads.raise_()
        self.downloads.activateWindow()

    def save_state(self):
        st = load_json(STATE_FILE, {})
        if not self.isMaximized() and not self.isFullScreen():
            st.update({"w": self.width(), "h": self.height()})
        st["max"] = self.isMaximized()
        save_json(STATE_FILE, st)

    def closeEvent(self, ev):
        self.save_state()
        if self.cfg["close_to_tray"] and self.tray and not self.really_quit:
            ev.ignore()
            self.hide()
        else:
            ev.accept()
            QApplication.quit()

    def quit_app(self):
        self.really_quit = True
        self.save_state()
        QApplication.quit()


def run(args, cfg):
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(ICON_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    global DPR
    DPR = max(1.0, app.primaryScreen().devicePixelRatio())

    # single instance: a second launch just raises the first
    instance = os.environ.get("TESSERA_INSTANCE", APP_ID)     # override only for side-by-side testing
    sock = QLocalSocket()
    sock.connectToServer(instance)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(500)
        return 0
    QLocalServer.removeServer(instance)
    server = QLocalServer()
    server.listen(instance)

    if not cfg["services"]:
        cfg["services"] = [make_service("whatsapp")]
    save_json(CONFIG_FILE, cfg)
    hub = Hub(args, cfg)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), hub.show_window()))
    ids = [s["id"] for s in cfg["services"]]
    last = load_json(STATE_FILE, {}).get("last")
    hub.select(last if last in ids else ids[0])
    hub.start_background()
    shot = os.environ.get("TESSERA_SHOT")
    if shot:      # developer aid: save window screenshots (current theme, then toggled) and quit
        def snap(n):
            hub.grab().save("%s-%d.png" % (shot, n))
        QTimer.singleShot(9000, lambda: snap(1))
        QTimer.singleShot(9500, hub.toggle_theme)
        QTimer.singleShot(11000, lambda: snap(2))
        QTimer.singleShot(12000, hub.add_service_dialog)
        QTimer.singleShot(14000, lambda: QApplication.activeModalWidget().grab().save("%s-3.png" % shot))
        QTimer.singleShot(14500, lambda: QApplication.activeModalWidget().reject())
        QTimer.singleShot(15500, QApplication.quit)
    if args.minimized or cfg["start_minimized"]:
        if not hub.tray:
            hub.showMinimized()
    else:
        hub.showMaximized() if hub.start_max else hub.show()
    return app.exec()


def main():
    p = argparse.ArgumentParser(prog=APP_SLUG, description=__doc__.split("\n")[0])
    p.add_argument("--minimized", action="store_true", help="start hidden in tray")
    p.add_argument("--debug", action="store_true", help="log capabilities; devtools on http://localhost:9222")
    p.add_argument("--reset", action="store_true", help="forget ALL logins & caches, then exit")
    p.add_argument("--version", action="version", version=VERSION)
    args = p.parse_args()
    if args.reset:
        for d in (DATA_DIR, CACHE_DIR):
            shutil.rmtree(d, ignore_errors=True)
        print("%s data cleared (config kept in %s)" % (APP_NAME, CONFIG_DIR))
        return 0
    migrate_legacy()
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg.update(load_json(CONFIG_FILE, {}))
    apply_chromium_flags(cfg)
    if args.debug:
        os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = "9222"
    return run(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
