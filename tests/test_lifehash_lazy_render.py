"""Generate LifeHashes on first use, without changing pixels or list behavior."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image, ImageDraw, ImageOps

# Install the test hardware mocks before importing GUI components.
from base import BaseTest
from seedsigner.gui.components import GUIConstants, LifeHashIcon
from seedsigner.gui.renderer import Renderer
from seedsigner.gui.screens.screen import ButtonListScreen, ButtonOption
from seedsigner.helpers import lifehash


class TestLazyLifeHashRendering(BaseTest):
    def native_renderer(self, monkeypatch):
        canvas = Image.new("RGB", (240, 240), GUIConstants.BACKGROUND_COLOR)
        renderer = MagicMock(canvas_width=240, canvas_height=240, canvas=canvas,
                             draw=ImageDraw.Draw(canvas),
                             disp=SimpleNamespace(colors_inverted=False))
        monkeypatch.setattr(Renderer, "get_instance", lambda: renderer)
        return renderer

    def track_images(self, monkeypatch):
        generate = MagicMock(wraps=lifehash.fingerprint_lifehash)
        monkeypatch.setattr(lifehash, "fingerprint_lifehash", generate)
        return generate

    @pytest.mark.parametrize("size", [20, 24, 32])
    def test_first_use_retains_canonical_image_across_renders_and_inversion(self, monkeypatch, size):
        renderer = self.native_renderer(monkeypatch)
        canonical = lifehash.fingerprint_lifehash("73c5da0a", size)
        generate = self.track_images(monkeypatch)
        icon = LifeHashIcon(fingerprint="73c5da0a", size=size, screen_x=8, screen_y=10)
        assert (icon.width, icon.height) == (size, size)
        generate.assert_not_called()
        box = (8, 10, 8 + size, 10 + size)

        for inverted in (False, True, False, True):
            renderer.disp.colors_inverted = inverted
            icon.render()
            expected = ImageOps.invert(canonical) if inverted else canonical
            assert renderer.canvas.crop(box).tobytes() == expected.tobytes()
            assert icon.image.tobytes() == canonical.tobytes()
            generate.assert_called_once_with("73c5da0a", size)

    def test_explicit_image_access_is_lazy_and_reuses_the_same_image(self, monkeypatch):
        self.native_renderer(monkeypatch)
        generate = self.track_images(monkeypatch)
        icon = LifeHashIcon(fingerprint="73c5da0a")
        generate.assert_not_called()
        image = icon.image
        assert icon.image is image
        icon.render()
        generate.assert_called_once_with("73c5da0a", 32)

    @pytest.mark.parametrize("lineage", [False, True])
    def test_long_list_generates_only_visible_icons_and_reuses_them_when_scrolling_back(
            self, monkeypatch, lineage):
        self.native_renderer(monkeypatch)
        generate = self.track_images(monkeypatch)
        rows = []
        options = []
        for index in range(24):
            fingerprints = (f"{index * 2:08x}", f"{index * 2 + 1:08x}") if lineage else (f"{index:08x}",)
            rows.append(fingerprints)
            icon_args = {"lifehash_fingerprints": fingerprints} if lineage else {"lifehash_fingerprint": fingerprints[0]}
            options.append(ButtonOption(fingerprints[-1], **icon_args))
        screen = ButtonListScreen(title="In-Memory Seeds", button_data=options)
        assert screen.has_scroll_arrows
        generate.assert_not_called()

        def visible_fingerprints():
            return [fingerprint
                    for row, button in zip(rows, screen.buttons)
                    if screen.top_nav.height <= button.screen_y - button.scroll_y < screen.down_arrow_img_y
                    for fingerprint in row]

        first_page = visible_fingerprints()
        assert 0 < len(first_page) < 16
        screen._render()
        assert [call.args[0] for call in generate.call_args_list] == first_page
        screen._render()
        assert generate.call_count == len(first_page)

        # Use the screen's real viewport filter after scrolling one row.
        offset = screen.buttons[1].screen_y - screen.buttons[0].screen_y
        for button in screen.buttons:
            button.scroll_y += offset
        second_page = visible_fingerprints()
        new_fingerprints = [fingerprint for fingerprint in second_page if fingerprint not in first_page]
        assert len(new_fingerprints) == (2 if lineage else 1)
        screen._render_visible_buttons()
        assert [call.args[0] for call in generate.call_args_list] == first_page + new_fingerprints

        for button in screen.buttons:
            button.scroll_y -= offset
        screen._render_visible_buttons()
        assert generate.call_count == len(first_page) + len(new_fingerprints)
