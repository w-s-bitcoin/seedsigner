import pytest

# Install hardware mocks before importing application Views.
from base import FlowStep, FlowTest

from seedsigner.models.seed import Seed
from seedsigner.models.settings import SettingsConstants
from seedsigner.views import seed_views
from seedsigner.views.view import MainMenuView


MNEMONIC = ["abandon"] * 11 + ["about"]
KINDS = ["regular", "passphrased", "child", "passphrased_child"]
WALLET_STATE = (
    "psbt", "psbt_parser", "psbt_seed", "resume_main_flow",
    "multisig_wallet_descriptor", "unverified_address",
    "address_explorer_data", "sign_message_data",
)


class TestSeedDiscardFlows(FlowTest):
    def load_wallets(self, kind, multiple):
        parent = Seed(MNEMONIC, "TREZOR" if kind != "regular" else "")
        child = Seed(
            parent.get_bip85_child_mnemonic(0, 12).split(),
            "child extension" if kind == "passphrased_child" else "",
            bip85_parent_fingerprint=parent.get_fingerprint(),
            bip85_child_index=0, bip85_num_words=12,
        )
        self.target = child if kind in ("child", "passphrased_child") else parent
        self.related = parent if self.target is child else child
        self.pending = Seed(MNEMONIC, "unrelated pending entry")
        if multiple:
            self.originals = [Seed(MNEMONIC, "first other wallet"), self.target,
                              Seed(MNEMONIC, "second other wallet"), self.related]
        else:
            self.originals = [self.target]
        self.controller.storage.seeds = list(self.originals)
        self.controller.storage.set_pending_seed(self.pending)
        self.settings.set_value(SettingsConstants.SETTING__PASSPHRASE, SettingsConstants.OPTION__ENABLED)
        self.settings.set_value(SettingsConstants.SETTING__BIP85_CHILD_SEEDS, SettingsConstants.OPTION__ENABLED)
        self.original_state = [
            (seed.seed_bytes, seed.passphrase, seed.is_bip85_child,
             seed.bip85_parent_fingerprint, seed.bip85_child_index, seed.bip85_num_words)
            for seed in self.originals
        ]

    def inspect_discard(self, view):
        assert view.seed is self.target
        assert not view.is_pending_seed
        assert all(actual is original for actual, original in zip(
            self.controller.storage.seeds, self.originals))
        # Inject after SeedOptions so its normal resume behavior does not run.
        for attr in WALLET_STATE:
            setattr(self.controller, attr, self.target if attr == "psbt_seed" else object())
        run = view.run

        def record_destination():
            self.discard_destination = run()
            return self.discard_destination

        view.run = record_destination

    def assert_original_objects_unchanged(self):
        for seed, state in zip(self.originals, self.original_state):
            assert seed.seed_bytes is state[0]
            assert (seed.passphrase, seed.is_bip85_child, seed.bip85_parent_fingerprint,
                    seed.bip85_child_index, seed.bip85_num_words) == state[1:]

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("multiple", [False, True], ids=["last_seed", "other_seeds_remain"])
    def test_discard_returns_to_remaining_seeds_or_home(self, kind, multiple):
        self.load_wallets(kind, multiple)
        expected_view = seed_views.SeedsMenuView if multiple else MainMenuView
        self.run_sequence([
            FlowStep(seed_views.SeedOptionsView,
                     button_data_selection=seed_views.SeedOptionsView.DISCARD),
            FlowStep(seed_views.SeedDiscardView, before_run=self.inspect_discard,
                     button_data_selection=seed_views.SeedDiscardView.DISCARD),
            FlowStep(expected_view),
        ], initial_destination_view_args={"seed": self.target})

        expected = [seed for seed in self.originals if seed is not self.target]
        assert len(self.controller.storage.seeds) == len(expected)
        assert all(actual is original for actual, original in zip(self.controller.storage.seeds, expected))
        assert all(seed is not self.target for seed in self.controller.storage.seeds)
        assert self.controller.storage.get_pending_seed() is self.pending
        self.assert_original_objects_unchanged()
        assert self.discard_destination.View_cls is expected_view
        assert self.discard_destination.clear_history
        assert all(getattr(self.controller, attr) is None for attr in WALLET_STATE)
        # Home clears its own entry; the list keeps only its new destination.
        assert len(self.controller.back_stack) == (1 if multiple else 0)
        assert all(destination.View_cls is expected_view for destination in self.controller.back_stack)

    @pytest.mark.parametrize("kind", KINDS)
    def test_keep_returns_to_same_wallet_without_discarding_any_seed(self, kind):
        self.load_wallets(kind, multiple=True)
        self.run_sequence([
            FlowStep(seed_views.SeedOptionsView,
                     button_data_selection=seed_views.SeedOptionsView.DISCARD),
            FlowStep(seed_views.SeedDiscardView,
                     button_data_selection=seed_views.SeedDiscardView.KEEP),
            FlowStep(seed_views.SeedOptionsView),
        ], initial_destination_view_args={"seed": self.target})

        assert len(self.controller.storage.seeds) == len(self.originals)
        assert all(actual is original for actual, original in zip(self.controller.storage.seeds, self.originals))
        assert self.controller.storage.get_pending_seed() is self.pending
        assert self.controller.back_stack[-1].view_args["seed"] is self.target
        assert all(destination.View_cls is not seed_views.SeedDiscardView
                   for destination in self.controller.back_stack)
        self.assert_original_objects_unchanged()

    @pytest.mark.parametrize("multiple", [False, True], ids=["no_loaded_seeds", "loaded_seeds_remain"])
    def test_pending_seed_discard_still_returns_home(self, multiple):
        self.load_wallets("regular", multiple=True)
        if not multiple:
            self.controller.storage.seeds = []
        stored = list(self.controller.storage.seeds)
        self.run_sequence([
            FlowStep(seed_views.SeedDiscardView,
                     button_data_selection=seed_views.SeedDiscardView.DISCARD),
            FlowStep(MainMenuView),
        ])

        assert self.controller.storage.get_pending_seed() is None
        assert len(self.controller.storage.seeds) == len(stored)
        assert all(actual is original for actual, original in zip(self.controller.storage.seeds, stored))
        assert len(self.controller.back_stack) == 0

    @pytest.mark.parametrize("equal_reimport", [False, True])
    def test_stale_discard_view_redirects_without_removing_later_wallet(self, equal_reimport):
        self.load_wallets("passphrased", multiple=False)
        canonical = Seed(MNEMONIC, self.target.passphrase)
        self.controller.storage.seeds = [canonical] if equal_reimport else []
        view = seed_views.SeedDiscardView(self.target)
        assert view.has_redirect
        destination = view.get_redirect()
        assert destination.View_cls is (seed_views.SeedsMenuView if equal_reimport else MainMenuView)
        assert destination.clear_history
        assert len(self.controller.storage.seeds) == int(equal_reimport)
        if equal_reimport:
            assert self.controller.storage.seeds[0] is canonical
        assert self.controller.storage.get_pending_seed() is self.pending

    @pytest.mark.parametrize("equal_reimport", [False, True])
    @pytest.mark.parametrize("discard", [False, True], ids=["keep", "discard"])
    def test_discard_rechecks_identity_after_screen_selection(self, monkeypatch, equal_reimport, discard):
        self.load_wallets("passphrased_child", multiple=False)
        canonical = Seed(self.target.mnemonic_list, self.target.passphrase)
        view = seed_views.SeedDiscardView(self.target)
        assert not view.has_redirect

        def remove_before_selection(*args, **kwargs):
            self.controller.storage.seeds = [canonical] if equal_reimport else []
            return 1 if discard else 0

        def reject_discard(*args, **kwargs):
            pytest.fail("A stale discard screen must not remove a later wallet")

        monkeypatch.setattr(view, "run_screen", remove_before_selection)
        monkeypatch.setattr(self.controller, "discard_seed", reject_discard)
        destination = view.run()
        assert destination.View_cls is (seed_views.SeedsMenuView if equal_reimport else MainMenuView)
        assert destination.clear_history
        assert len(self.controller.storage.seeds) == int(equal_reimport)
        if equal_reimport:
            assert self.controller.storage.seeds[0] is canonical
        assert self.controller.storage.get_pending_seed() is self.pending

    def test_controller_discard_rejects_equal_but_stale_instance(self):
        self.load_wallets("regular", multiple=False)
        canonical = Seed(self.target.mnemonic_list, self.target.passphrase)
        self.controller.storage.seeds = [canonical]
        with pytest.raises(ValueError, match="no longer loaded"):
            self.controller.discard_seed(self.target)
        assert self.controller.storage.seeds[0] is canonical
        assert self.controller.storage.get_pending_seed() is self.pending


    @pytest.mark.parametrize("kind", KINDS)
    def test_discard_uses_existing_translation_with_actual_wallet_fingerprint(self, monkeypatch, kind):
        self.load_wallets(kind, multiple=True)
        view = seed_views.SeedDiscardView(self.target)
        translated_template = "¿Borrar la semilla {} del dispositivo?"
        lookups = []

        def translate(message):
            lookups.append(message)
            return translated_template if message == "Wipe seed {} from the device?" else message

        def inspect_screen(*args, **kwargs):
            fingerprint = self.target.get_fingerprint()
            assert kwargs["text"] == translated_template.format(fingerprint)
            assert kwargs["lifehash_fingerprint"] == fingerprint
            return 0  # Keep the wallet.

        monkeypatch.setattr(seed_views, "_", translate)
        monkeypatch.setattr(view, "run_screen", inspect_screen)
        destination = view.run()
        assert "Wipe seed {} from the device?" in lookups
        assert destination.View_cls is seed_views.SeedOptionsView
        assert destination.view_args["seed"] is self.target
