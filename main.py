from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
import sys

import elements.menu as menu

if  __name__ == "__main__":
    # Minimal imports; show splash screen
    app = QApplication(sys.argv)
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    pixmap = QPixmap("assets/newey.png")
    splash = QSplashScreen(pixmap)
    splash.show()
    splash.raise_()
    splash.activateWindow()
    app.processEvents()
    
    window = menu.MainWindow()
    window.show()
    window.canvas.zoom_to_network()
    window.canvas.render()
    splash.finish(window)
    sys.exit(app.exec())
