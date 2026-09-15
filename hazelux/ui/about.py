"""About / credits screen for Hazelux, rendered with Adw.AboutWindow."""

from typing import Dict, List, Optional, Tuple

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from hazelux import __version__

# Publisher logo installed into the hicolor icon theme by meson
# (data/icons/hicolor/512x512/apps/io.github.hazelux.Hazelux.publisher.png).
PUBLISHER_ICON_NAME = "io.github.hazelux.Hazelux.publisher"

# Core About window properties (name, branding, copyright, license).
ABOUT_METADATA: Dict[str, object] = {
    "application_name": "Hazelux",
    "application_icon": PUBLISHER_ICON_NAME,
    "developer_name": "Gabriel Foss",
    "version": __version__,
    "copyright": "© 2026 RidgeBridge Studios",
    "license_type": Gtk.License.GPL_3_0,
}

# Rendered as the "Developed by" credit section.
DEVELOPERS: List[str] = [
    "Gabriel Foss <emanuelgabrielfoss@gmail.com>",
]

# Additional custom credit sections (title, people).
CREDIT_SECTIONS: List[Tuple[str, List[str]]] = [
    ("Publisher", ["RidgeBridge Studios"]),
    ("Built with", ["GTK 4", "libadwaita", "watchfiles", "SQLite", "Python"]),
]


def show_about_window(parent: Optional[Gtk.Window] = None) -> Adw.AboutWindow:
    """Build and present the About window, transient to `parent` if given."""
    about = Adw.AboutWindow(transient_for=parent, modal=True)
    for prop, value in ABOUT_METADATA.items():
        about.set_property(prop, value)

    about.set_developers(DEVELOPERS)
    for title, people in CREDIT_SECTIONS:
        about.add_credit_section(title, people)

    about.present()
    return about
