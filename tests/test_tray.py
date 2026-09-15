"""Tests for system tray icon generation and availability state."""

from PIL import Image

from hazelux.ui.tray import TrayManager, create_tray_icon_image, load_app_icon_image


def test_fallback_tray_icon_is_generated():
    """The drawn placeholder remains available when no app icon can load."""
    img = create_tray_icon_image()
    assert isinstance(img, Image.Image)
    assert img.mode == "RGBA"
    assert img.size == (64, 64)


def test_app_icon_loads_or_falls_back_gracefully():
    """With a display the real app icon rasterizes; headless returns None."""
    img = load_app_icon_image()
    assert img is None or (isinstance(img, Image.Image) and img.size == (64, 64))


def test_tray_manager_inactive_before_setup():
    """is_active is False until setup_tray registers an icon."""
    mgr = TrayManager(
        on_toggle_window=lambda: None,
        on_pause_toggle=lambda: False,
        on_run_rules_now=lambda: None,
        on_quit=lambda: None,
    )
    assert mgr.is_active is False
