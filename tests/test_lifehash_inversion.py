"""LifeHash colors across the supported displays' hardware inversion modes.

GPIO/SPI are replaced before importing real driver implementations. The modeled
panel output uses the documented supported panels' native INVON polarity and
RGB565 complement; it is not a measurement of physical LCD color calibration.
"""

import importlib.util
from pathlib import Path
import sys
from threading import Lock
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image, ImageDraw

from base import BaseTest
from seedsigner.gui.components import GUIConstants, LifeHashIcon, LifeHashSequence
from seedsigner.gui.renderer import Renderer
from seedsigner.hardware.displays.display_driver import BaseDisplayDriver
from seedsigner.helpers.lifehash import fingerprint_lifehash
from seedsigner.models.settings_definition import SettingsConstants


SOURCE = Path(__file__).resolve().parents[1] / "src" / "seedsigner"
DRIVERS = ("ST7789", "st7789_mpy", "ili9341")


def load_source(monkeypatch, relative_path):
    """Import independently of the flow suite's mocked renderer module."""
    name = "lifehash_inversion_test_" + relative_path.replace("/", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, SOURCE / relative_path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=DRIVERS)
def display(request, monkeypatch):
    gpio = MagicMock()
    rpi = ModuleType("RPi")
    rpi.GPIO = gpio
    monkeypatch.setitem(sys.modules, "RPi", rpi)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", gpio)
    monkeypatch.setitem(sys.modules, "spidev", MagicMock())
    module = load_source(monkeypatch, f"hardware/displays/{request.param}.py")
    commands = []

    if request.param == "st7789_mpy":
        cls = module.ST7789
        original_write = cls._write

        def record_write(self, command=None, data=None):
            if command is not None:
                commands.append(command[0])
            return original_write(self, command, data)

        monkeypatch.setattr(cls, "_write", record_write)
        monkeypatch.setattr(module, "sleep_ms", lambda milliseconds: None)
        driver = cls(_width=240, _height=320)
    else:
        cls = module.ILI9341 if request.param == "ili9341" else module.ST7789
        original_command = cls.command

        def record_command(self, command):
            commands.append(command)
            return original_command(self, command)

        monkeypatch.setattr(cls, "command", record_command)
        # Avoid sleeps without replacing the process-wide time module.
        monkeypatch.setattr(module, "time", SimpleNamespace(sleep=lambda seconds: None))
        driver = cls(_width=320 if request.param == "ili9341" else 240, _height=240)
        if request.param == "ili9341":
            driver.begin()

    return SimpleNamespace(name=request.param, driver=driver, commands=commands)


def rgb565(image):
    """The same packed channel conversion used by the display drivers."""
    return image.convert("RGB").convert("BGR;16").tobytes()


def visible_rgb565(image, driver):
    encoded = rgb565(image)
    # Model the physical register state, independently of colors_inverted.
    return encoded if driver.inverted else bytes(channel ^ 0xff for channel in encoded)


def test_driver_initialization_and_commands_report_actual_polarity(display):
    driver = display.driver
    if display.name == "ili9341":
        assert driver.inverted is False
        assert driver.colors_inverted is True
        assert 0x21 not in display.commands
    else:
        assert driver.inverted is True
        assert driver.colors_inverted is False
        assert display.commands.count(0x21) == (2 if display.name == "st7789_mpy" else 1)

    for enabled in (False, True, False, True):
        driver.invert(enabled)
        assert display.commands[-1] == (0x21 if enabled else 0x20)
        assert driver.inverted is enabled
        assert driver.colors_inverted is (not enabled)

    if display.name == "st7789_mpy":
        # Direct calls to the driver's underlying API must also update state.
        driver.inversion_mode(False)
        assert driver.colors_inverted is True
        driver.inversion_mode(True)
        assert driver.colors_inverted is False


@pytest.mark.parametrize("enabled", [False, True])
def test_renderer_startup_keeps_existing_controller_polarity(display, monkeypatch, enabled):
    module = load_source(monkeypatch, "gui/renderer.py")
    configuration = {
        "ST7789": SettingsConstants.DISPLAY_CONFIGURATION__ST7789__240x240,
        "st7789_mpy": SettingsConstants.DISPLAY_CONFIGURATION__ST7789__320x240,
        "ili9341": SettingsConstants.DISPLAY_CONFIGURATION__ILI9341__320x240,
    }[display.name]
    values = {
        SettingsConstants.SETTING__DISPLAY_CONFIGURATION: configuration,
        SettingsConstants.SETTING__DISPLAY_COLOR_INVERTED:
            SettingsConstants.OPTION__ENABLED if enabled else SettingsConstants.OPTION__DISABLED,
    }
    settings = SimpleNamespace(get_value=lambda key, **kwargs: values[key])
    monkeypatch.setattr(module.Settings, "get_instance", lambda: settings)
    monkeypatch.setattr(module.DisplayDriverFactory, "instantiate_display_driver",
                        lambda *args, **kwargs: display.driver)
    renderer = module.Renderer.__new__(module.Renderer)
    renderer.lock = Lock()
    renderer.disp = None
    commands_before = list(display.commands)
    renderer.initialize_display()
    assert renderer.disp is display.driver
    assert display.commands == commands_before + ([0x21] if enabled else [])
    assert display.driver.colors_inverted is (display.name == "ili9341" and not enabled)


class TestLifeHashInversion(BaseTest):
    def native_renderer(self, monkeypatch, driver):
        canvas = Image.new("RGB", (240, 240), (12, 34, 56))
        renderer = SimpleNamespace(canvas=canvas, draw=ImageDraw.Draw(canvas),
                                   canvas_width=240, canvas_height=240, disp=driver)
        monkeypatch.setattr(Renderer, "get_instance", lambda: renderer)
        return renderer

    @pytest.mark.parametrize("size", [20, 24, 32])
    def test_toggle_reuses_icon_and_preserves_reference_rgb565(self, display, monkeypatch, size):
        renderer = self.native_renderer(monkeypatch, display.driver)
        canonical = fingerprint_lifehash("73c5da0a", size)
        icon = LifeHashIcon(fingerprint="73c5da0a", size=size, screen_x=11, screen_y=13)
        original_icon_bytes = icon.image.tobytes()
        box = (11, 13, 11 + size, 13 + size)

        for enabled in (True, False, True, False, True):
            display.driver.invert(enabled)
            icon.render()
            tile = renderer.canvas.crop(box)
            assert visible_rgb565(tile, display.driver) == rgb565(canonical)
            assert renderer.canvas.getpixel((0, 0)) == (12, 34, 56)
            assert icon.image.tobytes() == original_icon_bytes == canonical.tobytes()
            assert fingerprint_lifehash("73c5da0a", size).tobytes() == canonical.tobytes()

    @pytest.mark.parametrize("arrow_color", [GUIConstants.PASSPHRASE_COLOR, GUIConstants.BIP85_COLOR])
    def test_lineage_tiles_are_excluded_but_surrounding_pixels_are_not(
            self, display, monkeypatch, arrow_color):
        renderer = self.native_renderer(monkeypatch, display.driver)
        fingerprints = ("73c5da0a", "382af2cb")
        sequence = LifeHashSequence(fingerprints=fingerprints, arrow_color=arrow_color,
                                    screen_x=9, screen_y=17)
        display.driver.invert(True)
        sequence.render()
        normal = renderer.canvas.copy()
        display.driver.invert(False)
        sequence.render()
        compensated = renderer.canvas.copy()
        outside_normal = normal.copy()
        outside_compensated = compensated.copy()
        icons = [component for _, component in sequence.components if isinstance(component, LifeHashIcon)]
        assert len(icons) == 2
        for icon, fingerprint in zip(icons, fingerprints):
            box = (icon.screen_x, icon.screen_y, icon.screen_x + icon.width, icon.screen_y + icon.height)
            assert visible_rgb565(compensated.crop(box), display.driver) == rgb565(fingerprint_lifehash(fingerprint, 20))
            outside_normal.paste("black", box)
            outside_compensated.paste("black", box)
        assert outside_normal.tobytes() == outside_compensated.tobytes()
        arrow = sequence.components[1][1]
        arrow_pixel = (arrow.screen_x + 13, arrow.screen_y + 10)
        pixel_box = (*arrow_pixel, arrow_pixel[0] + 1, arrow_pixel[1] + 1)
        assert visible_rgb565(compensated.crop(pixel_box), display.driver) != rgb565(normal.crop(pixel_box))

    @pytest.mark.parametrize("driver", [None, BaseDisplayDriver(240, 240), MagicMock()])
    def test_preview_or_unimplemented_driver_keeps_canonical_pixels(self, monkeypatch, driver):
        renderer = self.native_renderer(monkeypatch, driver)
        icon = LifeHashIcon(fingerprint="73c5da0a", size=20)
        icon.render()
        assert renderer.canvas.crop((0, 0, 20, 20)).tobytes() == fingerprint_lifehash("73c5da0a", 20).tobytes()
