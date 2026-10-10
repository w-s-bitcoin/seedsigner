"""Keep replacement identity explicit without changing derivation diagrams."""

from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from base import BaseTest
from seedsigner.gui.components import FingerprintHeader, IconTextLine, LifeHashIcon, TextArea
from seedsigner.gui.renderer import Renderer
from seedsigner.gui.screens.screen import ButtonOption
from seedsigner.gui.screens.seed_screens import SeedBIP85SaveChildScreen, SeedPassphraseSaveScreen


class TestWalletSaveIdentity(BaseTest):
    @pytest.mark.parametrize("kind,source,current,candidate", [
        ("passphrase", "73c5da0a", "73c5da0a", "0d777ffb"),
        ("passphrase", "73c5da0a", "0d777ffb", "4bbb23c1"),
        ("bip85", "0d777ffb", "02e8bff2", "95078ef2"),
    ])
    def test_target_is_visible_below_two_tile_derivation(self, monkeypatch, kind, source, current, candidate):
        canvas = Image.new("RGB", (240, 240))
        renderer = SimpleNamespace(canvas=canvas, draw=ImageDraw.Draw(canvas),
                                   canvas_width=240, canvas_height=240, disp=None, show_image=lambda: None)
        monkeypatch.setattr(Renderer, "get_instance", lambda: renderer)
        cls = SeedPassphraseSaveScreen if kind == "passphrase" else SeedBIP85SaveChildScreen
        source_key = "fingerprint_without" if kind == "passphrase" else "fingerprint_parent"
        screen = cls(**{source_key: source}, fingerprint_new=candidate, fingerprint_current=current,
                     button_data=[ButtonOption("Replace current"), ButtonOption("Load separately"),
                                  ButtonOption("Cancel")], selected_button=0)
        screen._render()
        header = next(c for c in screen.components if isinstance(c, FingerprintHeader))
        tiles = [c if isinstance(c, LifeHashIcon) else c.icon
                 for c in header.components if isinstance(c, (LifeHashIcon, IconTextLine))]
        assert [c.fingerprint for c in tiles] == [source, candidate]
        label = next(c for c in screen.components if isinstance(c, TextArea)
                     and c.text == "Replace loaded wallet:")
        target = next(c for c in screen.components if isinstance(c, TextArea) and c.text == current)
        assert target.font_size == 20
        assert label.screen_y + label.height <= target.screen_y
        assert target.screen_y + target.height <= screen.buttons[0].screen_y
        assert screen.buttons[0].text == "Replace current"
        assert screen.selected_button == 0
        # The loaded identity has actually painted visible text on the canvas.
        assert canvas.crop((target.screen_x, target.screen_y,
                            target.screen_x + target.width, target.screen_y + target.height)).getbbox()
