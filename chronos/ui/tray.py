"""System tray icon with balloon notifications and a Show/Quit context menu."""
from PyQt5 import QtGui, QtWidgets


def build_tray_icon(window: QtWidgets.QMainWindow) -> QtWidgets.QSystemTrayIcon:
    icon = window.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)
    tray = QtWidgets.QSystemTrayIcon(icon, window)
    tray.setToolTip("Chronos — Power Cycle Test & Recovery Verifier")

    menu = QtWidgets.QMenu()
    show_action = menu.addAction("顯示視窗")
    show_action.triggered.connect(window.showNormal)
    quit_action = menu.addAction("結束")
    quit_action.triggered.connect(QtWidgets.QApplication.quit)
    tray.setContextMenu(menu)

    def on_activated(reason):
        if reason == QtWidgets.QSystemTrayIcon.DoubleClick:
            window.showNormal()
            window.raise_()
            window.activateWindow()

    tray.activated.connect(on_activated)
    tray.show()
    return tray


def notify(tray: QtWidgets.QSystemTrayIcon, title: str, message: str,
           icon=QtWidgets.QSystemTrayIcon.Information) -> None:
    tray.showMessage(title, message, icon, 8000)
