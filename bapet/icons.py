"""make_icon: the tray / window icon."""
from __future__ import annotations

from PySide6 import QtGui
from PySide6.QtCore import QRectF, Qt


# =============================================================================
#  Application glue
# =============================================================================
def make_icon(letter="A"):
    pm = QtGui.QPixmap(64, 64); pm.fill(Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    g = QtGui.QLinearGradient(0, 0, 64, 64); g.setColorAt(0, QtGui.QColor("#35b6ff")); g.setColorAt(1, QtGui.QColor("#0b4fb3"))
    p.setBrush(QtGui.QBrush(g)); p.setPen(QtGui.QPen(QtGui.QColor("white"), 3)); p.drawEllipse(4, 4, 56, 56)
    p.setPen(QtGui.QColor("white")); f = QtGui.QFont("Arial", 28, QtGui.QFont.Weight.Bold); p.setFont(f)
    p.drawText(QRectF(0, 0, 64, 62), int(Qt.AlignmentFlag.AlignCenter.value), (letter or "A")[:1].upper()); p.end()
    return QtGui.QIcon(pm)
