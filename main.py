#!/usr/bin/env python3
"""
FanLight Studio - Fan & Hardware RGB Controller
Motherboard: MSI B650M GAMING WIFI (MS-7E30)
"""

import sys
import os

# Ensure current directory is in sys.path
app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt
from ui import FanLightApp


def main():
    # Setup High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("FanLight Studio")
    app.setApplicationDisplayName("FanLight Studio")
    app.setDesktopFileName("FanLightControl")

    icon_path = os.path.join(app_dir, "assets", "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = FanLightApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
