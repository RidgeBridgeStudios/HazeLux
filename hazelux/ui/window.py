"""Main application window using GTK4, Libadwaita, Adw.NavigationSplitView, and Adw.ToastOverlay."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GLib", "2.0")
from gi.repository import Adw, GLib, Gtk

from hazelux.config import ConfigManager
from hazelux.engine.runner import RuleEngine
from hazelux.journal.manager import JournalManager
from hazelux.ui.activity import RecentActivityGroup
from hazelux.ui.rule_editor import RuleExpanderRow
from hazelux.ui.sidebar import SidebarView
from hazelux.utils.inotify_limits import check_inotify_watch_limit, estimate_directory_watches

logger = logging.getLogger("hazelux.ui.window")


class MainWindow(Adw.ApplicationWindow):
    """Primary Hazelux desktop configuration and monitoring window."""

    def __init__(
        self,
        application: Adw.Application,
        config_manager: ConfigManager,
        journal_manager: JournalManager,
        rule_engine: RuleEngine,
    ):
        super().__init__(application=application, title="Hazelux")
        self.config_manager = config_manager
        self.journal_manager = journal_manager
        self.rule_engine = rule_engine

        self.set_default_size(1050, 720)
        self.connect("close-request", self._on_close_request)

        # Style manager integration for dark/accent mode tracking
        self.style_manager = Adw.StyleManager.get_default()

        # Root Toast Overlay
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # Primary Navigation Split View
        self.split_view = Adw.NavigationSplitView()
        self.split_view.set_collapsed(False)
        self.split_view.set_min_sidebar_width(260)
        self.toast_overlay.set_child(self.split_view)

        # 1. Master Sidebar
        self.sidebar = SidebarView(
            on_folder_selected=self._on_folder_selected,
            on_add_folder=self._on_add_folder,
            on_folder_active_toggled=self._on_folder_active_toggled,
            on_folder_removed=self._on_folder_removed,
        )
        self.split_view.set_sidebar(self.sidebar)

        # 2. Detail Content Page
        self.detail_page = Adw.NavigationPage(title="Folder Automation Rules")
        self.detail_toolbar_view = Adw.ToolbarView()
        self.detail_page.set_child(self.detail_toolbar_view)
        self.split_view.set_content(self.detail_page)

        # Detail Top Bar
        detail_header = Adw.HeaderBar()
        self.window_title = Adw.WindowTitle(title="Folder Automation Rules", subtitle="")
        detail_header.set_title_widget(self.window_title)

        # Manual Run button
        run_btn = Gtk.Button(icon_name="media-playback-start-symbolic")
        run_btn.set_tooltip_text("Run rules on this folder now")
        run_btn.connect("clicked", self._on_run_rules_clicked)
        detail_header.pack_start(run_btn)

        # Add Rule button
        add_rule_btn = Gtk.Button(label="Add Rule")
        add_rule_btn.add_css_class("suggested-action")
        add_rule_btn.connect("clicked", self._on_add_rule_clicked)
        detail_header.pack_end(add_rule_btn)

        self.detail_toolbar_view.add_top_bar(detail_header)

        # Detail Content Container
        detail_scrolled = Gtk.ScrolledWindow()
        clamp = Adw.Clamp(maximum_size=850)
        detail_scrolled.set_child(clamp)
        self.detail_toolbar_view.set_content(detail_scrolled)

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.main_box.set_margin_top(18)
        self.main_box.set_margin_bottom(24)
        self.main_box.set_margin_start(16)
        self.main_box.set_margin_end(16)
        clamp.set_child(self.main_box)

        # Validation Banner
        self.validation_banner = Adw.Banner(
            title="Rule configuration is invalid; automation is paused. Click to review."
        )
        self.validation_banner.set_button_label("Review")
        self.validation_banner.connect("button-clicked", self._on_validation_banner_clicked)
        self.main_box.append(self.validation_banner)

        # Inotify Limit Warning Banner
        self.inotify_banner = Adw.Banner(
            title="Approaching system inotify watch limit (>80%). Increase fs.inotify.max_user_watches."
        )
        self.main_box.append(self.inotify_banner)

        # Section 1: Rules PreferencesGroup
        self.rules_group = Adw.PreferencesGroup(title="Rules")
        self.rules_list = Gtk.ListBox()
        self.rules_list.add_css_class("boxed-list")
        self.rules_group.add(self.rules_list)
        self.main_box.append(self.rules_group)

        # Section 2: Recent Activity PreferencesGroup
        self.activity_group = RecentActivityGroup(
            journal_manager=self.journal_manager,
            on_toast_message=self.show_toast,
        )
        self.main_box.append(self.activity_group)

        self.selected_folder: Optional[str] = None
        self._rule_widgets: List[RuleExpanderRow] = []

        # Wire rule action executed callback to refresh activity on main thread
        self.rule_engine.on_rule_action_executed = self._on_action_executed

        # Initial UI load
        self.refresh_ui()

    def show_toast(self, message: str) -> None:
        """Display an Adw.Toast message."""
        toast = Adw.Toast(title=message)
        self.toast_overlay.add_toast(toast)

    def _on_action_executed(self, rule: Dict[str, Any], path: Path, action_type: str) -> None:
        """Called by RuleEngine in worker thread when an action occurs."""
        GLib.idle_add(self.activity_group.refresh)
        rule_name = rule.get("metadata", {}).get("name", "Rule")
        msg = f"{rule_name}: {action_type} {path.name}"
        GLib.idle_add(self.show_toast, msg)

    def _on_close_request(self, _window) -> bool:
        """Intercept window close request to hide window while daemon runs."""
        self.set_visible(False)
        return True

    def refresh_ui(self) -> None:
        """Re-read config, update sidebar, banners, and rules."""
        # 1. Update validation banner
        if not self.config_manager.is_valid:
            self.validation_banner.set_revealed(True)
        else:
            self.validation_banner.set_revealed(False)

        # 2. Update watched folders in sidebar
        folders = self.config_manager.get_watched_folders()
        if not folders and Path("~/Downloads").expanduser().exists():
            folders = [str(Path("~/Downloads").expanduser().resolve())]
        self.sidebar.set_folders(folders)

        if not self.selected_folder and folders:
            self.selected_folder = folders[0]

        # 3. Check inotify limits
        total_projected = sum(estimate_directory_watches(Path(f)) for f in folders)
        is_warn, ratio, max_w = check_inotify_watch_limit(total_projected)
        self.inotify_banner.set_revealed(is_warn)
        if is_warn:
            self.inotify_banner.set_title(
                f"Inotify capacity at {int(ratio*100)}% ({total_projected}/{max_w} watches). "
                "Consider increasing fs.inotify.max_user_watches."
            )

        self._refresh_rules_for_folder()

    def _on_folder_selected(self, folder_path: str) -> None:
        self.selected_folder = folder_path
        folder_name = Path(folder_path).name or folder_path
        self.window_title.set_subtitle(folder_name)
        self._refresh_rules_for_folder()

    def _refresh_rules_for_folder(self) -> None:
        """Populate rules for currently selected folder."""
        while row := self.rules_list.get_first_child():
            self.rules_list.remove(row)
        self._rule_widgets.clear()

        if not self.selected_folder:
            return

        norm_selected = str(Path(self.selected_folder).expanduser().resolve())
        rules = self.config_manager.get_rules()

        for r in rules:
            rule_paths = [str(Path(p).expanduser().resolve()) for p in r.get("triggers", {}).get("paths", [])]
            if norm_selected in rule_paths:
                expander = RuleExpanderRow(
                    rule_data=r,
                    target_path=self.selected_folder,
                    on_save_needed=self._save_all_rules,
                    on_delete_rule=self._on_delete_rule,
                )
                self._rule_widgets.append(expander)
                self.rules_list.append(expander)

    def _on_add_folder(self, folder_path: str) -> None:
        """Add new folder by creating a default rule for it."""
        norm_path = str(Path(folder_path).expanduser().resolve())
        # Check if already exists
        rules = self.config_manager.get_rules()
        has_folder = any(
            norm_path in [str(Path(p).expanduser().resolve()) for p in r.get("triggers", {}).get("paths", [])]
            for r in rules
        )
        if not has_folder:
            new_rule = {
                "metadata": {
                    "id": str(Path(folder_path).name or "Folder"),
                    "name": f"Organize {Path(folder_path).name or folder_path}",
                    "enabled": True,
                    "priority": 0,
                    "stop_on_match": False,
                },
                "triggers": {
                    "paths": [norm_path],
                    "recursive": False,
                },
                "conditions": {
                    "mode": "all",
                    "rules": [{"field": "name", "operator": "contains", "value": ""}],
                },
                "actions": [
                    {
                        "type": "move",
                        "destination": str(Path.home() / "Documents"),
                        "conflict_strategy": "rename_counter",
                    }
                ],
            }
            rules.append(new_rule)
            try:
                self.config_manager.save({"version": 1, "rules": rules})
                self.show_toast(f"Added folder: {Path(folder_path).name}")
            except Exception as e:
                self.show_toast(f"Error saving rule: {e}")

        self.selected_folder = norm_path
        self.refresh_ui()

    def _on_folder_active_toggled(self, folder_path: str, is_active: bool) -> None:
        """Enable or disable rules targeting this folder."""
        norm_path = str(Path(folder_path).expanduser().resolve())
        rules = self.config_manager.get_rules()
        for r in rules:
            rule_paths = [str(Path(p).expanduser().resolve()) for p in r.get("triggers", {}).get("paths", [])]
            if norm_path in rule_paths:
                r["metadata"]["enabled"] = is_active

        try:
            self.config_manager.save({"version": 1, "rules": rules})
            status = "enabled" if is_active else "paused"
            self.show_toast(f"Automation for {Path(folder_path).name} {status}")
        except Exception as e:
            self.show_toast(f"Failed to update folder status: {e}")

    def _on_folder_removed(self, folder_path: str) -> None:
        """Remove all rules targeting this folder."""
        norm_path = str(Path(folder_path).expanduser().resolve())
        rules = self.config_manager.get_rules()
        updated_rules = []
        for r in rules:
            paths = [str(Path(p).expanduser().resolve()) for p in r.get("triggers", {}).get("paths", [])]
            if norm_path not in paths:
                updated_rules.append(r)

        try:
            self.config_manager.save({"version": 1, "rules": updated_rules})
            self.show_toast(f"Removed folder: {Path(folder_path).name}")
        except Exception as e:
            self.show_toast(f"Error removing folder: {e}")

        self.selected_folder = None
        self.refresh_ui()

    def _on_add_rule_clicked(self, _btn) -> None:
        """Add a new empty rule for currently selected folder."""
        if not self.selected_folder:
            self.show_toast("Select a watched folder first.")
            return

        expander = RuleExpanderRow(
            rule_data=None,
            target_path=self.selected_folder,
            on_save_needed=self._save_all_rules,
            on_delete_rule=self._on_delete_rule,
        )
        self._rule_widgets.append(expander)
        self.rules_list.append(expander)
        expander.set_expanded(True)

    def _on_delete_rule(self, row: RuleExpanderRow) -> None:
        """Delete rule from UI and persistent config."""
        self.rules_list.remove(row)
        if row in self._rule_widgets:
            self._rule_widgets.remove(row)
        self._save_all_rules()
        self.show_toast("Rule deleted.")

    def _save_all_rules(self) -> None:
        """Collect rules from UI, update current folder rules, and save."""
        all_rules = list(self.config_manager.get_rules())
        norm_selected = str(Path(self.selected_folder).expanduser().resolve()) if self.selected_folder else ""

        # Remove rules belonging to current folder from all_rules
        remaining = [
            r for r in all_rules
            if norm_selected not in [str(Path(p).expanduser().resolve()) for p in r.get("triggers", {}).get("paths", [])]
        ]

        # Add updated rules from current editor widgets
        for widget in self._rule_widgets:
            remaining.append(widget.to_rule_dict())

        try:
            self.config_manager.save({"version": 1, "rules": remaining})
            self.show_toast("Rules saved successfully.")
        except Exception as e:
            self.show_toast(f"Failed to save rules: {e}")

    def _on_run_rules_clicked(self, _btn) -> None:
        """Manually trigger rules on current watched folder."""
        if not self.selected_folder:
            return

        target_dir = Path(self.selected_folder)
        self.show_toast(f"Running rules on {target_dir.name}...")

        def worker():
            count = self.rule_engine.run_rules_on_directory(target_dir, recursive=True)
            GLib.idle_add(self.activity_group.refresh)
            GLib.idle_add(self.show_toast, f"Evaluated {count} files in {target_dir.name}")

        import threading
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _on_validation_banner_clicked(self, _banner) -> None:
        """Open modal displaying validation errors with backup restore option."""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Rule Configuration Invalid",
            body="\n".join(self.config_manager.validation_errors) or "Unknown schema error.",
        )
        dialog.add_response("cancel", "Dismiss")
        dialog.add_response("revert", "Revert to Last Known Good")
        dialog.set_response_appearance("revert", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_dlg, response_id):
            if response_id == "revert":
                success, errors = self.config_manager.revert_to_backup()
                if success:
                    self.show_toast("Reverted configuration to backup.")
                    self.refresh_ui()
                else:
                    self.show_toast(f"Revert failed: {'; '.join(errors)}")

        dialog.connect("response", on_response)
        dialog.present()
