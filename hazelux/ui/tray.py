"""System tray integration via pystray and StatusNotifierWatcher discovery."""

import logging
import os
import threading
from typing import Any, Callable, Optional

from PIL import Image, ImageDraw

logger = logging.getLogger("hazelux.ui.tray")


def is_status_notifier_watcher_present() -> bool:
    """Check if org.kde.StatusNotifierWatcher is registered on the session D-Bus."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            None,
        )
        names = proxy.call_sync(
            "ListNames",
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        ).unpack()[0]
        return "org.kde.StatusNotifierWatcher" in names
    except Exception as e:
        logger.debug("D-Bus query for StatusNotifierWatcher failed: %s", e)
        return False


def create_tray_icon_image() -> Image.Image:
    """Generate default hazel/file automation icon for system tray."""
    img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Draw simple stylized folder / hazel symbol
    draw.rounded_rectangle([8, 14, 56, 52], radius=8, fill=(46, 125, 50, 255))
    draw.rounded_rectangle([8, 8, 32, 20], radius=4, fill=(56, 142, 60, 255))
    draw.ellipse([24, 24, 40, 40], fill=(255, 255, 255, 230))
    return img


class TrayManager:
    """Manages pystray StatusNotifierItem presence and callbacks."""

    def __init__(
        self,
        on_toggle_window: Callable[[], None],
        on_pause_toggle: Callable[[], bool],
        on_run_rules_now: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        self.on_toggle_window = on_toggle_window
        self.on_pause_toggle = on_pause_toggle
        self.on_run_rules_now = on_run_rules_now
        self.on_quit = on_quit
        self.icon: Optional[Any] = None
        self._is_paused = False

    def setup_tray(self) -> bool:
        """Attempt to register StatusNotifierItem icon in system tray.

        Returns True if tray was successfully initialized, False otherwise.
        """
        # Ensure StatusNotifierWatcher exists on session bus
        if not is_status_notifier_watcher_present():
            logger.info("org.kde.StatusNotifierWatcher not present on D-Bus; tray disabled.")
            return False

        try:
            # Set backend fallback to xorg if appindicator raises GTK conflicts
            if "PYSTRAY_BACKEND" not in os.environ:
                os.environ["PYSTRAY_BACKEND"] = "appindicator"

            import pystray
        except Exception as e:
            logger.warning("Could not import pystray: %s; falling back to window-only mode.", e)
            return False

        try:
            img = create_tray_icon_image()

            def get_pause_label(item):
                return "Resume Automations" if self._is_paused else "Pause Automations"

            def on_pause_clicked(icon, item):
                self._is_paused = self.on_pause_toggle()
                icon.update_menu()

            menu = pystray.Menu(
                pystray.MenuItem("Open Hazelux", lambda icon, item: self.on_toggle_window(), default=True),
                pystray.MenuItem(get_pause_label, on_pause_clicked),
                pystray.MenuItem("Run Rules Now", lambda icon, item: self.on_run_rules_now()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit Hazelux", lambda icon, item: self.on_quit()),
            )

            self.icon = pystray.Icon("hazelux", img, "Hazelux", menu)

            # Run pystray loop in background thread
            tray_thread = threading.Thread(target=self.icon.run, daemon=True, name="hazelux-tray")
            tray_thread.start()
            logger.info("System tray initialized successfully.")
            return True
        except Exception as ex:
            logger.warning("Failed initializing system tray icon: %s", ex)
            return False

    def stop(self) -> None:
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
