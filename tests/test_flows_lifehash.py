from binascii import a2b_base64

import pytest
from embit import bip32
from embit.descriptor import Descriptor
from embit.networks import NETWORKS
from embit.psbt import PSBT

# Install hardware mocks before importing the application Views.
from base import BaseTest, FlowStep, FlowTest
from psbt_testing_util import PSBTTestData

from seedsigner.controller import Controller, StopFlowBasedTest
from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON
from seedsigner.models.seed import Seed
from seedsigner.models.settings import SettingsConstants
from seedsigner.views import psbt_views, seed_views, tools_views
from seedsigner.views.view import Destination, MainMenuView


def multisig_descriptor(num_keys):
    """Build a real descriptor from deterministic, public test key material."""
    keys = []
    for index in range(num_keys):
        root = bip32.HDKey.from_seed(bytes([index + 1]) * 32)
        xpub = root.derive("m/48h/0h/0h/2h").to_public().to_base58()
        keys.append(f"[{root.my_fingerprint.hex()}/48h/0h/0h/2h]{xpub}/<0;1>/*")
    return Descriptor.from_string(f"wsh(sortedmulti(2,{','.join(keys)}))")


class TestLifeHashViewFlows(FlowTest):
    def load_descriptor(self, num_keys, flow=None):
        descriptor = multisig_descriptor(num_keys)
        self.controller.multisig_wallet_descriptor = descriptor
        self.controller.resume_main_flow = flow
        # As after scanning, page zero is already the current history entry.
        self.controller.back_stack.append(Destination(seed_views.MultisigWalletDescriptorView))
        return descriptor

    def inspect_descriptor_page(self, descriptor, page_index, button_labels, flow):
        def before_run(view):
            assert self.controller.multisig_wallet_descriptor is descriptor
            assert self.controller.resume_main_flow == flow
            assert view.page_index == page_index
            run_screen = view.run_screen

            def inspect_screen(*args, **kwargs):
                assert kwargs["page_index"] == page_index
                assert kwargs["policy"] == f"2 of {len(descriptor.keys)}"
                assert kwargs["fingerprints"] == [key.fingerprint.hex() for key in descriptor.keys]
                assert [button.button_label for button in kwargs["button_data"]] == button_labels
                return run_screen(*args, **kwargs)

            view.run_screen = inspect_screen

        return before_run

    @pytest.mark.parametrize("num_keys", [5, 8, 9])
    def test_multisig_reviews_every_key_page_before_continuing(self, num_keys):
        flow = Controller.FLOW__ADDRESS_EXPLORER
        descriptor = self.load_descriptor(num_keys, flow)
        pages = (num_keys + 3) // 4
        sequence = []
        for page_index in range(pages):
            button = (seed_views.MultisigWalletDescriptorView.ADDRESS_EXPLORER
                      if page_index == pages - 1 else seed_views.MultisigWalletDescriptorView.NEXT)
            sequence.append(FlowStep(
                seed_views.MultisigWalletDescriptorView,
                before_run=self.inspect_descriptor_page(descriptor, page_index, [button.button_label], flow),
                button_data_selection=button,
            ))
        sequence.append(FlowStep(tools_views.ToolsAddressExplorerAddressTypeView))

        self.run_sequence(sequence)

        assert self.controller.multisig_wallet_descriptor is descriptor
        assert self.controller.address_explorer_data["wallet_descriptor"] is descriptor
        assert self.controller.resume_main_flow is None

    def test_back_from_later_multisig_pages_preserves_descriptor_and_flow(self):
        flow = Controller.FLOW__PSBT
        descriptor = self.load_descriptor(9, flow)
        next_button = seed_views.MultisigWalletDescriptorView.NEXT
        return_button = seed_views.MultisigWalletDescriptorView.RETURN

        self.run_sequence([
            FlowStep(seed_views.MultisigWalletDescriptorView,
                     before_run=self.inspect_descriptor_page(descriptor, 0, [next_button.button_label], flow),
                     button_data_selection=next_button),
            FlowStep(seed_views.MultisigWalletDescriptorView,
                     before_run=self.inspect_descriptor_page(descriptor, 1, [next_button.button_label], flow),
                     button_data_selection=next_button),
            FlowStep(seed_views.MultisigWalletDescriptorView,
                     before_run=self.inspect_descriptor_page(descriptor, 2, [return_button.button_label], flow),
                     screen_return_value=RET_CODE__BACK_BUTTON),
            FlowStep(seed_views.MultisigWalletDescriptorView,
                     before_run=self.inspect_descriptor_page(descriptor, 1, [next_button.button_label], flow),
                     screen_return_value=RET_CODE__BACK_BUTTON),
            FlowStep(seed_views.MultisigWalletDescriptorView,
                     before_run=self.inspect_descriptor_page(descriptor, 0, [next_button.button_label], flow),
                     screen_return_value=StopFlowBasedTest()),
        ])

        assert self.controller.multisig_wallet_descriptor is descriptor
        assert self.controller.resume_main_flow == flow

    def test_back_from_first_multisig_page_discards_descriptor(self):
        flow = Controller.FLOW__PSBT
        descriptor = self.load_descriptor(5, flow)
        self.controller.back_stack.insert(0, Destination(seed_views.LoadMultisigWalletDescriptorView))
        next_button = seed_views.MultisigWalletDescriptorView.NEXT

        self.run_sequence([
            FlowStep(seed_views.MultisigWalletDescriptorView,
                     before_run=self.inspect_descriptor_page(descriptor, 0, [next_button.button_label], flow),
                     screen_return_value=RET_CODE__BACK_BUTTON),
            FlowStep(seed_views.LoadMultisigWalletDescriptorView),
        ])

        assert self.controller.multisig_wallet_descriptor is None
        assert self.controller.resume_main_flow == flow

    @pytest.mark.parametrize("flow,final_view", [
        (None, MainMenuView),
        (Controller.FLOW__PSBT, psbt_views.PSBTChangeDetailsView),
        (Controller.FLOW__VERIFY_MULTISIG_ADDR, seed_views.SeedAddressVerificationView),
    ])
    def test_multisig_final_page_resumes_original_flow(self, flow, final_view):
        descriptor = self.load_descriptor(5, flow)
        if flow == Controller.FLOW__VERIFY_MULTISIG_ADDR:
            address = descriptor.derive(0, branch_index=0).address(NETWORKS["main"])
            self.controller.unverified_address = dict(
                address=address,
                derivation_path="m/48h/0h/0h/2h",
                script_type=SettingsConstants.NATIVE_SEGWIT,
                sig_type=SettingsConstants.MULTISIG,
                network=SettingsConstants.MAINNET,
            )
            final_label = f"Verify addr {address[:7]}"
        elif flow == Controller.FLOW__PSBT:
            final_label = seed_views.MultisigWalletDescriptorView.RETURN.button_label
        else:
            final_label = seed_views.MultisigWalletDescriptorView.OK.button_label

        self.run_sequence([
            FlowStep(seed_views.MultisigWalletDescriptorView,
                     button_data_selection=seed_views.MultisigWalletDescriptorView.NEXT),
            FlowStep(seed_views.MultisigWalletDescriptorView,
                     before_run=self.inspect_descriptor_page(descriptor, 1, [final_label], flow),
                     screen_return_value=0),
            FlowStep(final_view),
        ])

        assert self.controller.resume_main_flow is None
        if flow is None:
            # Returning home intentionally clears the descriptor as before.
            assert self.controller.multisig_wallet_descriptor is None
        else:
            assert self.controller.multisig_wallet_descriptor is descriptor
        if flow == Controller.FLOW__PSBT:
            assert self.controller.back_stack[-1].view_args == {"change_address_num": 0}

    def test_psbt_signer_labels_keep_undecorated_lifehash_metadata(self):
        signer = PSBTTestData.two_input_seed
        non_signer = Seed(["abandon"] * 11 + ["about"])
        self.settings.set_value(SettingsConstants.SETTING__NETWORK, SettingsConstants.REGTEST)
        self.controller.storage.seeds = [signer, non_signer]
        self.controller.psbt = PSBT.parse(a2b_base64(PSBTTestData.SINGLE_SIG_NATIVE_SEGWIT_2_INPUTS))

        def inspect_signers(view):
            run_screen = view.run_screen

            def inspect_screen(*args, **kwargs):
                options = kwargs["button_data"]
                signer_fp = signer.get_fingerprint(SettingsConstants.REGTEST)
                non_signer_fp = non_signer.get_fingerprint(SettingsConstants.REGTEST)
                assert options[0].button_label == signer_fp
                assert options[1].button_label == f"{non_signer_fp} (?)"
                assert [option.lifehash_fingerprint for option in options[:2]] == [signer_fp, non_signer_fp]
                assert all(len(bytes.fromhex(option.lifehash_fingerprint)) == 4 for option in options[:2])
                assert all(option.lifehash_fingerprint is None for option in options[2:])
                return run_screen(*args, **kwargs)

            view.run_screen = inspect_screen

        self.run_sequence([
            FlowStep(psbt_views.PSBTSelectSeedView, before_run=inspect_signers, screen_return_value=0),
            FlowStep(psbt_views.PSBTOverviewView),
        ])

        assert self.controller.psbt_seed is signer


class TestPassphraseReviewColor(BaseTest):
    @pytest.mark.parametrize("initial_review", [True, False])
    def test_rendered_passphrase_keeps_arrow_color_after_supersampling(self, initial_review, monkeypatch):
        from unittest.mock import MagicMock

        from PIL import Image, ImageColor, ImageDraw

        from seedsigner.gui.components import FingerprintArrow, FingerprintTransition, GUIConstants, TextArea
        from seedsigner.gui.renderer import Renderer
        from seedsigner.gui.screens.screen import ButtonOption
        from seedsigner.gui.screens.seed_screens import SeedConfirmPassphraseScreen, SeedReviewPassphraseScreen

        # Keep the native fonts and Pillow rendering; replace only the hardware
        # display with a real image canvas. No button loop or background threads.
        renderer = MagicMock()
        renderer.canvas_width = renderer.canvas_height = 240
        renderer.canvas = Image.new("RGB", (240, 240), GUIConstants.BACKGROUND_COLOR)
        renderer.draw = ImageDraw.Draw(renderer.canvas)
        monkeypatch.setattr(Renderer, "get_instance", lambda: renderer)
        passphrase = "Passphrase123!lIgy@"
        kwargs = dict(fingerprint_without="73c5da0a", passphrase=passphrase,
                      button_data=[ButtonOption("Edit"), ButtonOption("Done")])
        if initial_review:
            screen = SeedReviewPassphraseScreen(fingerprint_with="0d777ffb", **kwargs)
        else:
            screen = SeedConfirmPassphraseScreen(fingerprint_new="0d777ffb", **kwargs)
        screen._render()

        text = next(component for component in screen.components
                    if isinstance(component, TextArea) and component.text == passphrase)
        transition = next(component for component in screen.components if isinstance(component, FingerprintTransition))
        arrow = next(component for component in transition.components if isinstance(component, FingerprintArrow))
        expected_color = ImageColor.getrgb(GUIConstants.PASSPHRASE_COLOR)
        arrow_pixel = renderer.canvas.getpixel((arrow.screen_x + 10, arrow.screen_y + 10))
        text_colors = set(text.rendered_text_img.convert("RGB").getdata())

        assert text.supersampling_factor > 1
        assert arrow_pixel == expected_color
        assert max(text_colors, key=sum) == arrow_pixel
        # Sharpening RGB directly previously increased green/blue independently
        # of the saturated red channel, visibly changing the glyph hue.
        assert all(all(channel <= target for channel, target in zip(pixel, expected_color))
                   for pixel in text_colors)


class TestSeedOptionsHeader(BaseTest):
    @pytest.mark.parametrize("parent,without,current", [
        ("b4e3f5ed", None, "47c88c48"),
        ("b4e3f5ed", "47c88c48", "0d777ffb"),
        (None, None, "47c88c48"),
        ("deadbeef", "deadbeef", "deadbeef"),
    ])
    def test_native_child_header_renders_every_role_without_overlapping_back_or_xfp(
            self, parent, without, current, monkeypatch):
        from unittest.mock import MagicMock

        from PIL import Image, ImageColor, ImageDraw

        from seedsigner.gui.components import FingerprintArrow, GUIConstants, IconTextLine, LifeHashIcon, TextArea
        from seedsigner.gui.renderer import Renderer
        from seedsigner.gui.screens.screen import ButtonOption
        from seedsigner.gui.screens.seed_screens import SeedOptionsScreen

        renderer = MagicMock()
        renderer.canvas_width = renderer.canvas_height = 240
        renderer.canvas = Image.new("RGB", (240, 240), GUIConstants.BACKGROUND_COLOR)
        renderer.draw = ImageDraw.Draw(renderer.canvas)
        monkeypatch.setattr(Renderer, "get_instance", lambda: renderer)
        screen = SeedOptionsScreen(fingerprint_parent=parent, fingerprint_without=without, fingerprint=current,
                                   button_data=[ButtonOption("Scan PSBT")])
        screen._render()
        icons, arrows, labels = [], [], []

        def visit(component):
            if isinstance(component, LifeHashIcon):
                icons.append(component)
            elif isinstance(component, FingerprintArrow):
                arrows.append(component)
            elif isinstance(component, TextArea):
                labels.append(component)
            elif isinstance(component, IconTextLine):
                visit(component.icon)
                visit(component.value_textarea)
            else:
                for child in component.components:
                    visit(child[1] if isinstance(child, tuple) else child)

        visit(screen.top_nav.title)
        expected_fingerprints = ([parent] if parent else []) + ([without] if without else []) + [current]
        expected_colors = ([GUIConstants.BIP85_COLOR] if parent else []) + ([GUIConstants.PASSPHRASE_COLOR] if without else [])
        assert [icon.fingerprint for icon in icons] == expected_fingerprints
        assert [arrow.color for arrow in arrows] == expected_colors
        assert [label.text for label in labels] == [current]

        left_edge = screen.top_nav.left_button.screen_x + screen.top_nav.left_button.width + GUIConstants.COMPONENT_PADDING
        right_edge = renderer.canvas_width - GUIConstants.EDGE_PADDING
        for icon in icons:
            assert left_edge <= icon.screen_x < icon.screen_x + icon.width <= right_edge
            box = (icon.screen_x, icon.screen_y, icon.screen_x + icon.width, icon.screen_y + icon.height)
            assert renderer.canvas.crop(box).tobytes() == icon.image.tobytes()
        for arrow in arrows:
            assert renderer.canvas.getpixel((arrow.screen_x + 10, arrow.screen_y + 10)) == ImageColor.getrgb(arrow.color)
        label = labels[0]
        assert icons[-1].screen_x + icons[-1].width < label.screen_x
        assert label.screen_x + label.text_width <= right_edge
        assert screen.top_nav.title.content_width <= screen.top_nav.title.width
