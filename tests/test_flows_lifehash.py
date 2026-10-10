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
