#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

from PySide6.QtWidgets import QApplication

from .main_window import QtMainWindow
from .theme import build_stylesheet


def run_qt_app() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet())
    window = QtMainWindow()
    window.show()
    return app.exec()
