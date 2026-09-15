"""Hazelux Gtk.Application entry point and daemon lifecycle coordinator."""

import argparse
import asyncio
import logging
import os
from pathlib import Path
import sys
import threading
from typing import Optional

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Adw, Gio, GLib, Gtk

from hazelux import __app_id__, __version__
from hazelux.config import ConfigManager
from hazelux.engine.runner import RuleEngine
from hazelux.journal.manager import JournalManager
from hazelux.journal.reconcile import reconcile_journal_on_startup
from hazelux.ui.about import show_about_window
from hazelux.ui.tray import TrayManager
from hazelux.ui.window import MainWindow
from hazelux.utils.paths import get_journal_db_path, get_rules_path

logger = logging.getLogger("hazelux")


class HazeluxApplication(Adw.Application):
    """Main Gtk.Application coordinator for Hazelux."""

    def __init__(self, start_in_background: bool = False):
        super().__init__(
            application_id=__app_id__,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.start_in_background = start_in_background
        self.config_manager = ConfigManager(get_rules_path())
        self.journal_manager = JournalManager(get_journal_db_path())
        self.rule_engine: Optional[RuleEngine] = None
        self.tray_manager: Optional[TrayManager] = None
        self.main_window: Optional[MainWindow] = None

        # Asyncio background loop for watchfiles
        self._async_loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_thread: Optional[threading.Thread] = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        Adw.init()

        # 1. Startup crash reconciliation & journal pruning
        try:
            db_path = get_journal_db_path()
            reconcile_journal_on_startup(db_path)
            self.journal_manager.prune_and_vacuum()
        except Exception as e:
            logger.error("Error during startup crash reconciliation: %s", e)

        # 2. Initialize RuleEngine with cascading loop toast handler
        self.rule_engine = RuleEngine(
            config_manager=self.config_manager,
            journal_manager=self.journal_manager,
            on_loop_suspect=self._on_cascading_loop_detected,
        )

        # 3. Load initial configuration
        is_valid, errors = self.config_manager.load()
        if not is_valid:
            logger.warning("Configuration invalid on startup: %s", errors)

        # 4. Start asyncio event loop in dedicated worker thread for watchfiles
        self._start_async_worker()

        # 5. Register config reload hook to restart watching when rules change
        self.config_manager.register_reload_callback(self._on_rules_reloaded)

        # 6. Initialize System Tray presence
        self.tray_manager = TrayManager(
            on_toggle_window=self._toggle_window_visibility,
            on_pause_toggle=self._toggle_engine_pause,
            on_run_rules_now=self._run_all_rules_now,
            on_quit=self._quit_application,
        )
        tray_started = self.tray_manager.setup_tray()

        # If tray could not be started and user did not explicitly request background, ensure window presents
        if not tray_started:
            self.start_in_background = False

        # 7. Application actions
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

    def _start_async_worker(self) -> None:
        """Run asyncio event loop in dedicated background thread."""
        def run_loop():
            self._async_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._async_loop)
            # Start directory watchers if configuration is valid
            if self.config_manager.is_valid and self.rule_engine:
                dirs = self.rule_engine.get_monitored_directories()
                if dirs:
                    asyncio.run_coroutine_threadsafe(
                        self.rule_engine.watcher.start_watching(dirs),
                        self._async_loop,
                    )
            self._async_loop.run_forever()

        self._async_thread = threading.Thread(target=run_loop, daemon=True, name="hazelux-async")
        self._async_thread.start()

    def _on_rules_reloaded(self, _config) -> None:
        """Restart watchers when rules configuration changes."""
        if not self._async_loop or not self.rule_engine:
            return
        if self.config_manager.is_valid:
            dirs = self.rule_engine.get_monitored_directories()
            asyncio.run_coroutine_threadsafe(
                self.rule_engine.watcher.start_watching(dirs),
                self._async_loop,
            )
        else:
            # Stop watching if configuration became invalid
            asyncio.run_coroutine_threadsafe(
                self.rule_engine.watcher.stop(),
                self._async_loop,
            )

    def do_activate(self) -> None:
        """Handle primary or secondary instance activation."""
        if not self.main_window:
            self.main_window = MainWindow(
                application=self,
                config_manager=self.config_manager,
                journal_manager=self.journal_manager,
                rule_engine=self.rule_engine,
                tray_active=self.tray_manager.is_active if self.tray_manager else False,
            )

        if self.start_in_background:
            # First launch was background; don't show window yet
            self.start_in_background = False
            return

        if not self.main_window.get_visible():
            self.main_window.present()
        else:
            self.main_window.present()

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        """Handle CLI arguments from primary or secondary invocations."""
        args = command_line.get_arguments()
        is_bg = "--background" in args or "-b" in args

        if is_bg and not self.main_window:
            self.start_in_background = True

        self.activate()
        return 0

    def _toggle_window_visibility(self) -> None:
        GLib.idle_add(self._idle_toggle_window)

    def _idle_toggle_window(self) -> None:
        if not self.main_window:
            self.do_activate()
            return
        if self.main_window.get_visible():
            self.main_window.set_visible(False)
        else:
            self.main_window.present()

    def _toggle_engine_pause(self) -> bool:
        if not self.rule_engine:
            return False
        if self.rule_engine.is_paused():
            self.rule_engine.resume()
            if self.main_window:
                GLib.idle_add(self.main_window.show_toast, "Automation resumed.")
            return False
        else:
            self.rule_engine.pause()
            if self.main_window:
                GLib.idle_add(self.main_window.show_toast, "Automation paused.")
            return True

    def _run_all_rules_now(self) -> None:
        if not self.rule_engine:
            return
        dirs = self.rule_engine.get_monitored_directories()
        for d in dirs:
            threading.Thread(
                target=self.rule_engine.run_rules_on_directory,
                args=(Path(d), True),
                daemon=True,
            ).start()
        if self.main_window:
            GLib.idle_add(self.main_window.show_toast, "Running all rules now...")

    def _on_cascading_loop_detected(self, inode: int, path: Path) -> None:
        msg = f"Loop Suspect: {path.name} triggered >5 actions in 60s. Automation suspended."
        logger.error(msg)
        if self.main_window:
            GLib.idle_add(self.main_window.show_toast, msg)

    def _on_about(self, _action, _param) -> None:
        """Present the About / credits window."""
        if not self.main_window:
            self.do_activate()
        show_about_window(self.main_window)

    def _quit_application(self) -> None:
        if self.tray_manager:
            self.tray_manager.stop()
        if self._async_loop:
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)
        self.quit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Hazelux: Native Linux desktop file automation")
    parser.add_argument("--background", "-b", action="store_true", help="Launch daemon in background without UI")
    parser.add_argument("--version", "-v", action="version", version=f"Hazelux {__version__}")
    args, unknown = parser.parse_known_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = HazeluxApplication(start_in_background=args.background)
    sys.exit(app.run([sys.argv[0]] + unknown))


if __name__ == "__main__":
    main()
