import pytest

# Install hardware mocks before importing the application Views.
from base import FlowStep, FlowTest

from seedsigner.controller import StopFlowBasedTest
from seedsigner.gui.components import GUIConstants
from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON
from seedsigner.models.seed import Seed
from seedsigner.models.seed_storage import SeedStorage
from seedsigner.models.settings import SettingsConstants
from seedsigner.views import seed_views
from seedsigner.views.view import Destination


MNEMONIC = ["abandon"] * 11 + ["about"]

# Public test seed: MNEMONIC with the BIP39 passphrase TREZOR. These goldens were
# derived independently of Seed.get_bip85_child_mnemonic using the hardened path
# m/83696968'/39'/0'/{word_count}'/{index}' and HMAC-SHA512("bip-entropy-from-k", k).
CHILDREN = [
    (12, 0, "47c88c48", "climb typical because giraffe beach wool fit ship common chapter hotel arm"),
    (12, 2**31 - 1, "a18dd64b", "always have female giant cannon resource mercy blue real when modify trouble"),
    (24, 0, "b61f4fbe", "guess violin output company next ribbon submit simple balance toss buffalo number fire horn mystery assault require opinion social pony obey system winter pupil"),
    (24, 2**31 - 1, "b0c90adb", "rate flash cycle boat unfair fortune humor tunnel song hurt club round famous resource rent inspire lounge hour used spare front mix rough scorpion"),
]


class TestBIP85Flows(FlowTest):
    def inspect_options_header(self, parent_fingerprint, current_fingerprint, without_passphrase=None):
        def before_run(view):
            run_screen = view.run_screen

            def inspect_screen(*args, **kwargs):
                assert kwargs["fingerprint_parent"] == parent_fingerprint
                assert kwargs["fingerprint"] == current_fingerprint
                assert kwargs["fingerprint_without"] == without_passphrase
                return run_screen(*args, **kwargs)

            view.run_screen = inspect_screen

        return before_run

    def load_parent(self):
        parent = Seed(MNEMONIC, "TREZOR")
        assert not parent.is_bip85_child
        self.controller.storage.seeds = [Seed(MNEMONIC, "other wallet"), parent]
        self.controller.storage.set_pending_seed(Seed(MNEMONIC, "pending wallet"))
        self.settings.set_value(SettingsConstants.SETTING__DIRE_WARNINGS, SettingsConstants.OPTION__ENABLED)
        self.settings.set_value(SettingsConstants.SETTING__BIP85_CHILD_SEEDS, SettingsConstants.OPTION__ENABLED)
        self.settings.set_value(SettingsConstants.SETTING__PASSPHRASE, SettingsConstants.OPTION__ENABLED)
        return parent

    def inspect_review(self, parent, num_words, child_index, child_fingerprint):
        def before_run(view):
            assert view.seed is parent
            run_screen = view.run_screen

            def inspect_screen(*args, **kwargs):
                # BIP85's source is the selected wallet, including its passphrase.
                assert kwargs["fingerprint_parent"] == parent.get_fingerprint() == "b4e3f5ed"
                assert kwargs["fingerprint_parent"] != parent.get_fingerprint_without_passphrase()
                assert kwargs["fingerprint_child"] == child_fingerprint
                assert kwargs["num_words"] == num_words
                assert kwargs["child_index"] == child_index
                return run_screen(*args, **kwargs)

            view.run_screen = inspect_screen

        return before_run

    @pytest.mark.parametrize("num_words,child_index,child_fingerprint,child_mnemonic", CHILDREN)
    def test_review_and_word_pages_identify_actual_parent_and_same_child(
            self, num_words, child_index, child_fingerprint, child_mnemonic):
        parent = self.load_parent()
        stored_seeds = list(self.controller.storage.seeds)
        pending_seed = self.controller.storage.get_pending_seed()
        parent_bytes = parent.seed_bytes
        parent_mnemonic = parent.mnemonic_list
        words = child_mnemonic.split()
        displayed_words = []

        def inspect_words(page_index):
            def before_run(view):
                assert view.seed is parent
                assert view.bip85_data == {"num_words": num_words, "child_index": child_index}
                run_screen = view.run_screen

                def inspect_screen(*args, **kwargs):
                    assert kwargs["fingerprint_parent"] == "b4e3f5ed"
                    assert kwargs["fingerprint_child"] == child_fingerprint
                    assert kwargs["child_index"] == child_index
                    assert kwargs["num_pages"] == num_words // 3
                    assert kwargs["page_index"] == page_index
                    assert kwargs["words"] == words[page_index * 3:(page_index + 1) * 3]
                    displayed_words.extend(kwargs["words"])
                    return run_screen(*args, **kwargs)

                view.run_screen = inspect_screen

            return before_run

        sequence = [
            FlowStep(seed_views.SeedBIP85SelectNumWordsView, button_data_selection=(
                seed_views.SeedBIP85SelectNumWordsView.WORDS_12 if num_words == 12
                else seed_views.SeedBIP85SelectNumWordsView.WORDS_24)),
            FlowStep(seed_views.SeedBIP85SelectChildIndexView, screen_return_value=str(child_index)),
            FlowStep(seed_views.SeedBIP85ReviewView,
                     before_run=self.inspect_review(parent, num_words, child_index, child_fingerprint),
                     button_data_selection=seed_views.SeedBIP85ReviewView.VIEW_WORDS),
            FlowStep(seed_views.SeedWordsWarningView, screen_return_value=0),
        ]
        for page_index in range(num_words // 3):
            sequence.append(FlowStep(
                seed_views.SeedWordsView,
                before_run=inspect_words(page_index),
                button_data_selection=(seed_views.SeedWordsView.DONE if page_index == num_words // 3 - 1
                                       else seed_views.SeedWordsView.NEXT),
            ))
        sequence.extend([
            FlowStep(seed_views.SeedWordsBackupTestPromptView,
                     button_data_selection=seed_views.SeedWordsBackupTestPromptView.LOAD_CHILD),
            FlowStep(seed_views.SeedBIP85LoadChildView, is_redirect=True),
            FlowStep(seed_views.SeedOptionsView,
                     before_run=self.inspect_options_header("b4e3f5ed", child_fingerprint),
                     screen_return_value=StopFlowBasedTest()),
        ])

        self.run_sequence(sequence, initial_destination_view_args={"seed": parent})

        assert displayed_words == words
        assert Seed(displayed_words).get_fingerprint() == child_fingerprint
        assert all(actual is expected for actual, expected in zip(self.controller.storage.seeds, stored_seeds))
        assert len(self.controller.storage.seeds) == len(stored_seeds) + 1
        child = self.controller.storage.seeds[-1]
        assert child is not parent
        assert child.mnemonic_list == words
        assert not child.has_passphrase
        assert child.is_bip85_child
        assert child.bip85_parent_fingerprint == "b4e3f5ed"
        assert child.get_fingerprint() == child_fingerprint
        assert self.controller.storage.get_pending_seed() is pending_seed
        assert parent.seed_bytes is parent_bytes
        assert parent.mnemonic_list is parent_mnemonic
        assert parent.passphrase == "TREZOR"
        assert self.controller.back_stack[-1].view_args["seed"] is child

    def test_back_from_review_returns_to_index_with_same_parent_and_word_count(self):
        parent = self.load_parent()

        def inspect_index(view):
            assert view.seed is parent
            assert view.num_words == 24

        self.run_sequence([
            FlowStep(seed_views.SeedBIP85SelectNumWordsView,
                     button_data_selection=seed_views.SeedBIP85SelectNumWordsView.WORDS_24),
            FlowStep(seed_views.SeedBIP85SelectChildIndexView, screen_return_value="0"),
            FlowStep(seed_views.SeedBIP85ReviewView,
                     before_run=self.inspect_review(parent, 24, 0, "b61f4fbe"),
                     screen_return_value=RET_CODE__BACK_BUTTON),
            FlowStep(seed_views.SeedBIP85SelectChildIndexView,
                     before_run=inspect_index, screen_return_value=StopFlowBasedTest()),
        ], initial_destination_view_args={"seed": parent})

        assert self.controller.storage.seeds[1] is parent
        assert parent.passphrase == "TREZOR"

    @pytest.mark.parametrize("invalid_index", ["-1", str(2**31)])
    def test_invalid_index_retries_before_deriving_or_reviewing_child(self, invalid_index):
        parent = self.load_parent()

        def inspect_retry(view):
            assert view.seed is parent
            assert view.num_words == 12

        self.run_sequence([
            FlowStep(seed_views.SeedBIP85SelectNumWordsView,
                     button_data_selection=seed_views.SeedBIP85SelectNumWordsView.WORDS_12),
            FlowStep(seed_views.SeedBIP85SelectChildIndexView, screen_return_value=invalid_index),
            FlowStep(seed_views.SeedBIP85InvalidChildIndexView,
                     before_run=inspect_retry, screen_return_value=0),
            FlowStep(seed_views.SeedBIP85SelectChildIndexView,
                     before_run=inspect_retry, screen_return_value="0"),
            FlowStep(seed_views.SeedBIP85ReviewView,
                     before_run=self.inspect_review(parent, 12, 0, "47c88c48"),
                     screen_return_value=StopFlowBasedTest()),
        ], initial_destination_view_args={"seed": parent})

        assert self.controller.storage.seeds[1] is parent

    def test_ordinary_seed_words_keep_four_words_per_page(self):
        parent = self.load_parent()
        shown_words = []

        def inspect_words(page_index):
            def before_run(view):
                run_screen = view.run_screen

                def inspect_screen(*args, **kwargs):
                    assert kwargs["num_pages"] == 3
                    assert kwargs["words"] == MNEMONIC[page_index * 4:(page_index + 1) * 4]
                    assert kwargs.get("fingerprint_parent") is None
                    assert kwargs.get("fingerprint_child") is None
                    shown_words.extend(kwargs["words"])
                    return run_screen(*args, **kwargs)

                view.run_screen = inspect_screen

            return before_run

        self.run_sequence([
            FlowStep(seed_views.SeedWordsView, before_run=inspect_words(0),
                     button_data_selection=seed_views.SeedWordsView.NEXT),
            FlowStep(seed_views.SeedWordsView, before_run=inspect_words(1),
                     button_data_selection=seed_views.SeedWordsView.NEXT),
            FlowStep(seed_views.SeedWordsView, before_run=inspect_words(2),
                     button_data_selection=seed_views.SeedWordsView.DONE),
            FlowStep(seed_views.SeedWordsBackupTestPromptView),
        ], initial_destination_view_args={"seed": parent})

        assert shown_words == MNEMONIC

    def test_successful_child_backup_quiz_loads_child_and_preserves_parent(self):
        parent = self.load_parent()
        pending = self.controller.storage.get_pending_seed()
        stored_seeds = list(self.controller.storage.seeds)
        child_words = CHILDREN[0][3].split()

        def answer_child_word(view):
            assert view.seed is parent
            assert view.mnemonic_list == child_words
            assert len(self.controller.storage.seeds) == 2
            view.cur_index = next(index for index in range(12) if index not in view.confirmed_list)
            run_screen = view.run_screen

            def choose_correct_word(*args, **kwargs):
                run_screen(*args, **kwargs)
                return next(index for index, button in enumerate(kwargs["button_data"])
                            if button.button_label == child_words[view.cur_index])

            view.run_screen = choose_correct_word

        def before_success(view):
            # Completing the quiz has not loaded anything before acknowledging it.
            assert len(self.controller.storage.seeds) == 2
            assert view.seed is parent

        sequence = [FlowStep(seed_views.SeedWordsBackupTestPromptView,
                             button_data_selection=seed_views.SeedWordsBackupTestPromptView.VERIFY_CHILD)]
        sequence.extend(FlowStep(seed_views.SeedWordsBackupTestView, before_run=answer_child_word,
                                 screen_return_value=0) for _ in range(12))
        sequence.extend([
            FlowStep(seed_views.SeedWordsBackupTestSuccessView, before_run=before_success, screen_return_value=0),
            FlowStep(seed_views.SeedBIP85LoadChildView, is_redirect=True),
            FlowStep(seed_views.SeedOptionsView,
                     before_run=self.inspect_options_header("b4e3f5ed", "47c88c48"),
                     screen_return_value=StopFlowBasedTest()),
        ])
        self.run_sequence(sequence, initial_destination_view_args={
            "seed": parent, "bip85_data": {"num_words": 12, "child_index": 0},
        })

        assert len(self.controller.storage.seeds) == 3
        assert all(actual is expected for actual, expected in zip(self.controller.storage.seeds, stored_seeds))
        child = self.controller.storage.seeds[-1]
        assert child.mnemonic_list == child_words
        assert child.get_fingerprint() == "47c88c48"
        assert not child.has_passphrase
        assert child.is_bip85_child
        assert child.bip85_parent_fingerprint == "b4e3f5ed"
        assert self.controller.back_stack[-1].view_args["seed"] is child
        assert self.controller.storage.get_pending_seed() is pending
        assert parent.passphrase == "TREZOR"

    @pytest.mark.parametrize("cancel_from_words", [False, True])
    def test_cancelling_child_review_or_words_does_not_load_child(self, cancel_from_words):
        parent = self.load_parent()
        stored_seeds = list(self.controller.storage.seeds)
        pending = self.controller.storage.get_pending_seed()
        # In the app the selected parent's menu is already a history entry.
        self.controller.back_stack.append(Destination(seed_views.SeedOptionsView, view_args={"seed": parent}))
        sequence = [
            FlowStep(seed_views.SeedOptionsView,
                     button_data_selection=seed_views.SeedOptionsView.BIP85_CHILD_SEED),
            FlowStep(seed_views.SeedBIP85SelectNumWordsView,
                     button_data_selection=seed_views.SeedBIP85SelectNumWordsView.WORDS_12),
            FlowStep(seed_views.SeedBIP85SelectChildIndexView, screen_return_value="0"),
        ]
        if cancel_from_words:
            sequence.extend([
                FlowStep(seed_views.SeedBIP85ReviewView,
                         button_data_selection=seed_views.SeedBIP85ReviewView.VIEW_WORDS),
                FlowStep(seed_views.SeedWordsWarningView, screen_return_value=0),
                FlowStep(seed_views.SeedWordsView, screen_return_value=RET_CODE__BACK_BUTTON),
            ])
        sequence.extend([
            FlowStep(seed_views.SeedBIP85ReviewView, screen_return_value=RET_CODE__BACK_BUTTON),
            FlowStep(seed_views.SeedBIP85SelectChildIndexView, screen_return_value=RET_CODE__BACK_BUTTON),
            FlowStep(seed_views.SeedBIP85SelectNumWordsView, screen_return_value=RET_CODE__BACK_BUTTON),
            FlowStep(seed_views.SeedOptionsView),
        ])
        self.run_sequence(sequence, initial_destination_view_args={"seed": parent})

        assert len(self.controller.storage.seeds) == 2
        assert all(actual is expected for actual, expected in zip(self.controller.storage.seeds, stored_seeds))
        assert self.controller.storage.get_pending_seed() is pending
        assert self.controller.back_stack[-1].view_args["seed"] is parent

    @pytest.mark.parametrize("already_loaded", [False, True])
    def test_loading_child_deduplicates_full_seed_bytes_not_fingerprint_or_mnemonic(self, already_loaded, monkeypatch):
        parent = self.load_parent()
        pending = self.controller.storage.get_pending_seed()
        child_words = CHILDREN[0][3].split()
        extended_child = Seed(child_words, "existing extension")
        self.controller.storage.seeds.append(extended_child)
        existing_child = Seed(child_words)
        if already_loaded:
            self.controller.storage.seeds.append(existing_child)
        originals = list(self.controller.storage.seeds)
        wallet_state_fields = (
            "psbt", "psbt_parser", "psbt_seed", "resume_main_flow",
            "multisig_wallet_descriptor", "unverified_address", "address_explorer_data", "sign_message_data",
        )
        for field in wallet_state_fields:
            setattr(self.controller, field, object())
        # Force an XFP collision across distinct wallets. Only full seed equality
        # may select the existing canonical child or avoid adding the new child.
        monkeypatch.setattr(Seed, "get_fingerprint", lambda self, *args, **kwargs: "01020304")

        self.run_sequence([
            FlowStep(seed_views.SeedWordsBackupTestPromptView,
                     button_data_selection=seed_views.SeedWordsBackupTestPromptView.LOAD_CHILD),
            FlowStep(seed_views.SeedBIP85LoadChildView, is_redirect=True),
            FlowStep(seed_views.SeedOptionsView),
        ], initial_destination_view_args={"seed": parent, "bip85_data": {"num_words": 12, "child_index": 0}})

        selected = self.controller.back_stack[-1].view_args["seed"]
        assert len(self.controller.storage.seeds) == 4
        assert all(actual is expected for actual, expected in zip(self.controller.storage.seeds, originals))
        assert selected is self.controller.storage.seeds[-1]
        assert selected is not parent and selected is not extended_child
        assert selected.seed_bytes == existing_child.seed_bytes
        assert selected.is_bip85_child
        assert selected.bip85_parent_fingerprint == "01020304"
        assert not parent.is_bip85_child
        assert not extended_child.is_bip85_child
        if already_loaded:
            assert selected is existing_child
        assert self.controller.storage.get_pending_seed() is pending
        assert len(self.controller.back_stack) == 1
        assert all(getattr(self.controller, field) is None for field in wallet_state_fields)

    @pytest.mark.parametrize("remove", [False, True])
    def test_cancelling_child_passphrase_change_preserves_child_marker(self, remove):
        parent = self.load_parent()
        child = Seed(CHILDREN[0][3].split(), "child extension", bip85_parent_fingerprint="b4e3f5ed")
        self.controller.storage.seeds.append(child)

        def inspect_candidate(view):
            assert view.seed is child
            assert view.candidate.is_bip85_child
            assert view.candidate.bip85_parent_fingerprint == "b4e3f5ed"
            assert self.controller.storage.seeds[-1] is child

        sequence = [
            FlowStep(seed_views.SeedOptionsView,
                     button_data_selection=seed_views.SeedOptionsView.PASSPHRASE),
            FlowStep(seed_views.SeedPassphraseMenuView, button_data_selection=(
                seed_views.SeedPassphraseMenuView.REMOVE if remove else seed_views.SeedPassphraseMenuView.EDIT)),
        ]
        if not remove:
            sequence.append(FlowStep(seed_views.SeedEditPassphraseView,
                                     screen_return_value={"passphrase": "unfinished child extension"}))
        sequence.extend([
            FlowStep(seed_views.SeedConfirmPassphraseView, before_run=inspect_candidate,
                     button_data_selection=seed_views.SeedConfirmPassphraseView.CANCEL),
            FlowStep(seed_views.SeedOptionsView),
        ])
        self.run_sequence(sequence, initial_destination_view_args={"seed": child})

        assert self.controller.storage.seeds[-1] is child
        assert child.is_bip85_child
        assert child.bip85_parent_fingerprint == "b4e3f5ed"
        assert child.passphrase == "child extension"
        assert self.controller.storage.seeds[1] is parent
        assert not parent.is_bip85_child

    def test_child_passphrase_add_edit_remove_never_changes_parent(self, monkeypatch):
        parent = self.load_parent()
        other = self.controller.storage.seeds[0]
        pending = self.controller.storage.get_pending_seed()
        parent_bytes = parent.seed_bytes
        parent_words = parent.mnemonic_list
        parent_fingerprint = parent.get_fingerprint()
        child_words = CHILDREN[0][3].split()

        def reject_parent_mutation(*args, **kwargs):
            pytest.fail("Changing a BIP85 child's passphrase must never mutate its parent")

        monkeypatch.setattr(parent, "set_passphrase", reject_parent_mutation)

        def inspect_child_options(passphrase):
            expected = Seed(child_words, passphrase)

            def before_run(view):
                assert len(self.controller.storage.seeds) == 3
                assert self.controller.storage.seeds[0] is other
                assert self.controller.storage.seeds[1] is parent
                assert view.seed is self.controller.storage.seeds[2]
                assert view.seed.seed_bytes == expected.seed_bytes
                assert view.seed.mnemonic_list == child_words
                assert view.seed.passphrase == passphrase
                assert view.seed.is_bip85_child
                assert view.seed.bip85_parent_fingerprint == "b4e3f5ed"
                assert not parent.is_bip85_child
                assert parent.seed_bytes is parent_bytes
                assert parent.mnemonic_list is parent_words
                assert parent.passphrase == "TREZOR"
                assert parent.get_fingerprint() == parent_fingerprint
                assert self.controller.storage.get_pending_seed() is pending
                run_screen = view.run_screen

                def inspect_screen(*args, **kwargs):
                    assert kwargs["fingerprint"] == expected.get_fingerprint()
                    assert kwargs["fingerprint_without"] == ("47c88c48" if passphrase else None)
                    assert kwargs["fingerprint_parent"] == "b4e3f5ed"
                    options = kwargs["button_data"]
                    child_index = options.index(seed_views.SeedOptionsView.BIP85_CHILD_SEED)
                    expected_colors = {child_index: GUIConstants.BIP85_COLOR}
                    expected_selected_colors = {child_index: GUIConstants.BIP85_COLOR_SELECTED}
                    if passphrase:
                        passphrase_index = options.index(seed_views.SeedOptionsView.PASSPHRASE)
                        expected_colors[passphrase_index] = GUIConstants.PASSPHRASE_COLOR
                        expected_selected_colors[passphrase_index] = GUIConstants.PASSPHRASE_COLOR_SELECTED
                    assert set(kwargs["checked_button_indices"]) == set(expected_colors)
                    assert kwargs["checked_button_colors"] == expected_colors
                    assert kwargs["selected_checked_button_colors"] == expected_selected_colors
                    return run_screen(*args, **kwargs)

                view.run_screen = inspect_screen

            return before_run

        self.run_sequence([
            FlowStep(seed_views.SeedWordsBackupTestPromptView,
                     button_data_selection=seed_views.SeedWordsBackupTestPromptView.LOAD_CHILD),
            FlowStep(seed_views.SeedBIP85LoadChildView, is_redirect=True),
            FlowStep(seed_views.SeedOptionsView, before_run=inspect_child_options(""),
                     button_data_selection=seed_views.SeedOptionsView.PASSPHRASE),
            FlowStep(seed_views.SeedPassphraseMenuView, is_redirect=True),
            FlowStep(seed_views.SeedEditPassphraseView, screen_return_value={"passphrase": "child only"}),
            FlowStep(seed_views.SeedConfirmPassphraseView,
                     button_data_selection=seed_views.SeedConfirmPassphraseView.APPLY),
            FlowStep(seed_views.SeedPassphraseSaveView, button_data_selection=seed_views.SeedPassphraseSaveView.REPLACE),
            FlowStep(seed_views.SeedOptionsView, before_run=inspect_child_options("child only"),
                     button_data_selection=seed_views.SeedOptionsView.PASSPHRASE),
            FlowStep(seed_views.SeedPassphraseMenuView, button_data_selection=seed_views.SeedPassphraseMenuView.EDIT),
            FlowStep(seed_views.SeedEditPassphraseView, screen_return_value={"passphrase": "child edited"}),
            FlowStep(seed_views.SeedConfirmPassphraseView,
                     button_data_selection=seed_views.SeedConfirmPassphraseView.APPLY),
            FlowStep(seed_views.SeedPassphraseSaveView, button_data_selection=seed_views.SeedPassphraseSaveView.REPLACE),
            FlowStep(seed_views.SeedOptionsView, before_run=inspect_child_options("child edited"),
                     button_data_selection=seed_views.SeedOptionsView.PASSPHRASE),
            FlowStep(seed_views.SeedPassphraseMenuView, button_data_selection=seed_views.SeedPassphraseMenuView.REMOVE),
            FlowStep(seed_views.SeedConfirmPassphraseView,
                     button_data_selection=seed_views.SeedConfirmPassphraseView.REMOVE),
            FlowStep(seed_views.SeedOptionsView, before_run=inspect_child_options(""),
                     screen_return_value=StopFlowBasedTest()),
        ], initial_destination_view_args={"seed": parent, "bip85_data": {"num_words": 12, "child_index": 0}})


    @pytest.mark.parametrize("already_loaded", [False, True])
    def test_loading_child_passphrase_separately_preserves_bare_child_parent_and_provenance(self, already_loaded):
        parent = self.load_parent()
        parent_bytes = parent.seed_bytes
        parent_words = parent.mnemonic_list
        pending = self.controller.storage.get_pending_seed()
        child_words = CHILDREN[0][3].split()
        imported_variant = Seed(child_words, "separate child wallet")
        if already_loaded:
            self.controller.storage.seeds.append(imported_variant)
        bare_children = []

        def before_child_menu(view):
            bare_children.append(view.seed)
            assert view.seed.mnemonic_list == child_words
            assert not view.seed.has_passphrase
            self.inspect_options_header("b4e3f5ed", "47c88c48")(view)

        def before_save(view):
            assert view.seed is bare_children[0]
            assert view.candidate.is_bip85_child
            assert view.candidate.bip85_parent_fingerprint == "b4e3f5ed"
            assert parent.seed_bytes is parent_bytes
            assert parent.mnemonic_list is parent_words

        def after_separate_load(view):
            bare_child = bare_children[0]
            assert view.seed is not bare_child and view.seed is not parent
            assert view.seed.seed_bytes == imported_variant.seed_bytes
            assert view.seed.is_bip85_child
            assert view.seed.bip85_parent_fingerprint == "b4e3f5ed"
            if already_loaded:
                assert view.seed is imported_variant
            assert len(self.controller.storage.seeds) == 4
            assert any(seed is bare_child for seed in self.controller.storage.seeds)
            assert not bare_child.has_passphrase
            assert bare_child.bip85_parent_fingerprint == "b4e3f5ed"
            assert self.controller.storage.seeds[1] is parent
            assert parent.seed_bytes is parent_bytes
            assert parent.mnemonic_list is parent_words
            assert parent.passphrase == "TREZOR"
            assert parent.get_fingerprint() == "b4e3f5ed"
            assert self.controller.storage.get_pending_seed() is pending
            assert len(self.controller.back_stack) == 1
            self.inspect_options_header("b4e3f5ed", imported_variant.get_fingerprint(), "47c88c48")(view)

        self.run_sequence([
            FlowStep(seed_views.SeedWordsBackupTestPromptView,
                     button_data_selection=seed_views.SeedWordsBackupTestPromptView.LOAD_CHILD),
            FlowStep(seed_views.SeedBIP85LoadChildView, is_redirect=True),
            FlowStep(seed_views.SeedOptionsView, before_run=before_child_menu,
                     button_data_selection=seed_views.SeedOptionsView.PASSPHRASE),
            FlowStep(seed_views.SeedPassphraseMenuView, is_redirect=True),
            FlowStep(seed_views.SeedEditPassphraseView,
                     screen_return_value={"passphrase": imported_variant.passphrase}),
            FlowStep(seed_views.SeedConfirmPassphraseView,
                     button_data_selection=seed_views.SeedConfirmPassphraseView.APPLY),
            FlowStep(seed_views.SeedPassphraseSaveView, before_run=before_save,
                     button_data_selection=seed_views.SeedPassphraseSaveView.LOAD_SEPARATELY),
            FlowStep(seed_views.SeedOptionsView, before_run=after_separate_load, screen_return_value=StopFlowBasedTest()),
        ], initial_destination_view_args={"seed": parent, "bip85_data": {"num_words": 12, "child_index": 0}})

    @pytest.mark.parametrize("selected_index", range(5))
    def test_in_memory_rows_show_relationships_and_select_exact_loaded_seed(self, selected_index):
        plain = Seed(MNEMONIC)
        parent = Seed(MNEMONIC, "TREZOR")
        child_words = CHILDREN[0][3].split()
        child = Seed(child_words, bip85_parent_fingerprint=parent.get_fingerprint())
        extended_child = Seed(child_words, "child extension", bip85_parent_fingerprint=parent.get_fingerprint())
        # Older session metadata may identify a child without knowing its parent.
        unknown_parent_child = Seed(CHILDREN[2][3].split(), is_bip85_child=True)
        seeds = [plain, parent, child, extended_child, unknown_parent_child]
        self.controller.storage.seeds = seeds
        expected_chains = [
            (plain.get_fingerprint(),),
            (plain.get_fingerprint(), parent.get_fingerprint()),
            (parent.get_fingerprint(), child.get_fingerprint()),
            (parent.get_fingerprint(), child.get_fingerprint(), extended_child.get_fingerprint()),
            (unknown_parent_child.get_fingerprint(),),
        ]
        expected_edge_colors = [
            (),
            (GUIConstants.PASSPHRASE_COLOR,),
            (GUIConstants.BIP85_COLOR,),
            (GUIConstants.BIP85_COLOR, GUIConstants.PASSPHRASE_COLOR),
            (),
        ]
        expected_selected_edge_colors = [
            (),
            (GUIConstants.PASSPHRASE_COLOR_SELECTED,),
            (GUIConstants.BIP85_COLOR_SELECTED,),
            (GUIConstants.BIP85_COLOR_SELECTED, GUIConstants.PASSPHRASE_COLOR_SELECTED),
            (),
        ]

        def inspect_rows(view):
            run_screen = view.run_screen

            def inspect_screen(*args, **kwargs):
                rows = kwargs["button_data"]
                assert len(rows) == len(seeds) + 1
                for row, seed, expected_chain, edge_colors, selected_colors in zip(
                        rows, seeds, expected_chains, expected_edge_colors, expected_selected_edge_colors):
                    assert row.lifehash_fingerprints == expected_chain
                    assert row.button_label == seed.get_fingerprint() == expected_chain[-1]
                    assert row.lifehash_arrow_colors == edge_colors
                    assert row.selected_lifehash_arrow_colors == selected_colors
                return run_screen(*args, **kwargs)

            view.run_screen = inspect_screen

        self.run_sequence([
            FlowStep(seed_views.SeedsMenuView, before_run=inspect_rows, screen_return_value=selected_index),
            FlowStep(seed_views.SeedOptionsView,
                     before_run=self.inspect_options_header(
                         seeds[selected_index].bip85_parent_fingerprint, seeds[selected_index].get_fingerprint(),
                         seeds[selected_index].get_fingerprint_without_passphrase() if seeds[selected_index].has_passphrase else None),
                     screen_return_value=StopFlowBasedTest()),
        ])

        assert self.controller.back_stack[-1].view_args["seed"] is seeds[selected_index]

    def test_child_parent_snapshot_survives_parent_edit_and_discard_without_retaining_parent(self):
        import gc
        import weakref

        parent = self.load_parent()
        self.run_sequence([
            FlowStep(seed_views.SeedWordsBackupTestPromptView,
                     button_data_selection=seed_views.SeedWordsBackupTestPromptView.LOAD_CHILD),
            FlowStep(seed_views.SeedBIP85LoadChildView, is_redirect=True),
            FlowStep(seed_views.SeedOptionsView),
        ], initial_destination_view_args={"seed": parent, "bip85_data": {"num_words": 12, "child_index": 0}})
        child = self.controller.storage.seeds[-1]
        parent_reference = weakref.ref(parent)
        updated_parent = Seed(MNEMONIC, "updated parent")
        assert self.controller.replace_seed(parent, updated_parent) is updated_parent
        assert child.bip85_parent_fingerprint == "b4e3f5ed"
        assert child.bip85_parent_fingerprint != updated_parent.get_fingerprint()
        del parent
        gc.collect()
        assert parent_reference() is None

        self.controller.discard_seed(updated_parent)
        assert child.bip85_parent_fingerprint == "b4e3f5ed"

        def inspect_child_row(view):
            run_screen = view.run_screen

            def inspect_screen(*args, **kwargs):
                row = kwargs["button_data"][1]
                assert row.lifehash_fingerprints == ("b4e3f5ed", "47c88c48")
                assert row.button_label == "47c88c48"
                return run_screen(*args, **kwargs)

            view.run_screen = inspect_screen

        self.run_sequence([
            FlowStep(seed_views.SeedsMenuView, before_run=inspect_child_row, screen_return_value=1),
            FlowStep(seed_views.SeedOptionsView,
                     before_run=self.inspect_options_header("b4e3f5ed", "47c88c48"),
                     screen_return_value=StopFlowBasedTest()),
        ])
        assert self.controller.back_stack[-1].view_args["seed"] is child


    def test_in_memory_relationship_keeps_each_role_when_fingerprints_collide(self, monkeypatch):
        child = Seed(CHILDREN[0][3].split(), "child extension", bip85_parent_fingerprint="deadbeef")
        self.controller.storage.seeds = [child]
        monkeypatch.setattr(Seed, "get_fingerprint", lambda self, *args, **kwargs: "deadbeef")

        def inspect_row(view):
            run_screen = view.run_screen

            def inspect_screen(*args, **kwargs):
                row = kwargs["button_data"][0]
                assert row.lifehash_fingerprints == ("deadbeef", "deadbeef", "deadbeef")
                assert row.button_label == "deadbeef"
                assert row.lifehash_arrow_colors == (GUIConstants.BIP85_COLOR, GUIConstants.PASSPHRASE_COLOR)
                assert row.selected_lifehash_arrow_colors == (
                    GUIConstants.BIP85_COLOR_SELECTED, GUIConstants.PASSPHRASE_COLOR_SELECTED)
                return run_screen(*args, **kwargs)

            view.run_screen = inspect_screen

        self.run_sequence([
            FlowStep(seed_views.SeedsMenuView, before_run=inspect_row, screen_return_value=0),
            FlowStep(seed_views.SeedOptionsView,
                     before_run=self.inspect_options_header("deadbeef", "deadbeef", "deadbeef"),
                     screen_return_value=StopFlowBasedTest()),
        ])
        assert self.controller.back_stack[-1].view_args["seed"] is child


    @pytest.mark.parametrize("bip85_setting", [SettingsConstants.OPTION__ENABLED, SettingsConstants.OPTION__DISABLED])
    @pytest.mark.parametrize("passphrase_setting", [
        SettingsConstants.OPTION__ENABLED, SettingsConstants.OPTION__REQUIRED, SettingsConstants.OPTION__DISABLED,
    ])
    def test_menu_check_colors_follow_visible_roles_even_when_fingerprints_collide(
            self, bip85_setting, passphrase_setting, monkeypatch):
        child = Seed(CHILDREN[0][3].split(), "child extension", bip85_parent_fingerprint="deadbeef")
        self.controller.storage.seeds = [child]
        self.settings.set_value(SettingsConstants.SETTING__BIP85_CHILD_SEEDS, bip85_setting)
        self.settings.set_value(SettingsConstants.SETTING__PASSPHRASE, passphrase_setting)
        monkeypatch.setattr(Seed, "get_fingerprint", lambda self, *args, **kwargs: "deadbeef")

        def inspect_checks(view):
            run_screen = view.run_screen

            def inspect_screen(*args, **kwargs):
                options = kwargs["button_data"]
                expected_colors = {}
                expected_selected_colors = {}
                visible_child = bip85_setting == SettingsConstants.OPTION__ENABLED
                visible_passphrase = passphrase_setting != SettingsConstants.OPTION__DISABLED
                assert (seed_views.SeedOptionsView.BIP85_CHILD_SEED in options) == visible_child
                assert (seed_views.SeedOptionsView.PASSPHRASE in options) == visible_passphrase
                if visible_child:
                    index = options.index(seed_views.SeedOptionsView.BIP85_CHILD_SEED)
                    expected_colors[index] = GUIConstants.BIP85_COLOR
                    expected_selected_colors[index] = GUIConstants.BIP85_COLOR_SELECTED
                if visible_passphrase:
                    index = options.index(seed_views.SeedOptionsView.PASSPHRASE)
                    expected_colors[index] = GUIConstants.PASSPHRASE_COLOR
                    expected_selected_colors[index] = GUIConstants.PASSPHRASE_COLOR_SELECTED
                assert set(kwargs["checked_button_indices"]) == set(expected_colors)
                assert kwargs["checked_button_colors"] == expected_colors
                assert kwargs["selected_checked_button_colors"] == expected_selected_colors
                return run_screen(*args, **kwargs)

            view.run_screen = inspect_screen

        self.run_sequence([
            FlowStep(seed_views.SeedOptionsView, before_run=inspect_checks, screen_return_value=StopFlowBasedTest()),
        ], initial_destination_view_args={"seed": child})


@pytest.mark.parametrize("operation,original_child,replacement_child,canonical_child,expected_child", [
    ("new", True, False, False, True),
    ("new", False, True, False, True),
    ("new", False, False, False, False),
    ("noop", True, False, False, True),
    ("noop", False, True, False, True),
    ("dedup", True, False, False, True),
    ("dedup", False, True, False, True),
    ("dedup", False, False, True, True),
    ("dedup", False, False, False, False),
])
def test_replacement_preserves_known_child_metadata(
        operation, original_child, replacement_child, canonical_child, expected_child):
    storage = SeedStorage()
    words = CHILDREN[0][3].split()
    original = Seed(words, "original", is_bip85_child=original_child)
    replacement = Seed(words, "original" if operation == "noop" else "changed",
                       is_bip85_child=replacement_child)
    storage.seeds = [original]
    canonical = Seed(words, "changed", is_bip85_child=canonical_child)
    if operation == "dedup":
        storage.seeds.append(canonical)

    selected = storage.replace_seed(original, replacement)

    assert selected is (original if operation == "noop" else canonical if operation == "dedup" else replacement)
    assert selected.is_bip85_child is expected_child
    assert len(storage.seeds) == 1
    assert storage.seeds[0] is selected
    assert selected.seed_bytes == replacement.seed_bytes


def test_reimporting_known_child_does_not_clear_child_metadata():
    storage = SeedStorage()
    words = CHILDREN[0][3].split()
    known_child = Seed(words, is_bip85_child=True)
    manually_entered = Seed(words)
    storage.seeds = [known_child]

    assert known_child == manually_entered
    assert storage.add_seed(manually_entered) is known_child
    assert known_child.is_bip85_child
    assert not manually_entered.is_bip85_child
    assert len(storage.seeds) == 1


@pytest.mark.parametrize("operation,original_parent,candidate_parent,canonical_parent,expected_parent", [
    ("add", None, "b4e3f5ed", None, "b4e3f5ed"),
    ("add", "01020304", "b4e3f5ed", None, "01020304"),
    ("noop", None, "b4e3f5ed", None, "b4e3f5ed"),
    ("noop", "01020304", "b4e3f5ed", None, "01020304"),
    ("new", "b4e3f5ed", None, None, "b4e3f5ed"),
    ("new", "01020304", "b4e3f5ed", None, "01020304"),
    ("dedup", "b4e3f5ed", None, None, "b4e3f5ed"),
    ("dedup", None, "b4e3f5ed", None, "b4e3f5ed"),
    ("dedup", "b4e3f5ed", "05060708", "01020304", "01020304"),
])
def test_canonical_child_provenance_is_preserved_or_filled_when_missing(
        operation, original_parent, candidate_parent, canonical_parent, expected_parent):
    storage = SeedStorage()
    words = CHILDREN[0][3].split()
    original = Seed(words, "original", bip85_parent_fingerprint=original_parent)
    candidate = Seed(words, "original" if operation in ("add", "noop") else "changed",
                     bip85_parent_fingerprint=candidate_parent)
    storage.seeds = [original]
    canonical = Seed(words, "changed", bip85_parent_fingerprint=canonical_parent)
    if operation == "dedup":
        storage.seeds.append(canonical)

    selected = storage.add_seed(candidate) if operation == "add" else storage.replace_seed(original, candidate)

    expected_seed = original if operation in ("add", "noop") else canonical if operation == "dedup" else candidate
    assert selected is expected_seed
    assert selected.bip85_parent_fingerprint == expected_parent
    assert selected.is_bip85_child
    assert len(storage.seeds) == 1
