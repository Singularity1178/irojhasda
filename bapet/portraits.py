"""Flat roster images. Browsing never opens a GLB or requests a renderer."""
from __future__ import annotations

import hashlib
import json
import os
from collections import OrderedDict
from pathlib import Path

from PySide6 import QtCore, QtGui


class Portraits:
    def __init__(self):
        folder = Path(__file__).parent / "data"
        self.atlas = QtGui.QImage(str(folder / "roster.png"))
        try:
            self.index = json.loads((folder / "roster.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.index = {}
        cache = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.GenericCacheLocation)
        self.folder = Path(cache) / "irojhasda" / "portraits-v1"
        self.recent = OrderedDict()
        self.keys = {}

    def _key(self, slot):
        if slot not in self.keys:
            try:
                st = slot.path.stat()
                stamp, size = st.st_mtime_ns, st.st_size
            except OSError:
                stamp, size = 0, -1
            key = hashlib.sha256(f"{slot.path}:{stamp}:{size}:{slot.profile!r}".encode()).hexdigest()
            self.keys[slot] = self.folder / (key + ".png"), size
        return self.keys[slot]

    def _builtin(self, slot):
        row = self.index.get(slot.path.name)
        return row if row and row[0] == self._key(slot)[1] and not self.atlas.isNull() else None

    def has(self, slot):
        return bool(self._builtin(slot)) or self._key(slot)[0].is_file()

    def _keep(self, slot, image):
        self.recent[slot] = image
        self.recent.move_to_end(slot)
        while len(self.recent) > 48:
            self.recent.popitem(last=False)
        return image

    def image(self, slot):
        if slot in self.recent:
            self.recent.move_to_end(slot)
            return self.recent[slot]
        path, _ = self._key(slot)
        img = QtGui.QImage(str(path)) if path.is_file() else QtGui.QImage()
        if img.isNull():
            row = self._builtin(slot)
            if row:
                img = self.atlas.copy(*row[1:])
        if img.isNull():
            img = QtGui.QImage(144, 144, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(QtCore.Qt.GlobalColor.transparent)
            p = QtGui.QPainter(img)
            p.setPen(QtGui.QColor("#7796b8"))
            f = p.font(); f.setPixelSize(49); f.setBold(True); p.setFont(f)
            p.drawText(img.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, slot.name[:2].upper()); p.end()
        return self._keep(slot, img)

    def save(self, slot, img):
        self._keep(slot, img)
        path, _ = self._key(slot)
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(f".{os.getpid()}.tmp")
            if img.save(str(temp), "PNG"):
                os.replace(temp, path)
            files = sorted(self.folder.glob("*.png"), key=lambda p: p.stat().st_mtime_ns)
            for old in files[:-256]:
                old.unlink(missing_ok=True)
        except OSError:
            pass  # A read-only or shared cache must never prevent deployment.