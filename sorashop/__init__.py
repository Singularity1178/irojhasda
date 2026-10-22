"""sorashop - Sora's shop, opened from the shop icon on the Battle Arena title screen.

    shop      SoraShop: frameless window with the Spine 3.8 lobby scene in a QtWebEngine view
              (import it as `from sorashop.shop import SoraShop`; it needs PySide6 with QtWebEngine)
    assets/   everything the page loads: sora_shop.html, shop_ui.js + shop_ui.css (the shop screen drawn over
              the scene), spine-webgl.js, the sora_shop/ Spine export, and MP_Shop.png (the title screen icon)

This module stays free of Qt imports so the title screen can read ICON_PATH without pulling in the web view.
"""
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ICON_PATH = ASSETS_DIR / "MP_Shop.png"
