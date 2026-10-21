"""Sora's shop: the Spine 3.8 lobby background (sora_shop.skel / .atlas), fully rigged and animated.

The scene is rendered by the Spine 3.8 WebGL runtime (assets/spine-webgl.js, the same one the Spine
folder viewer uses) inside a QtWebEngine view. A tiny localhost server hands the page and the Spine
files to the view, and receives the page's back button (POST /__back). Everything lives in
babattlearena/assets/ (the localize/ folder of the original export is deliberately not used).

    * the arrival clip plays, then Idle_01 loops
    * her eyes follow the cursor (Touch_Eye_Key), her head and halo sway a little (Touch_Point_Key)
    * hold the left button on her head to pat her (Pat_01_M, released with PatEnd_01_A / _M)
    * tap her to make her talk (Talk_01..07, mouth + body clips); voice lines play if the .wav files
      are dropped into assets/sora_shop/ (they are not part of the repo's copy of the export)
    * the round dark-blue arrow in the top left corner (or Esc) goes back to the main menu
"""
from __future__ import annotations

import json
import mimetypes
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import QObject, Qt, QUrl, Signal

ASSETS = Path(__file__).resolve().parent / "assets"
SHOP_DIR = ASSETS / "sora_shop"
PAGE = "sora_shop.html"
AUDIO_EXT = (".wav", ".mp3", ".ogg", ".m4a")
mimetypes.add_type("application/octet-stream", ".skel")
mimetypes.add_type("text/plain", ".atlas")


class _Bridge(QObject):
    back = Signal()


def _make_handler(bridge):
    root = ASSETS.resolve()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):            # keep the console quiet
            pass

        def _send(self, code, body=b"", ctype="text/plain", head=False):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            if urlparse(self.path).path == "/__back":
                bridge.back.emit()
                self._send(204)
            else:
                self._send(404)

        def do_GET(self, head=False):
            path = unquote(urlparse(self.path).path)
            if path == "/__audio":
                names = [p.name for p in SHOP_DIR.iterdir() if p.suffix.lower() in AUDIO_EXT] if SHOP_DIR.is_dir() else []
                return self._send(200, json.dumps(names).encode(), "application/json", head)
            rel = path.lstrip("/") or PAGE
            f = (root / rel).resolve()
            if root not in f.parents or not f.is_file():
                return self._send(404, b"not found", head=head)
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if ctype.startswith("text/html") or f.suffix == ".js":
                ctype += "; charset=utf-8"
            self._send(200, f.read_bytes(), ctype, head)

        def do_HEAD(self):
            self.do_GET(head=True)

    return Handler


class SoraShop(QtWidgets.QWidget):
    """Frameless window with the shop scene. Back (button in the page, or Esc) returns to the main menu."""

    BASE_W, BASE_H = 1180, 720

    def __init__(self, mgr):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window
        super().__init__(None, flags)
        self.mgr = mgr
        self.app = mgr.app
        self.setWindowTitle("Sora's Shop - Blue Archive")
        try:
            tray = getattr(self.app, "tray", None)
            if tray is not None:
                self.setWindowIcon(tray.icon())
        except Exception:
            pass
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
        self._bridge = _Bridge()
        self._bridge.back.connect(self.go_back)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self._bridge))
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, name="sora-shop-http", daemon=True).start()
        self._base = f"http://127.0.0.1:{self._server.server_address[1]}"
        self.view = QWebEngineView(self)
        s = self.view.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        self.view.page().setBackgroundColor(QtGui.QColor(207, 230, 247))
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        QtGui.QShortcut(QtGui.QKeySequence(Qt.Key.Key_Escape), self, activated=self.go_back)
        self._loaded = False
        self.app.qapp.aboutToQuit.connect(self._server.shutdown)

    # ------------------------------------------------------------------ open / close
    def open(self, center=None):
        try:
            g = self.app.resolve_screen()
        except Exception:
            g = self.app.qapp.primaryScreen().availableGeometry()
        w = int(min(self.BASE_W, g.width() * 0.96))
        h = int(min(self.BASE_H, g.height() * 0.95))
        self.resize(w, h)
        c = center if center is not None else g.center()
        self.move(c.x() - w // 2, c.y() - h // 2)
        self.show()
        self.raise_()
        self.activateWindow()
        if not self._loaded:
            self._loaded = True
            self.view.load(QUrl(f"{self._base}/{PAGE}"))
        else:
            self.view.page().runJavaScript("window.shopEnter && window.shopEnter()")
        self.view.setFocus()

    def go_back(self):
        if self.isVisible():
            self.mgr.close_shop()

    def hideEvent(self, ev):
        try:
            self.view.page().runJavaScript("window.shopLeave && window.shopLeave()")
        except Exception:
            traceback.print_exc()
        super().hideEvent(ev)

    def closeEvent(self, ev):
        ev.ignore()
        self.go_back()
