"""Watched Folders sidebar component using Adw.NavigationPage and Adw.ActionRow."""

from pathlib import Path
from typing import Callable, List, Optional, Set

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk


class FolderRow(Adw.ActionRow):
    """Adw.ActionRow representing a watched directory with folder icon and active switch."""

    def __init__(
        self,
        folder_path: str,
        is_active: bool = True,
        on_active_toggled: Optional[Callable[[str, bool], None]] = None,
        on_remove: Optional[Callable[[str], None]] = None,
    ):
        super().__init__()
        self.folder_path = folder_path
        self.on_active_toggled = on_active_toggled
        self.on_remove = on_remove

        self.set_title(Path(folder_path).name or folder_path)
        self.set_subtitle(folder_path)
        self.add_prefix(Gtk.Image.new_from_icon_name("folder-symbolic"))

        # Pause / Active toggle switch
        self.active_switch = Gtk.Switch()
        self.active_switch.set_active(is_active)
        self.active_switch.set_valign(Gtk.Align.CENTER)
        self.active_switch.connect("notify::active", self._on_switch_toggled)
        self.add_suffix(self.active_switch)

        # Remove button
        remove_btn = Gtk.Button(icon_name="edit-delete-symbolic")
        remove_btn.add_css_class("flat")
        remove_btn.set_valign(Gtk.Align.CENTER)
        remove_btn.set_tooltip_text("Remove folder from automation")
        remove_btn.connect("clicked", self._on_remove_clicked)
        self.add_suffix(remove_btn)

    def _on_switch_toggled(self, switch, _pspec):
        if self.on_active_toggled:
            self.on_active_toggled(self.folder_path, switch.get_active())

    def _on_remove_clicked(self, _btn):
        if self.on_remove:
            self.on_remove(self.folder_path)


class SidebarView(Adw.NavigationPage):
    """Sidebar navigation page listing watched folders."""

    def __init__(
        self,
        on_folder_selected: Callable[[str], None],
        on_add_folder: Callable[[str], None],
        on_folder_active_toggled: Callable[[str, bool], None],
        on_folder_removed: Callable[[str], None],
    ):
        super().__init__(title="Watched Folders")
        self.on_folder_selected = on_folder_selected
        self.on_add_folder = on_add_folder
        self.on_folder_active_toggled = on_folder_active_toggled
        self.on_folder_removed = on_folder_removed

        self.toolbar_view = Adw.ToolbarView()
        self.set_child(self.toolbar_view)

        # Top Bar with Add Folder button
        header = Adw.HeaderBar()
        add_btn = Gtk.Button(icon_name="list-add-symbolic")
        add_btn.set_tooltip_text("Add folder to watch")
        add_btn.connect("clicked", self._open_add_folder_dialog)
        header.pack_start(add_btn)
        self.toolbar_view.add_top_bar(header)

        # Content ListBox
        scrolled = Gtk.ScrolledWindow()
        self.list_box = Gtk.ListBox()
        self.list_box.add_css_class("navigation-sidebar")
        self.list_box.connect("row-selected", self._on_row_selected)
        scrolled.set_child(self.list_box)
        self.toolbar_view.set_content(scrolled)

        self._folder_rows: List[FolderRow] = []

    def set_folders(self, folders: List[str], paused_folders: Optional[Set[str]] = None) -> None:
        """Update displayed folder rows."""
        paused = paused_folders or set()
        # Clear existing
        while row := self.list_box.get_first_child():
            self.list_box.remove(row)
        self._folder_rows.clear()

        for f in folders:
            is_active = f not in paused
            row = FolderRow(
                folder_path=f,
                is_active=is_active,
                on_active_toggled=self.on_folder_active_toggled,
                on_remove=self.on_folder_removed,
            )
            self._folder_rows.append(row)
            self.list_box.append(row)

        if self._folder_rows:
            self.list_box.select_row(self._folder_rows[0])

    def _on_row_selected(self, _box, row):
        if isinstance(row, FolderRow):
            self.on_folder_selected(row.folder_path)

    def _open_add_folder_dialog(self, _btn):
        # Open GTK FileDialog for folder selection
        dialog = Gtk.FileDialog(title="Select Folder to Automate")
        dialog.select_folder(
            parent=self.get_root(),
            cancellable=None,
            callback=self._on_folder_chosen,
        )

    def _on_folder_chosen(self, dialog, result):
        try:
            folder_file = dialog.select_folder_finish(result)
            if folder_file:
                path = folder_file.get_path()
                if path:
                    self.on_add_folder(path)
        except Exception:
            pass  # User cancelled
