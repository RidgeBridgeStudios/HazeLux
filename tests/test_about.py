"""Tests for the About / credits screen metadata."""

from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from hazelux import __version__
from hazelux.ui.about import ABOUT_METADATA, CREDIT_SECTIONS, DEVELOPERS


def test_about_metadata_matches_credits_template():
    """Core About properties reflect the credits template."""
    assert ABOUT_METADATA["application_name"] == "Hazelux"
    assert ABOUT_METADATA["developer_name"] == "Gabriel Foss"
    assert ABOUT_METADATA["copyright"] == "© 2026 RidgeBridge Studios"
    assert ABOUT_METADATA["license_type"] == Gtk.License.GPL_3_0
    assert ABOUT_METADATA["version"] == __version__


def test_about_credits_sections_match_template():
    """Developer, publisher, and built-with credits match the template."""
    assert DEVELOPERS == ["Gabriel Foss <emanuelgabrielfoss@gmail.com>"]
    sections = dict(CREDIT_SECTIONS)
    assert sections["Publisher"] == ["RidgeBridge Studios"]
    assert sections["Built with"] == [
        "GTK 4", "libadwaita", "watchfiles", "SQLite", "Python",
    ]


def test_publisher_icon_asset_exists():
    """The publisher logo icon is shipped with the project and installed by meson."""
    icon = (
        Path(__file__).resolve().parent.parent
        / "data/icons/hicolor/512x512/apps/io.github.hazelux.Hazelux.publisher.png"
    )
    assert icon.is_file()
    assert "io.github.hazelux.Hazelux.publisher.png" in Path(
        __file__).resolve().parent.parent.joinpath("meson.build").read_text()
