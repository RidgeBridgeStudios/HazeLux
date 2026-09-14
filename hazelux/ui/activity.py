"""Recent Activity transaction history component with pagination, failure badges, and undo."""

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from hazelux.journal.manager import JournalManager
from hazelux.journal.trash import restore_trashed_file


class TransactionRow(Adw.ActionRow):
    """Adw.ActionRow representing a single filesystem transaction with undo capability."""

    def __init__(
        self,
        txn: Dict[str, Any],
        on_undo_requested: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        super().__init__()
        self.txn = txn
        self.on_undo_requested = on_undo_requested

        action_type = txn.get("action_type", "unknown")
        state = txn.get("state", "committed")
        reverted = bool(txn.get("reverted", 0))
        source_name = Path(txn.get("source_path", "")).name
        target_path = txn.get("target_path")
        target_name = Path(target_path).name if target_path else ""

        ts = txn.get("timestamp", 0.0)
        time_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S")

        # Set title and subtitle based on action
        if action_type.startswith("move"):
            self.set_title(f"Moved {source_name} → {target_name}")
            icon_name = "document-send-symbolic"
        elif action_type == "copy":
            self.set_title(f"Copied {source_name} → {target_name}")
            icon_name = "edit-copy-symbolic"
        elif action_type == "rename":
            self.set_title(f"Renamed {source_name} → {target_name}")
            icon_name = "edit-symbolic"
        elif action_type == "trash":
            self.set_title(f"Moved {source_name} to Trash")
            icon_name = "user-trash-symbolic"
        else:
            self.set_title(f"{action_type} on {source_name}")
            icon_name = "text-x-generic-symbolic"

        sub_parts = [f"at {time_str}"]
        if reverted:
            sub_parts.append("(Reverted)")
        self.set_subtitle(" ".join(sub_parts))
        self.add_prefix(Gtk.Image.new_from_icon_name(icon_name))

        # Status badge or Undo button
        if state == "failed":
            warning_img = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
            warning_img.set_tooltip_text("Operation failed; see logs.")
            warning_img.set_valign(Gtk.Align.CENTER)
            self.add_suffix(warning_img)
        elif not reverted and state == "committed":
            undo_btn = Gtk.Button(label="Undo")
            undo_btn.add_css_class("flat")
            undo_btn.set_valign(Gtk.Align.CENTER)
            undo_btn.connect("clicked", self._on_undo_clicked)
            self.add_suffix(undo_btn)

    def _on_undo_clicked(self, _btn):
        if self.on_undo_requested:
            self.on_undo_requested(self.txn)


class RecentActivityGroup(Adw.PreferencesGroup):
    """PreferencesGroup displaying recent transactions with 50-row pagination."""

    def __init__(
        self,
        journal_manager: JournalManager,
        on_toast_message: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(title="Recent Activity")
        self.journal_manager = journal_manager
        self.on_toast_message = on_toast_message
        self.current_limit = 50
        self.current_offset = 0

        self.list_box = Gtk.ListBox()
        self.list_box.add_css_class("boxed-list")
        self.add(self.list_box)

        self.load_older_btn = Gtk.Button(label="Load Older")
        self.load_older_btn.add_css_class("flat")
        self.load_older_btn.set_halign(Gtk.Align.CENTER)
        self.load_older_btn.set_margin_top(8)
        self.load_older_btn.connect("clicked", self._on_load_older_clicked)
        self.add(self.load_older_btn)

        self.refresh()

    def refresh(self) -> None:
        """Refresh transaction display starting from top 50."""
        self.current_limit = 50
        self.current_offset = 0
        self._populate_rows(clear_existing=True)

    def _on_load_older_clicked(self, _btn):
        self.current_offset += 50
        self._populate_rows(clear_existing=False)

    def _populate_rows(self, clear_existing: bool) -> None:
        if clear_existing:
            while row := self.list_box.get_first_child():
                self.list_box.remove(row)

        txns = self.journal_manager.get_recent_transactions(limit=50, offset=self.current_offset)
        for t in txns:
            row = TransactionRow(txn=t, on_undo_requested=self.execute_undo)
            self.list_box.append(row)

        # Hide 'Load Older' if fewer than 50 rows were returned
        self.load_older_btn.set_visible(len(txns) == 50)

    def execute_undo(self, txn: Dict[str, Any]) -> bool:
        """Execute transactional rollback for a given file operation."""
        txn_id = txn["id"]
        action_type = txn.get("action_type", "")
        source_path = txn.get("source_path", "")
        target_path = txn.get("target_path")
        trash_uri = txn.get("trash_uri")

        success = False
        error_msg = ""

        try:
            if action_type in ("move_same_dev", "move_cross_dev", "rename"):
                if target_path and Path(target_path).exists():
                    orig_target = Path(source_path)
                    orig_target.parent.mkdir(parents=True, exist_ok=True)
                    Path(target_path).rename(orig_target)
                    success = True
                else:
                    error_msg = "Target file no longer exists."

            elif action_type == "copy":
                if target_path and Path(target_path).exists():
                    Path(target_path).unlink()
                    success = True
                else:
                    error_msg = "Copied file no longer exists."

            elif action_type == "trash":
                success = restore_trashed_file(source_path=source_path, trash_uri=trash_uri)
                if not success:
                    error_msg = "Cannot restore: original trash entry not found."

        except Exception as e:
            error_msg = f"Rollback failed: {e}"

        if success:
            self.journal_manager.mark_reverted(txn_id)
            if self.on_toast_message:
                self.on_toast_message(f"Reverted {Path(source_path).name}")
            self.refresh()
            return True
        else:
            msg = error_msg or "Failed to undo operation."
            if self.on_toast_message:
                self.on_toast_message(msg)
            return False
