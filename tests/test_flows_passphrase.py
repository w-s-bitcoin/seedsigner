import unicodedata

import pytest

# Hardware mocks must be installed before importing the Controller or Views.
from base import FlowStep, FlowTest

from seedsigner.controller import StopFlowBasedTest
from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON
from seedsigner.models.seed import ElectrumSeed, Seed
from seedsigner.models.settings import SettingsConstants
from seedsigner.views import seed_views
from seedsigner.views.view import Destination, MainMenuView


MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about".split()
ELECTRUM_MNEMONIC = "basket print toy noodle betray weird filter ticket insect copy force machine".split()
WALLET_STATE_FIELDS = (
    "psbt", "psbt_parser", "psbt_seed", "resume_main_flow", "multisig_wallet_descriptor",
    "unverified_address", "address_explorer_data", "sign_message_data",
)


class TestLoadedSeedPassphraseFlows(FlowTest):
    def load_seed(self, passphrase=""):
        seed = Seed(MNEMONIC, passphrase=passphrase)
        self.controller.storage.set_pending_seed(seed)
        self.controller.storage.finalize_pending_seed()
        return seed

    @staticmethod
    def expect_screen(**expected):
        """Inspect screen inputs while retaining the normal FlowTest screen mock."""
        def before_run(view):
            run_screen = view.run_screen

            def inspect_screen(*args, **kwargs):
                for key, value in expected.items():
                    assert kwargs[key] == value
                return run_screen(*args, **kwargs)

            view.run_screen = inspect_screen

        return before_run

    def start_edit_steps(self, seed, action="EDIT"):
        steps = [FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.PASSPHRASE)]
        if seed.has_passphrase:
            steps.append(FlowStep(
                seed_views.SeedPassphraseMenuView,
                button_data_selection=getattr(seed_views.SeedPassphraseMenuView, action),
            ))
        else:
            steps.append(FlowStep(seed_views.SeedPassphraseMenuView, is_redirect=True))
        return steps

    @pytest.mark.parametrize("original,action,entered,prefill", [
        ("", "EDIT", "new wallet", ""),
        ("old wallet", "EDIT", "old wallet corrected", "old wallet"),
        ("old wallet", "CHANGE", "another wallet", ""),
        ("old wallet", "REMOVE", "", None),
        ("old wallet", "EDIT", "", "old wallet"),
        ("old wallet", "EDIT", "old wallet", "old wallet"),
        ("", "EDIT", "", ""),
        ("", "EDIT", "  Keep  Spaces!  ", ""),
        ("", "EDIT", "   ", ""),
        ("", "EDIT", "caf\u00e9", ""),
    ])
    def test_apply_replaces_selected_wallet_only_after_confirmation(self, original, action, entered, prefill, monkeypatch):
        seed = self.load_seed(original)
        original_bytes = seed.seed_bytes

        def reject_source_mutation(*args, **kwargs):
            pytest.fail("Deriving the review's no-passphrase fingerprint must not mutate the loaded seed")

        monkeypatch.setattr(seed, "set_passphrase", reject_source_mutation)
        expected = Seed(MNEMONIC, passphrase=entered)
        other_seed = Seed(MNEMONIC, passphrase="unrelated loaded wallet")
        self.controller.storage.seeds.insert(0, other_seed)
        pending = Seed(MNEMONIC, passphrase="unrelated pending wallet")
        self.controller.storage.set_pending_seed(pending)
        confirm_button = (seed_views.SeedConfirmPassphraseView.APPLY if expected.has_passphrase
                          else seed_views.SeedConfirmPassphraseView.REMOVE)
        confirm_buttons = ([confirm_button, seed_views.SeedConfirmPassphraseView.EDIT,
                            seed_views.SeedConfirmPassphraseView.CANCEL] if expected.has_passphrase
                           else [seed_views.SeedConfirmPassphraseView.CANCEL, confirm_button])

        def before_confirm(view):
            assert self.controller.storage.seeds[1] is seed
            assert seed.seed_bytes == original_bytes
            assert seed.passphrase == original
            assert self.controller.storage.get_pending_seed() is pending
            self.expect_screen(
                fingerprint_without="73c5da0a",
                fingerprint_new=expected.get_fingerprint(),
                passphrase=expected.passphrase_display,
                page_index=0,
                button_data=confirm_buttons,
                selected_button=0,
                show_back_button=False,
            )(view)

        def after_apply(view):
            assert view.seed is self.controller.storage.seeds[1]
            assert view.seed.seed_bytes == expected.seed_bytes
            assert len(self.controller.back_stack) == 1
            self.expect_screen(
                fingerprint=expected.get_fingerprint(),
                fingerprint_without="73c5da0a" if expected.has_passphrase else None,
            )(view)

        sequence = self.start_edit_steps(seed, action)
        if action != "REMOVE":
            sequence.append(FlowStep(
                seed_views.SeedEditPassphraseView,
                before_run=self.expect_screen(passphrase=prefill),
                screen_return_value=dict(passphrase=entered),
            ))
        sequence.append(FlowStep(seed_views.SeedConfirmPassphraseView, before_run=before_confirm,
                                 button_data_selection=confirm_button))
        if expected.has_passphrase:
            sequence.append(FlowStep(seed_views.SeedPassphraseSaveView,
                                     button_data_selection=seed_views.SeedPassphraseSaveView.REPLACE))
        sequence.append(FlowStep(seed_views.SeedOptionsView, before_run=after_apply,
                                 screen_return_value=StopFlowBasedTest()))
        self.run_sequence(sequence, initial_destination_view_args=dict(seed=seed))

        assert len(self.controller.storage.seeds) == 2
        assert self.controller.storage.seeds[0] is other_seed
        assert self.controller.storage.seeds[1].passphrase == unicodedata.normalize("NFKD", entered)
        assert seed.seed_bytes == original_bytes
        assert seed.passphrase == original
        assert self.controller.storage.get_pending_seed() is pending
        if expected == seed:
            assert self.controller.storage.seeds[1] is seed
        else:
            assert self.controller.storage.seeds[1] is not seed

    @pytest.mark.parametrize("action", ["EDIT", "REMOVE"])
    def test_cancel_confirmation_preserves_original_wallet(self, action):
        seed = self.load_seed("original passphrase")
        original_bytes = seed.seed_bytes
        sequence = self.start_edit_steps(seed, action)
        if action == "EDIT":
            sequence.append(FlowStep(seed_views.SeedEditPassphraseView, screen_return_value=dict(passphrase="changed")))

        def after_cancel(view):
            assert view.seed is seed
            assert len(self.controller.back_stack) == 1

        if action == "REMOVE":
            # Accepting the initially selected button must cancel, not remove.
            confirmation_step = FlowStep(
                seed_views.SeedConfirmPassphraseView,
                before_run=self.expect_screen(
                    fingerprint_new=Seed(MNEMONIC).get_fingerprint(),
                    passphrase="",
                    button_data=[seed_views.SeedConfirmPassphraseView.CANCEL,
                                 seed_views.SeedConfirmPassphraseView.REMOVE],
                ),
                screen_return_value=0,
            )
        else:
            confirmation_step = FlowStep(
                seed_views.SeedConfirmPassphraseView,
                button_data_selection=seed_views.SeedConfirmPassphraseView.CANCEL,
            )
        sequence.extend([
            confirmation_step,
            FlowStep(seed_views.SeedOptionsView, before_run=after_cancel, screen_return_value=StopFlowBasedTest()),
        ])
        self.run_sequence(sequence, initial_destination_view_args=dict(seed=seed))
        assert self.controller.storage.seeds == [seed]
        assert self.controller.storage.seeds[0] is seed
        assert seed.seed_bytes == original_bytes
        assert seed.passphrase == "original passphrase"

    @pytest.mark.parametrize("original", ["", "original passphrase"])
    def test_keyboard_back_discard_preserves_original_wallet(self, original):
        seed = self.load_seed(original)
        original_bytes = seed.seed_bytes
        self.run_sequence(self.start_edit_steps(seed) + [
            FlowStep(seed_views.SeedEditPassphraseView, screen_return_value=dict(passphrase="unfinished", is_back_button=True)),
            FlowStep(seed_views.SeedCancelPassphraseView, button_data_selection=seed_views.SeedCancelPassphraseView.DISCARD),
            FlowStep(seed_views.SeedOptionsView),
        ], initial_destination_view_args=dict(seed=seed))
        assert self.controller.storage.seeds[0] is seed
        assert seed.seed_bytes == original_bytes
        assert seed.passphrase == original
        assert self.controller.storage.get_pending_seed() is None

    def test_keyboard_back_keep_editing_preserves_draft(self):
        seed = self.load_seed("original passphrase")
        self.run_sequence(self.start_edit_steps(seed) + [
            FlowStep(seed_views.SeedEditPassphraseView, screen_return_value=dict(passphrase="unfinished", is_back_button=True)),
            FlowStep(seed_views.SeedCancelPassphraseView, button_data_selection=seed_views.SeedCancelPassphraseView.KEEP_EDITING),
            FlowStep(seed_views.SeedEditPassphraseView, before_run=self.expect_screen(passphrase="unfinished"),
                     screen_return_value=dict(passphrase="finished")),
            FlowStep(seed_views.SeedConfirmPassphraseView, button_data_selection=seed_views.SeedConfirmPassphraseView.APPLY),
            FlowStep(seed_views.SeedPassphraseSaveView, button_data_selection=seed_views.SeedPassphraseSaveView.REPLACE),
            FlowStep(seed_views.SeedOptionsView),
        ], initial_destination_view_args=dict(seed=seed))
        assert seed.passphrase == "original passphrase"
        assert self.controller.storage.seeds[0].passphrase == "finished"

    def test_edit_from_confirmation_preserves_draft(self):
        seed = self.load_seed("original passphrase")
        self.run_sequence(self.start_edit_steps(seed) + [
            FlowStep(seed_views.SeedEditPassphraseView, screen_return_value=dict(passphrase="draft")),
            FlowStep(seed_views.SeedConfirmPassphraseView, button_data_selection=seed_views.SeedConfirmPassphraseView.EDIT),
            FlowStep(seed_views.SeedEditPassphraseView, before_run=self.expect_screen(passphrase="draft"),
                     screen_return_value=dict(passphrase="corrected")),
            FlowStep(seed_views.SeedConfirmPassphraseView, button_data_selection=seed_views.SeedConfirmPassphraseView.APPLY),
            FlowStep(seed_views.SeedPassphraseSaveView, button_data_selection=seed_views.SeedPassphraseSaveView.REPLACE),
            FlowStep(seed_views.SeedOptionsView),
        ], initial_destination_view_args=dict(seed=seed))
        assert seed.passphrase == "original passphrase"
        assert self.controller.storage.seeds[0].passphrase == "corrected"

    def test_long_passphrase_requires_all_review_pages_and_is_not_logged(self, caplog):
        seed = self.load_seed("original passphrase")
        passphrase = "Secret value with leading and trailing spaces: " * 2
        sequence = self.start_edit_steps(seed) + [
            FlowStep(seed_views.SeedEditPassphraseView, screen_return_value=dict(passphrase=passphrase)),
        ]
        for page_index in range(3):
            primary_button = (seed_views.SeedConfirmPassphraseView.APPLY if page_index == 2
                              else seed_views.SeedConfirmPassphraseView.NEXT)
            sequence.append(FlowStep(
                seed_views.SeedConfirmPassphraseView,
                before_run=self.expect_screen(
                    page_index=page_index,
                    fingerprint_without="73c5da0a",
                    passphrase=passphrase,
                    button_data=[primary_button, seed_views.SeedConfirmPassphraseView.EDIT,
                                 seed_views.SeedConfirmPassphraseView.CANCEL],
                    selected_button=0,
                ),
                button_data_selection=primary_button,
            ))
        sequence.extend([
            FlowStep(seed_views.SeedPassphraseSaveView, button_data_selection=seed_views.SeedPassphraseSaveView.REPLACE),
            FlowStep(seed_views.SeedOptionsView),
        ])
        self.run_sequence(sequence, initial_destination_view_args=dict(seed=seed))
        assert self.controller.storage.seeds[0].passphrase == passphrase
        assert passphrase not in caplog.text
        assert "original passphrase" not in caplog.text

    def test_initial_long_passphrase_is_not_finalized_until_last_review_page(self):
        passphrase = "A" * 44 + "B" * 44 + "TAIL"
        pending = Seed(MNEMONIC, passphrase=passphrase)
        self.controller.storage.set_pending_seed(pending)
        fingerprint_with = pending.get_fingerprint()
        sequence = []

        def before_review(page_index):
            def inspect(view):
                assert self.controller.storage.get_pending_seed() is pending
                assert self.controller.storage.seeds == []
                self.expect_screen(
                    fingerprint_without="73c5da0a",
                    fingerprint_with=fingerprint_with,
                    page_index=page_index,
                    button_data=[seed_views.SeedReviewPassphraseView.EDIT,
                                 seed_views.SeedReviewPassphraseView.DONE if page_index == 2
                                 else seed_views.SeedReviewPassphraseView.NEXT],
                )(view)
            return inspect

        for page_index in range(3):
            sequence.append(FlowStep(
                seed_views.SeedReviewPassphraseView,
                before_run=before_review(page_index),
                button_data_selection=(seed_views.SeedReviewPassphraseView.DONE if page_index == 2
                                       else seed_views.SeedReviewPassphraseView.NEXT),
            ))
        sequence.append(FlowStep(seed_views.SeedOptionsView))
        self.run_sequence(sequence)
        assert self.controller.storage.seeds == [pending]
        assert pending.passphrase == passphrase
        assert self.controller.storage.get_pending_seed() is None

    def test_editing_from_later_initial_review_page_restarts_review(self):
        pending = Seed(MNEMONIC, passphrase="A" * 90)
        self.controller.storage.set_pending_seed(pending)
        self.run_sequence([
            FlowStep(seed_views.SeedReviewPassphraseView,
                     button_data_selection=seed_views.SeedReviewPassphraseView.NEXT),
            FlowStep(seed_views.SeedReviewPassphraseView,
                     before_run=self.expect_screen(page_index=1),
                     button_data_selection=seed_views.SeedReviewPassphraseView.EDIT),
            FlowStep(seed_views.SeedAddPassphraseView,
                     before_run=self.expect_screen(passphrase="A" * 90),
                     screen_return_value=dict(passphrase="short")),
            FlowStep(seed_views.SeedReviewPassphraseView,
                     before_run=self.expect_screen(page_index=0),
                     button_data_selection=seed_views.SeedReviewPassphraseView.DONE),
            FlowStep(seed_views.SeedOptionsView),
        ])
        assert self.controller.storage.seeds == [pending]
        assert pending.passphrase == "short"

    @pytest.mark.parametrize("passphrase,setting,expected_baseline", [
        ("", SettingsConstants.OPTION__ENABLED, None),
        ("a", SettingsConstants.OPTION__ENABLED, "73c5da0a"),
        ("a", SettingsConstants.OPTION__DISABLED, "73c5da0a"),
    ])
    def test_seed_menu_identifies_passphrase_relationship_independent_of_edit_setting(
            self, passphrase, setting, expected_baseline):
        seed = self.load_seed(passphrase)
        self.settings.set_value(SettingsConstants.SETTING__PASSPHRASE, setting)
        self.run_sequence([
            FlowStep(seed_views.SeedOptionsView,
                     before_run=self.expect_screen(
                         fingerprint="a63dbf9c" if passphrase else "73c5da0a",
                         fingerprint_without=expected_baseline,
                     ),
                     screen_return_value=StopFlowBasedTest()),
        ], initial_destination_view_args=dict(seed=seed))
        assert self.controller.storage.seeds[0] is seed
        assert seed.passphrase == passphrase

    def test_back_from_passphrase_menu_preserves_original_wallet(self):
        seed = self.load_seed("original passphrase")
        self.run_sequence([
            FlowStep(seed_views.SeedOptionsView, button_data_selection=seed_views.SeedOptionsView.PASSPHRASE),
            FlowStep(seed_views.SeedPassphraseMenuView, screen_return_value=RET_CODE__BACK_BUTTON),
            FlowStep(seed_views.SeedOptionsView),
        ], initial_destination_view_args=dict(seed=seed))
        assert self.controller.storage.seeds[0] is seed
        assert seed.passphrase == "original passphrase"

    @pytest.mark.parametrize("action,resulting_passphrase", [("CHANGE", "already loaded"), ("REMOVE", "")])
    def test_apply_selects_existing_wallet_when_result_is_already_loaded(self, action, resulting_passphrase):
        seed = self.load_seed("original passphrase")
        existing = Seed(MNEMONIC, passphrase=resulting_passphrase)
        self.controller.storage.seeds.append(existing)
        sequence = self.start_edit_steps(seed, action)
        if action == "CHANGE":
            sequence.append(FlowStep(seed_views.SeedEditPassphraseView, screen_return_value=dict(passphrase=resulting_passphrase)))

        def after_apply(view):
            assert view.seed is existing

        sequence.append(FlowStep(seed_views.SeedConfirmPassphraseView,
                                 button_data_selection=(seed_views.SeedConfirmPassphraseView.APPLY if resulting_passphrase
                                                        else seed_views.SeedConfirmPassphraseView.REMOVE)))
        if resulting_passphrase:
            sequence.append(FlowStep(seed_views.SeedPassphraseSaveView,
                                     button_data_selection=seed_views.SeedPassphraseSaveView.REPLACE))
        sequence.append(FlowStep(seed_views.SeedOptionsView, before_run=after_apply,
                                 screen_return_value=StopFlowBasedTest()))
        self.run_sequence(sequence, initial_destination_view_args=dict(seed=seed))
        assert len(self.controller.storage.seeds) == 1
        assert self.controller.storage.seeds[0] is existing
        assert seed.passphrase == "original passphrase"

    @pytest.mark.parametrize("original", ["", "original passphrase"])
    @pytest.mark.parametrize("load_separately", [False, True])
    @pytest.mark.parametrize("already_loaded", [False, True])
    def test_save_choice_commits_only_after_choice_and_selects_canonical_wallet(
            self, original, load_separately, already_loaded):
        import weakref

        seed = self.load_seed(original)
        original_bytes = seed.seed_bytes
        other = Seed(MNEMONIC, "unrelated wallet")
        self.controller.storage.seeds.insert(0, other)
        pending = Seed(MNEMONIC, "pending wallet")
        self.controller.storage.set_pending_seed(pending)
        expected = Seed(MNEMONIC, "saved choice wallet")
        if already_loaded:
            self.controller.storage.seeds.append(expected)
        state = {field: object() for field in WALLET_STATE_FIELDS}
        candidate_reference = []

        def before_review(view):
            candidate_reference.append(weakref.ref(view.candidate))
            for field, value in state.items():
                setattr(self.controller, field, value)

        def before_choice(view):
            assert view.seed is seed
            assert view.candidate is candidate_reference[0]()
            assert self.controller.storage.seeds[1] is seed
            assert seed.passphrase == original
            assert self.controller.storage.get_pending_seed() is pending
            assert all(getattr(self.controller, field) is value for field, value in state.items())
            self.expect_screen(
                fingerprint_without="73c5da0a", fingerprint_new=expected.get_fingerprint(),
                selected_button=0,
                button_data=[seed_views.SeedPassphraseSaveView.REPLACE,
                             seed_views.SeedPassphraseSaveView.LOAD_SEPARATELY,
                             seed_views.SeedPassphraseSaveView.CANCEL],
            )(view)

        def after_commit(view):
            assert view.seed is (expected if already_loaded else candidate_reference[0]())
            assert view.seed.seed_bytes == expected.seed_bytes
            assert self.controller.storage.seeds[0] is other
            assert self.controller.storage.seeds[-1] is view.seed
            assert len(self.controller.storage.seeds) == (3 if load_separately else 2)
            assert any(loaded is seed for loaded in self.controller.storage.seeds) is load_separately
            assert seed.seed_bytes is original_bytes
            assert seed.passphrase == original
            assert self.controller.storage.get_pending_seed() is pending
            assert all(getattr(self.controller, field) is None for field in WALLET_STATE_FIELDS)
            assert len(self.controller.back_stack) == 1

        choice_step = FlowStep(seed_views.SeedPassphraseSaveView, before_run=before_choice,
                               button_data_selection=seed_views.SeedPassphraseSaveView.LOAD_SEPARATELY)
        if not load_separately:
            # The explicitly selected default commits Replace current.
            choice_step = FlowStep(seed_views.SeedPassphraseSaveView, before_run=before_choice, screen_return_value=0)
        self.run_sequence(self.start_edit_steps(seed) + [
            FlowStep(seed_views.SeedEditPassphraseView, screen_return_value={"passphrase": expected.passphrase}),
            FlowStep(seed_views.SeedConfirmPassphraseView, before_run=before_review,
                     button_data_selection=seed_views.SeedConfirmPassphraseView.APPLY),
            choice_step,
            FlowStep(seed_views.SeedOptionsView, before_run=after_commit, screen_return_value=StopFlowBasedTest()),
        ], initial_destination_view_args={"seed": seed})

    def test_cancelling_save_choice_preserves_wallet_state_and_releases_candidate(self):
        import gc
        import weakref

        seed = self.load_seed("original passphrase")
        pending = Seed(MNEMONIC, "pending wallet")
        self.controller.storage.set_pending_seed(pending)
        state = {field: object() for field in WALLET_STATE_FIELDS}
        candidate_reference = []

        def before_choice(view):
            candidate_reference.append(weakref.ref(view.candidate))
            for field, value in state.items():
                setattr(self.controller, field, value)

        def after_cancel(view):
            assert view.seed is seed
            assert self.controller.storage.seeds == [seed]
            assert seed.passphrase == "original passphrase"
            assert self.controller.storage.get_pending_seed() is pending
            assert all(getattr(self.controller, field) is value for field, value in state.items())
            assert len(self.controller.back_stack) == 1
            # Stop before unrelated suspended wallet flows resume on this menu.
            raise StopFlowBasedTest()

        choice_step = FlowStep(seed_views.SeedPassphraseSaveView, before_run=before_choice,
                               button_data_selection=seed_views.SeedPassphraseSaveView.CANCEL)
        self.run_sequence(self.start_edit_steps(seed) + [
            FlowStep(seed_views.SeedEditPassphraseView, screen_return_value={"passphrase": "discarded candidate"}),
            FlowStep(seed_views.SeedConfirmPassphraseView,
                     button_data_selection=seed_views.SeedConfirmPassphraseView.APPLY),
            choice_step,
            FlowStep(seed_views.SeedOptionsView, before_run=after_cancel, screen_return_value=StopFlowBasedTest()),
        ], initial_destination_view_args={"seed": seed})
        gc.collect()
        assert candidate_reference[0]() is None

    @pytest.mark.parametrize("long_passphrase", [False, True])
    @pytest.mark.parametrize("edit_after_back", [False, True])
    def test_save_back_restores_last_review_without_mutation_or_history_growth(self, long_passphrase, edit_after_back):
        import weakref

        seed = self.load_seed("original passphrase")
        seed_bytes = seed.seed_bytes
        pending = Seed(MNEMONIC, "pending wallet")
        self.controller.storage.set_pending_seed(pending)
        passphrase = "A" * 44 + "B" * 44 + "TAIL" if long_passphrase else "new wallet"
        num_pages = 3 if long_passphrase else 1
        state = {field: object() for field in WALLET_STATE_FIELDS}
        candidate_reference = []
        last_review_history_size = []

        def assert_uncommitted(view, expected_passphrase):
            if not candidate_reference:
                candidate_reference.append(weakref.ref(view.candidate))
                for field, value in state.items():
                    setattr(self.controller, field, value)
            assert view.candidate is candidate_reference[0]()
            assert view.candidate.passphrase == expected_passphrase
            assert self.controller.storage.seeds == [seed]
            assert self.controller.storage.seeds[0] is seed
            assert seed.seed_bytes is seed_bytes
            assert seed.passphrase == "original passphrase"
            assert self.controller.storage.get_pending_seed() is pending
            assert all(getattr(self.controller, field) is value for field, value in state.items())

        def before_review(page_index, expected_passphrase=passphrase, after_edit=False):
            def inspect(view):
                assert_uncommitted(view, expected_passphrase)
                assert view.page_index == page_index
                last_page = page_index == (0 if after_edit else num_pages - 1)
                if last_page and not after_edit:
                    if not last_review_history_size:
                        last_review_history_size.append(len(self.controller.back_stack))
                    assert len(self.controller.back_stack) == last_review_history_size[0]
                primary = seed_views.SeedConfirmPassphraseView.APPLY if last_page else seed_views.SeedConfirmPassphraseView.NEXT
                self.expect_screen(
                    page_index=page_index, passphrase=expected_passphrase, selected_button=0,
                    button_data=[primary, seed_views.SeedConfirmPassphraseView.EDIT,
                                 seed_views.SeedConfirmPassphraseView.CANCEL],
                )(view)
            return inspect

        def before_choice(view):
            assert_uncommitted(view, passphrase)
            assert len(self.controller.back_stack) == last_review_history_size[0] + 1

        sequence = self.start_edit_steps(seed) + [
            FlowStep(seed_views.SeedEditPassphraseView, screen_return_value={"passphrase": passphrase}),
        ]
        for page_index in range(num_pages - 1):
            sequence.append(FlowStep(seed_views.SeedConfirmPassphraseView,
                                     before_run=before_review(page_index), screen_return_value=0))
        # Two complete review -> save -> Back round trips must revisit the same
        # final review page and candidate without accumulating history entries.
        for _ in range(2):
            sequence.extend([
                FlowStep(seed_views.SeedConfirmPassphraseView,
                         before_run=before_review(num_pages - 1), screen_return_value=0),
                FlowStep(seed_views.SeedPassphraseSaveView, before_run=before_choice,
                         screen_return_value=RET_CODE__BACK_BUTTON),
            ])
        if edit_after_back:
            sequence.extend([
                FlowStep(seed_views.SeedConfirmPassphraseView, before_run=before_review(num_pages - 1),
                         button_data_selection=seed_views.SeedConfirmPassphraseView.EDIT),
                FlowStep(seed_views.SeedEditPassphraseView, before_run=self.expect_screen(passphrase=passphrase),
                         screen_return_value={"passphrase": "corrected wallet"}),
                FlowStep(seed_views.SeedConfirmPassphraseView,
                         before_run=before_review(0, "corrected wallet", after_edit=True), screen_return_value=0),
            ])
        else:
            sequence.append(FlowStep(seed_views.SeedConfirmPassphraseView,
                                     before_run=before_review(num_pages - 1), screen_return_value=0))

        def after_commit(view):
            assert view.seed is candidate_reference[0]()
            assert view.seed.passphrase == ("corrected wallet" if edit_after_back else passphrase)
            assert self.controller.storage.seeds[0] is view.seed
            assert all(getattr(self.controller, field) is None for field in WALLET_STATE_FIELDS)
            assert len(self.controller.back_stack) == 1

        sequence.extend([
            FlowStep(seed_views.SeedPassphraseSaveView, button_data_selection=seed_views.SeedPassphraseSaveView.REPLACE),
            FlowStep(seed_views.SeedOptionsView, before_run=after_commit, screen_return_value=StopFlowBasedTest()),
        ])
        self.run_sequence(sequence, initial_destination_view_args={"seed": seed})

    @pytest.mark.parametrize("load_separately", [False, True])
    def test_unchanged_passphrase_still_offers_choice_without_duplicate_seed(self, load_separately):
        seed = self.load_seed("unchanged wallet")
        state = {field: object() for field in WALLET_STATE_FIELDS}

        def before_choice(view):
            assert view.candidate == seed
            assert view.candidate is not seed
            for field, value in state.items():
                setattr(self.controller, field, value)

        def after_choice(view):
            assert view.seed is seed
            assert len(self.controller.storage.seeds) == 1
            assert self.controller.storage.seeds[0] is seed
            for field, value in state.items():
                assert getattr(self.controller, field) is (None if load_separately else value)
            raise StopFlowBasedTest()

        self.run_sequence(self.start_edit_steps(seed) + [
            FlowStep(seed_views.SeedEditPassphraseView, screen_return_value={"passphrase": seed.passphrase}),
            FlowStep(seed_views.SeedConfirmPassphraseView,
                     button_data_selection=seed_views.SeedConfirmPassphraseView.APPLY),
            FlowStep(seed_views.SeedPassphraseSaveView, before_run=before_choice,
                     button_data_selection=(seed_views.SeedPassphraseSaveView.LOAD_SEPARATELY if load_separately
                                            else seed_views.SeedPassphraseSaveView.REPLACE)),
            FlowStep(seed_views.SeedOptionsView, before_run=after_choice, screen_return_value=StopFlowBasedTest()),
        ], initial_destination_view_args={"seed": seed})

    @pytest.mark.parametrize("unavailable", ["disabled", "electrum", "stale"])
    def test_save_choice_direct_navigation_enforces_source_and_setting_guards(self, unavailable):
        seed = self.load_seed("original passphrase")
        if unavailable == "disabled":
            self.settings.set_value(SettingsConstants.SETTING__PASSPHRASE, SettingsConstants.OPTION__DISABLED)
        elif unavailable == "electrum":
            seed = ElectrumSeed(ELECTRUM_MNEMONIC)
            self.controller.storage.seeds = [seed]
        else:
            self.controller.storage.seeds = [Seed(MNEMONIC, "original passphrase")]
        stored = list(self.controller.storage.seeds)
        candidate = Seed(MNEMONIC, "must not load")
        self.controller.back_stack.append(Destination(seed_views.SeedPassphraseSaveView,
                                                      view_args={"seed": seed, "candidate": candidate}))
        self.run_sequence([
            FlowStep(seed_views.SeedPassphraseSaveView, is_redirect=True),
            FlowStep(seed_views.SeedsMenuView if unavailable == "stale" else seed_views.SeedOptionsView),
        ], initial_destination_view_args={"seed": seed, "candidate": candidate})
        assert len(self.controller.storage.seeds) == 1
        assert self.controller.storage.seeds[0] is stored[0]

    @pytest.mark.parametrize("action", ["replace", "separate", "remove"])
    @pytest.mark.parametrize("change", ["source_removed", "equal_reimport", "disabled"])
    def test_final_passphrase_action_rechecks_source_and_setting(self, monkeypatch, action, change):
        original = self.load_seed("original wallet")
        pending = Seed(MNEMONIC, "unrelated pending wallet")
        self.controller.storage.set_pending_seed(pending)
        candidate = Seed(MNEMONIC, "" if action == "remove" else "candidate wallet")
        view_type = (seed_views.SeedConfirmPassphraseView if action == "remove"
                     else seed_views.SeedPassphraseSaveView)
        view = view_type(original, candidate=candidate)
        assert not view.has_redirect
        canonical = Seed(MNEMONIC, original.passphrase)

        def change_before_selection(*args, **kwargs):
            if change == "source_removed":
                self.controller.storage.seeds.clear()
            elif change == "equal_reimport":
                self.controller.storage.seeds = [canonical]
            else:
                self.settings.set_value(SettingsConstants.SETTING__PASSPHRASE,
                                        SettingsConstants.OPTION__DISABLED)
            return 0 if action == "replace" else 1

        def reject_commit(*args, **kwargs):
            pytest.fail("Unavailable passphrase editing must not commit its candidate")

        monkeypatch.setattr(view, "run_screen", change_before_selection)
        monkeypatch.setattr(self.controller, "load_seed", reject_commit)
        monkeypatch.setattr(self.controller, "replace_seed", reject_commit)
        destination = view.run()
        assert destination.View_cls is (seed_views.SeedOptionsView if change == "disabled"
                                        else seed_views.SeedsMenuView)
        assert destination.clear_history
        expected = [] if change == "source_removed" else [canonical if change == "equal_reimport" else original]
        assert len(self.controller.storage.seeds) == len(expected)
        assert all(actual is saved for actual, saved in zip(self.controller.storage.seeds, expected))
        assert original.passphrase == "original wallet"
        assert self.controller.storage.get_pending_seed() is pending

    @pytest.mark.parametrize("passphrase_setting,seed_type,expected_visible", [
        (None, Seed, True),
        (SettingsConstants.OPTION__ENABLED, Seed, True),
        (SettingsConstants.OPTION__REQUIRED, Seed, True),
        (SettingsConstants.OPTION__DISABLED, Seed, False),
        (SettingsConstants.OPTION__ENABLED, ElectrumSeed, False),
    ])
    def test_passphrase_menu_gating(self, passphrase_setting, seed_type, expected_visible):
        if passphrase_setting is not None:
            self.settings.set_value(SettingsConstants.SETTING__PASSPHRASE, passphrase_setting)
        seed = seed_type(ELECTRUM_MNEMONIC if seed_type is ElectrumSeed else MNEMONIC)
        self.controller.storage.seeds.append(seed)

        def inspect_menu(view):
            run_screen = view.run_screen

            def inspect_screen(*args, **kwargs):
                assert (seed_views.SeedOptionsView.PASSPHRASE in kwargs["button_data"]) is expected_visible
                return run_screen(*args, **kwargs)

            view.run_screen = inspect_screen

        self.run_sequence([
            FlowStep(seed_views.SeedOptionsView, before_run=inspect_menu, screen_return_value=RET_CODE__BACK_BUTTON),
            FlowStep(seed_views.SeedsMenuView, screen_return_value=RET_CODE__BACK_BUTTON),
            FlowStep(MainMenuView),
        ], initial_destination_view_args=dict(seed=seed))
