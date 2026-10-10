from gettext import gettext as _
from unittest.mock import MagicMock

import pytest
from PIL import Image, ImageDraw

from base import BaseTest

from seedsigner.gui.components import Button, GUIConstants, SeedSignerIconConstants, TextArea
from seedsigner.gui.renderer import Renderer
from seedsigner.models.settings_definition import SettingsConstants


class TestButtonRightIconLayout(BaseTest):
    def native_renderer(self, monkeypatch):
        renderer = MagicMock()
        renderer.canvas_width = renderer.canvas_height = 240
        renderer.canvas = Image.new("RGB", (240, 240), GUIConstants.BACKGROUND_COLOR)
        renderer.draw = ImageDraw.Draw(renderer.canvas)
        monkeypatch.setattr(Renderer, "get_instance", lambda: renderer)
        # Inspect the real native glyphs and scroll viewport without starting a
        # timed animation that could race the image assertions.
        monkeypatch.setattr(TextArea.HorizontalTextScrollThread, "start", lambda self: None)
        return renderer

    @pytest.mark.parametrize("selected", [False, True])
    @pytest.mark.parametrize("locale,label,icon,color", [
        ("fr", "BIP-39 Passphrase", SeedSignerIconConstants.CHECK, GUIConstants.INFO_COLOR),
        ("cs", "BIP-85 child seed", SeedSignerIconConstants.CHECK, GUIConstants.INFO_COLOR),
        ("fr", "BIP-39 Passphrase", SeedSignerIconConstants.CHEVRON_RIGHT, GUIConstants.BODY_FONT_COLOR),
    ])
    def test_translated_label_respects_right_icon_in_both_states(
            self, monkeypatch, selected, locale, label, icon, color):
        renderer = self.native_renderer(monkeypatch)
        self.settings.set_value(SettingsConstants.SETTING__LOCALE, locale)
        button = Button(
            text=_(label), screen_x=8, screen_y=100, width=224,
            is_text_centered=False, is_selected=selected,
            right_icon_name=icon, right_icon_color=color,
        )
        # These translations fit the old full-width viewport but overlap the
        # right icon. Previously they were clipped without ever scrolling.
        assert button.visible_text_width < button.text_width <= button.width - 2 * GUIConstants.COMPONENT_PADDING
        button.render()
        text = button.active_button_label if selected else button.inactive_button_label
        right_icon = button.right_icon_selected if selected else button.right_icon
        assert text.visible_width == button.visible_text_width
        if selected:
            assert text.needs_scroll
            scroll = text.scroll_thread
            assert scroll.screen_x + scroll.visible_width <= right_icon.screen_x - 2

        icon_box = (right_icon.screen_x - 2, right_icon.screen_y - 2,
                    right_icon.screen_x + right_icon.width + 2,
                    right_icon.screen_y + right_icon.height + 2)
        icon_pixels = renderer.canvas.crop(icon_box).tobytes()
        text.render()
        assert renderer.canvas.crop(icon_box).tobytes() == icon_pixels

    def test_button_without_right_icon_keeps_full_label_width(self, monkeypatch):
        self.native_renderer(monkeypatch)
        self.settings.set_value(SettingsConstants.SETTING__LOCALE, "fr")
        button = Button(text=_("BIP-39 Passphrase"), width=224, is_selected=True)
        button.render()
        assert button.active_button_label.visible_width == 208
        assert not button.active_button_label.needs_scroll
