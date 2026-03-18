"""QMK Keyboard Visualizer - Entry point."""

import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen, QWidget

from keyboard_visualizer.ui import MainWindow


BASE_DIR = Path(__file__).resolve().parent
RESOURCES_DIR = BASE_DIR / "keyboard_visualizer" / "resources"
STYLESHEET_PATH = RESOURCES_DIR / "styles.qss"
SPLASH_IMAGE_PATH = RESOURCES_DIR / "images" / "charybdis_nano_photo.jpg"


def _apply_stylesheet(app: QApplication) -> None:
    """Apply the bundled stylesheet when available."""
    if not STYLESHEET_PATH.exists():
        return

    app.setStyleSheet(STYLESHEET_PATH.read_text(encoding="utf-8"))
    app.setStyle("Fusion")


def _create_splash() -> QSplashScreen | None:
    """Create a splash screen from the bundled Charybdis photo."""
    if not SPLASH_IMAGE_PATH.exists():
        return None

    splash_pixmap = QPixmap(str(SPLASH_IMAGE_PATH))
    if splash_pixmap.isNull():
        return None

    splash_pixmap = splash_pixmap.scaled(
        920,
        560,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    splash = QSplashScreen(
        splash_pixmap,
        Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint,
    )
    splash.setFont(QFont("Segoe UI", 12))
    splash.showMessage(
        "Loading QMK Keyboard Visualizer...",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#f3efe8"),
    )
    return splash


def _resolve_startup_screen() -> object | None:
    """Choose a startup screen without showing the main window first."""
    cursor_pos = QCursor.pos()
    screen = QApplication.screenAt(cursor_pos)
    if screen is None:
        screen = QApplication.primaryScreen()
    return screen


def _center_widget_on_screen(widget: QWidget, screen) -> None:
    """Center a widget on the given screen."""
    if screen is None:
        return

    available = screen.availableGeometry()
    rect = widget.frameGeometry()
    widget.move(
        available.center().x() - rect.width() // 2,
        available.center().y() - rect.height() // 2,
    )


def _position_main_window(window: MainWindow, screen) -> None:
    """Place the main window on the chosen screen before showing it."""
    if screen is None:
        return

    available = screen.availableGeometry()
    desired = window.size()
    if desired.width() <= 0 or desired.height() <= 0:
        desired = window.sizeHint()
    width = min(max(desired.width(), window.minimumWidth()), available.width())
    height = min(max(desired.height(), window.minimumHeight()),
                 available.height())
    window.resize(width, height)
    _center_widget_on_screen(window, screen)


def main() -> int:
    """Application entry point."""
    # High DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _apply_stylesheet(app)

    window = MainWindow()
    splash = _create_splash()
    splash_started_at = time.monotonic()
    startup_screen = _resolve_startup_screen()
    _position_main_window(window, startup_screen)
    app.processEvents()

    if splash is not None:
        _center_widget_on_screen(splash, startup_screen)
        splash.show()
        app.processEvents()

    if splash is not None:
        app.processEvents()
        elapsed = time.monotonic() - splash_started_at
        min_duration = 2.0
        if elapsed < min_duration:
            time.sleep(min_duration - elapsed)
    window.show()
    app.processEvents()
    if splash is not None:
        splash.finish(window)
    window.raise_()
    window.activateWindow()
    window.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
    QTimer.singleShot(0, window.raise_)
    QTimer.singleShot(0, window.activateWindow)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
