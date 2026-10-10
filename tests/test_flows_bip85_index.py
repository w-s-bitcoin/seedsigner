import pytest

# Install hardware mocks before importing application Views.
from base import FlowStep, FlowTest

from seedsigner.controller import StopFlowBasedTest
from seedsigner.gui.screens.screen import RET_CODE__BACK_BUTTON
from seedsigner.models.seed import Seed
from seedsigner.models.settings import SettingsConstants
from seedsigner.views import seed_views


MNEMONIC = ["abandon"] * 11 + ["about"]
LAST_INDEX = 2**31 - 1
# Independently derived BIP-85 English vectors for MNEMONIC + TREZOR, using
# m/83696968'/39'/0'/{words}'/{index}' and HMAC-SHA512("bip-entropy-from-k", k).
CHILD_WORDS = {
    12: "climb typical because giraffe beach wool fit ship common chapter hotel arm",
    24: "guess violin output company next ribbon submit simple balance toss buffalo number fire horn mystery assault require opinion social pony obey system winter pupil",
}
SIBLING_WORDS = {
    12: "always have female giant cannon resource mercy blue real when modify trouble",
    24: "rate flash cycle boat unfair fortune humor tunnel song hurt club round famous resource rent inspire lounge hour used spare front mix rough scorpion",
}
SIBLING_FINGERPRINTS = {12: "a18dd64b", 24: "b0c90adb"}
# Direct hardened-path/HMAC derivation from CHILD_WORDS[12] + child extension.
GRANDCHILD_WORDS = "grit embody alone guilt type mandate fluid pledge glance beach success final"


class TestBIP85ChildIndexFlows(FlowTest):
    def load_wallets(self, num_words=12):
        self.num_words = num_words
        self.parent = Seed(MNEMONIC, "TREZOR")
        self.child = Seed(
            CHILD_WORDS[num_words].split(), "child extension",
            bip85_parent_fingerprint="b4e3f5ed", bip85_child_index=0,
            bip85_num_words=num_words,
        )
        self.pending = Seed(MNEMONIC, "unrelated pending wallet")
        self.controller.storage.seeds = [self.parent, self.child]
        self.controller.storage.set_pending_seed(self.pending)
        self.originals = list(self.controller.storage.seeds)
        self.parent_bytes = self.parent.seed_bytes
        self.child_bytes = self.child.seed_bytes
        self.settings.set_value(SettingsConstants.SETTING__BIP85_CHILD_SEEDS, SettingsConstants.OPTION__ENABLED)
        self.settings.set_value(SettingsConstants.SETTING__PASSPHRASE, SettingsConstants.OPTION__ENABLED)
        self.settings.set_value(SettingsConstants.SETTING__DIRE_WARNINGS, SettingsConstants.OPTION__ENABLED)

    def assert_source_unchanged(self):
        assert len(self.controller.storage.seeds) == len(self.originals)
        assert all(actual is original for actual, original in zip(self.controller.storage.seeds, self.originals))
        assert self.parent.seed_bytes is self.parent_bytes
        assert self.parent.passphrase == "TREZOR"
        assert self.child.seed_bytes is self.child_bytes
        assert self.child.passphrase == "child extension"
        assert self.child.bip85_child_index == 0
        assert self.controller.storage.get_pending_seed() is self.pending

    def inspect_index(self, view):
        self.assert_source_unchanged()
        assert view.seed is self.parent
        assert view.change_from_seed is self.child
        assert view.num_words == self.num_words
        run_screen = view.run_screen

        def inspect_screen(*args, **kwargs):
            assert kwargs["initial_index"] == 0
            return run_screen(*args, **kwargs)

        view.run_screen = inspect_screen

    def inspect_review(self, view):
        self.assert_source_unchanged()
        assert view.seed is self.parent
        assert view.change_from_seed is self.child
        assert view.child_index == LAST_INDEX
        run_screen = view.run_screen

        def inspect_screen(*args, **kwargs):
            assert kwargs["fingerprint_parent"] == "b4e3f5ed"
            assert kwargs["fingerprint_child"] == SIBLING_FINGERPRINTS[self.num_words]
            assert kwargs["num_words"] == self.num_words
            return run_screen(*args, **kwargs)

        view.run_screen = inspect_screen

    def inspect_backup_context(self, view):
        self.assert_source_unchanged()
        assert view.seed is self.parent
        assert view.bip85_data == {
            "num_words": self.num_words, "child_index": LAST_INDEX,
            "change_from_seed": self.child,
        }

    def inspect_save(self, view):
        self.assert_source_unchanged()
        assert view.seed is self.child
        assert view.parent is self.parent
        assert view.candidate.mnemonic_list == SIBLING_WORDS[self.num_words].split()
        assert not view.candidate.has_passphrase
        assert view.candidate.is_bip85_child
        assert view.candidate.bip85_parent_fingerprint == "b4e3f5ed"
        assert view.candidate.bip85_child_index == LAST_INDEX
        assert view.candidate.bip85_num_words == self.num_words
        run_screen = view.run_screen

        def inspect_screen(*args, **kwargs):
            assert kwargs["fingerprint_parent"] == self.parent.get_fingerprint()
            assert kwargs["fingerprint_new"] == view.candidate.get_fingerprint()
            # Replacement affects the current passphrased child, not its bare
            # wallet, the deriving parent, or the new sibling in the diagram.
            assert kwargs["fingerprint_current"] == self.child.get_fingerprint()
            return run_screen(*args, **kwargs)

        view.run_screen = inspect_screen

    def to_review(self):
        return [
            FlowStep(seed_views.SeedOptionsView,
                     button_data_selection=seed_views.SeedOptionsView.BIP85_CHILD_SEED),
            FlowStep(seed_views.SeedBIP85ChildMenuView,
                     button_data_selection=seed_views.SeedBIP85ChildMenuView.CHANGE_INDEX),
            FlowStep(seed_views.SeedBIP85SelectChildIndexView,
                     before_run=self.inspect_index, screen_return_value=str(LAST_INDEX)),
            FlowStep(seed_views.SeedBIP85ReviewView, before_run=self.inspect_review,
                     button_data_selection=seed_views.SeedBIP85ReviewView.VIEW_WORDS),
            FlowStep(seed_views.SeedWordsWarningView, before_run=self.inspect_backup_context,
                     screen_return_value=0),
        ]

    def word_pages(self):
        steps = []
        for page in range(self.num_words // 3):
            def inspect_words(view, page=page):
                self.inspect_backup_context(view)
                run_screen = view.run_screen

                def inspect_screen(*args, **kwargs):
                    expected_words = SIBLING_WORDS[self.num_words].split()[page * 3:(page + 1) * 3]
                    assert kwargs["words"] == expected_words
                    assert kwargs["fingerprint_parent"] == "b4e3f5ed"
                    assert kwargs["fingerprint_child"] == SIBLING_FINGERPRINTS[self.num_words]
                    return run_screen(*args, **kwargs)

                view.run_screen = inspect_screen

            steps.append(FlowStep(
                seed_views.SeedWordsView, before_run=inspect_words,
                button_data_selection=(seed_views.SeedWordsView.DONE if page == self.num_words // 3 - 1
                                       else seed_views.SeedWordsView.NEXT),
            ))
        return steps

    @pytest.mark.parametrize("num_words", [12, 24])
    @pytest.mark.parametrize("action", ["replace", "separate", "cancel"])
    def test_submenu_changes_sibling_only_after_explicit_save(self, num_words, action):
        self.load_wallets(num_words)
        buttons = {
            "replace": seed_views.SeedBIP85SaveChildView.REPLACE,
            "separate": seed_views.SeedBIP85SaveChildView.LOAD_SEPARATELY,
            "cancel": seed_views.SeedBIP85SaveChildView.CANCEL,
        }
        self.run_sequence(self.to_review() + self.word_pages() + [
            FlowStep(seed_views.SeedWordsBackupTestPromptView, before_run=self.inspect_backup_context,
                     button_data_selection=seed_views.SeedWordsBackupTestPromptView.LOAD_CHILD),
            FlowStep(seed_views.SeedBIP85LoadChildView, is_redirect=True),
            FlowStep(seed_views.SeedBIP85SaveChildView, before_run=self.inspect_save,
                     button_data_selection=buttons[action]),
            FlowStep(seed_views.SeedOptionsView),
        ], initial_destination_view_args={"seed": self.child})

        selected = self.controller.back_stack[-1].view_args["seed"]
        assert self.controller.storage.seeds[0] is self.parent
        assert self.parent.seed_bytes is self.parent_bytes
        assert self.child.seed_bytes is self.child_bytes
        assert self.child.passphrase == "child extension"
        assert self.controller.storage.get_pending_seed() is self.pending
        if action == "cancel":
            self.assert_source_unchanged()
            assert selected is self.child
        else:
            assert selected is not self.child
            assert selected.mnemonic_list == SIBLING_WORDS[num_words].split()
            assert selected.get_fingerprint() == SIBLING_FINGERPRINTS[num_words]
            assert not selected.has_passphrase
            assert selected.bip85_child_index == LAST_INDEX
            assert selected.bip85_num_words == num_words
            assert selected.bip85_parent_fingerprint == "b4e3f5ed"
            assert len(self.controller.storage.seeds) == (2 if action == "replace" else 3)
            assert any(seed is self.child for seed in self.controller.storage.seeds) == (action == "separate")
        assert len(self.controller.back_stack) == 1

    @pytest.mark.parametrize("invalid_index", ["-1", str(2**31), "", "not an index"])
    def test_invalid_index_retry_preserves_parent_original_child_and_word_count(self, invalid_index):
        self.load_wallets(24)

        def inspect_error(view):
            self.assert_source_unchanged()
            assert view.seed is self.parent
            assert view.change_from_seed is self.child
            assert view.num_words == 24

        self.run_sequence([
            FlowStep(seed_views.SeedBIP85ChildMenuView,
                     button_data_selection=seed_views.SeedBIP85ChildMenuView.CHANGE_INDEX),
            FlowStep(seed_views.SeedBIP85SelectChildIndexView, before_run=self.inspect_index,
                     screen_return_value=invalid_index),
            FlowStep(seed_views.SeedBIP85InvalidChildIndexView, before_run=inspect_error,
                     screen_return_value=0),
            FlowStep(seed_views.SeedBIP85SelectChildIndexView, before_run=self.inspect_index,
                     screen_return_value=str(LAST_INDEX)),
            FlowStep(seed_views.SeedBIP85ReviewView, before_run=self.inspect_review,
                     screen_return_value=StopFlowBasedTest()),
        ], initial_destination_view_args={"seed": self.child})
        self.assert_source_unchanged()

    def test_unchanged_index_keeps_existing_child_and_its_passphrase(self):
        self.load_wallets()
        self.run_sequence([
            FlowStep(seed_views.SeedOptionsView,
                     button_data_selection=seed_views.SeedOptionsView.BIP85_CHILD_SEED),
            FlowStep(seed_views.SeedBIP85ChildMenuView,
                     button_data_selection=seed_views.SeedBIP85ChildMenuView.CHANGE_INDEX),
            FlowStep(seed_views.SeedBIP85SelectChildIndexView, before_run=self.inspect_index,
                     screen_return_value="0"),
            FlowStep(seed_views.SeedOptionsView),
        ], initial_destination_view_args={"seed": self.child})
        self.assert_source_unchanged()
        assert len(self.controller.back_stack) == 1
        assert self.controller.back_stack[-1].view_args["seed"] is self.child

    @pytest.mark.parametrize("unavailable", ["missing_origin", "missing_parent", "changed_parent"])
    def test_change_index_notice_keeps_child_and_pending_unchanged(self, unavailable):
        self.load_wallets()
        if unavailable == "missing_origin":
            self.child.bip85_child_index = None
        elif unavailable == "missing_parent":
            self.controller.storage.seeds.remove(self.parent)
        else:
            self.controller.storage.seeds[0] = Seed(MNEMONIC, "different parent wallet")
        before = list(self.controller.storage.seeds)

        def inspect_notice(view):
            assert view.seed is self.child
            assert view.missing_origin == (unavailable == "missing_origin")

        self.run_sequence([
            FlowStep(seed_views.SeedOptionsView,
                     button_data_selection=seed_views.SeedOptionsView.BIP85_CHILD_SEED),
            FlowStep(seed_views.SeedBIP85ChildMenuView,
                     button_data_selection=seed_views.SeedBIP85ChildMenuView.CHANGE_INDEX),
            FlowStep(seed_views.SeedBIP85ParentUnavailableView, before_run=inspect_notice,
                     screen_return_value=0),
            FlowStep(seed_views.SeedOptionsView),
        ], initial_destination_view_args={"seed": self.child})
        assert len(self.controller.storage.seeds) == len(before)
        assert all(actual is original for actual, original in zip(self.controller.storage.seeds, before))
        assert self.controller.back_stack[-1].view_args["seed"] is self.child
        assert len(self.controller.back_stack) == 1
        assert self.child.seed_bytes is self.child_bytes
        assert self.controller.storage.get_pending_seed() is self.pending

    def make_sibling(self):
        return Seed(
            SIBLING_WORDS[self.num_words].split(),
            bip85_parent_fingerprint="b4e3f5ed", bip85_child_index=LAST_INDEX,
            bip85_num_words=self.num_words,
        )

    @pytest.mark.parametrize("action", ["replace", "separate"])
    @pytest.mark.parametrize("change", ["remove_parent", "change_parent", "remove_child"])
    def test_save_rechecks_loaded_parent_and_child_after_screen_input(self, monkeypatch, action, change):
        self.load_wallets()
        candidate = self.make_sibling()
        view = seed_views.SeedBIP85SaveChildView(self.child, self.parent, candidate)
        assert not view.has_redirect

        def change_wallets(*args, **kwargs):
            self.assert_source_unchanged()
            if change == "remove_parent":
                self.controller.storage.seeds.remove(self.parent)
            elif change == "change_parent":
                self.controller.storage.seeds[0] = Seed(MNEMONIC, "different parent wallet")
            else:
                self.controller.storage.seeds.remove(self.child)
            return 0 if action == "replace" else 1

        def unexpected_commit(*args, **kwargs):
            pytest.fail("A stale sibling change must not reach a storage commit")

        monkeypatch.setattr(view, "run_screen", change_wallets)
        monkeypatch.setattr(self.controller, "load_seed", unexpected_commit)
        monkeypatch.setattr(self.controller, "replace_seed", unexpected_commit)
        destination = view.run()
        assert destination.clear_history
        if change == "remove_child":
            assert destination.View_cls is seed_views.SeedsMenuView
        else:
            assert destination.View_cls is seed_views.SeedBIP85ParentUnavailableView
            assert destination.view_args == {"seed": self.child, "missing_origin": False}
        assert all(seed is not candidate for seed in self.controller.storage.seeds)
        assert self.child.seed_bytes is self.child_bytes
        assert self.child.passphrase == "child extension"
        assert self.controller.storage.get_pending_seed() is self.pending

    @pytest.mark.parametrize("invalid_candidate", ["mnemonic", "origin", "passphrase", "word_count"])
    def test_save_rejects_candidate_that_is_not_a_bare_sibling(self, invalid_candidate):
        self.load_wallets()
        candidate = self.make_sibling()
        if invalid_candidate == "mnemonic":
            candidate = Seed(MNEMONIC, bip85_parent_fingerprint="b4e3f5ed",
                             bip85_child_index=LAST_INDEX, bip85_num_words=12)
        elif invalid_candidate == "origin":
            candidate.bip85_child_index = 0
        elif invalid_candidate == "passphrase":
            candidate.set_passphrase("unexpected inherited extension")
        else:
            candidate = Seed(SIBLING_WORDS[24].split(), bip85_parent_fingerprint="b4e3f5ed",
                             bip85_child_index=LAST_INDEX, bip85_num_words=24)

        view = seed_views.SeedBIP85SaveChildView(self.child, self.parent, candidate)
        assert view.has_redirect
        destination = view.get_redirect()
        assert destination.View_cls is seed_views.SeedBIP85ChildMenuView
        assert destination.view_args == {"seed": self.child}
        assert destination.clear_history
        self.assert_source_unchanged()

    @pytest.mark.parametrize("action", ["replace", "separate"])
    def test_save_selects_existing_canonical_sibling_without_duplicate(self, monkeypatch, action):
        self.load_wallets()
        canonical = self.make_sibling()
        self.controller.storage.seeds.append(canonical)
        candidate = self.make_sibling()
        view = seed_views.SeedBIP85SaveChildView(self.child, self.parent, candidate)
        assert not view.has_redirect
        monkeypatch.setattr(view, "run_screen", lambda *args, **kwargs: 0 if action == "replace" else 1)
        destination = view.run()
        assert destination.View_cls is seed_views.SeedOptionsView
        assert destination.view_args["seed"] is canonical
        assert destination.clear_history
        assert self.controller.storage.seeds[0] is self.parent
        assert len(self.controller.storage.seeds) == (2 if action == "replace" else 3)
        assert any(seed is self.child for seed in self.controller.storage.seeds) == (action == "separate")
        assert sum(seed is canonical for seed in self.controller.storage.seeds) == 1
        assert canonical.bip85_child_index == LAST_INDEX
        assert not canonical.has_passphrase
        assert self.child.passphrase == "child extension"
        assert self.controller.storage.get_pending_seed() is self.pending

    def test_grandchild_uses_selected_child_passphrase_and_loads_separately(self):
        self.load_wallets()

        def inspect_num_words(view):
            assert view.seed is self.child

        def inspect_grandchild(view):
            self.assert_source_unchanged()
            assert view.seed is self.child
            run_screen = view.run_screen

            def inspect_screen(*args, **kwargs):
                assert kwargs["fingerprint_parent"] == self.child.get_fingerprint()
                assert kwargs["fingerprint_parent"] != self.child.get_fingerprint_without_passphrase()
                assert kwargs["fingerprint_child"] == "1fccd34c"
                return run_screen(*args, **kwargs)

            view.run_screen = inspect_screen

        sequence = [
            FlowStep(seed_views.SeedOptionsView,
                     button_data_selection=seed_views.SeedOptionsView.BIP85_CHILD_SEED),
            FlowStep(seed_views.SeedBIP85ChildMenuView,
                     button_data_selection=seed_views.SeedBIP85ChildMenuView.DERIVE_CHILD),
            FlowStep(seed_views.SeedBIP85SelectNumWordsView, before_run=inspect_num_words,
                     button_data_selection=seed_views.SeedBIP85SelectNumWordsView.WORDS_12),
            FlowStep(seed_views.SeedBIP85SelectChildIndexView, screen_return_value="0"),
            FlowStep(seed_views.SeedBIP85ReviewView, before_run=inspect_grandchild,
                     button_data_selection=seed_views.SeedBIP85ReviewView.VIEW_WORDS),
            FlowStep(seed_views.SeedWordsWarningView, screen_return_value=0),
        ]
        sequence.extend(FlowStep(seed_views.SeedWordsView,
                                 button_data_selection=(seed_views.SeedWordsView.DONE if page == 3
                                                        else seed_views.SeedWordsView.NEXT)) for page in range(4))
        sequence.extend([
            FlowStep(seed_views.SeedWordsBackupTestPromptView,
                     button_data_selection=seed_views.SeedWordsBackupTestPromptView.LOAD_CHILD),
            FlowStep(seed_views.SeedBIP85LoadChildView, is_redirect=True),
            FlowStep(seed_views.SeedOptionsView),
        ])
        self.run_sequence(sequence, initial_destination_view_args={"seed": self.child})
        grandchild = self.controller.back_stack[-1].view_args["seed"]
        assert self.controller.storage.seeds[:2] == [self.parent, self.child]
        assert self.controller.storage.seeds[-1] is grandchild
        assert len(self.controller.storage.seeds) == 3
        assert grandchild.mnemonic_list == GRANDCHILD_WORDS.split()
        assert not grandchild.has_passphrase
        assert grandchild.bip85_parent_fingerprint == self.child.get_fingerprint()
        assert grandchild.bip85_child_index == 0
        assert grandchild.bip85_num_words == 12
        assert self.child.seed_bytes is self.child_bytes
        assert self.controller.storage.get_pending_seed() is self.pending

    def test_save_back_returns_to_backup_choice_without_loading_candidate(self):
        self.load_wallets()
        self.run_sequence(self.to_review() + self.word_pages() + [
            FlowStep(seed_views.SeedWordsBackupTestPromptView, before_run=self.inspect_backup_context,
                     button_data_selection=seed_views.SeedWordsBackupTestPromptView.LOAD_CHILD),
            FlowStep(seed_views.SeedBIP85LoadChildView, is_redirect=True),
            FlowStep(seed_views.SeedBIP85SaveChildView, before_run=self.inspect_save,
                     screen_return_value=RET_CODE__BACK_BUTTON),
            FlowStep(seed_views.SeedWordsBackupTestPromptView, before_run=self.inspect_backup_context,
                     button_data_selection=seed_views.SeedWordsBackupTestPromptView.LOAD_CHILD),
            FlowStep(seed_views.SeedBIP85LoadChildView, is_redirect=True),
            FlowStep(seed_views.SeedBIP85SaveChildView, before_run=self.inspect_save,
                     button_data_selection=seed_views.SeedBIP85SaveChildView.CANCEL),
            FlowStep(seed_views.SeedOptionsView),
        ], initial_destination_view_args={"seed": self.child})
        self.assert_source_unchanged()

    def test_backup_mistake_review_and_success_keep_sibling_change_context(self):
        self.load_wallets()
        sibling_words = SIBLING_WORDS[12].split()

        def choose_word(correct):
            def before_run(view):
                self.inspect_backup_context(view)
                assert view.mnemonic_list == sibling_words
                view.cur_index = next(index for index in range(12) if index not in view.confirmed_list)
                run_screen = view.run_screen

                def answer(*args, **kwargs):
                    run_screen(*args, **kwargs)
                    return next(index for index, button in enumerate(kwargs["button_data"])
                                if (button.button_label == sibling_words[view.cur_index]) == correct)

                view.run_screen = answer

            return before_run

        data = {"child_index": LAST_INDEX, "num_words": 12, "change_from_seed": self.child}
        sequence = [
            FlowStep(seed_views.SeedWordsBackupTestPromptView, before_run=self.inspect_backup_context,
                     button_data_selection=seed_views.SeedWordsBackupTestPromptView.VERIFY_CHILD),
            FlowStep(seed_views.SeedWordsBackupTestView, before_run=choose_word(False), screen_return_value=0),
            FlowStep(seed_views.SeedWordsBackupTestMistakeView, before_run=self.inspect_backup_context,
                     button_data_selection=seed_views.SeedWordsBackupTestMistakeView.REVIEW),
        ] + self.word_pages() + [
            FlowStep(seed_views.SeedWordsBackupTestPromptView, before_run=self.inspect_backup_context,
                     button_data_selection=seed_views.SeedWordsBackupTestPromptView.VERIFY_CHILD),
        ]
        sequence.extend(FlowStep(seed_views.SeedWordsBackupTestView,
                                 before_run=choose_word(True), screen_return_value=0) for _ in range(12))
        sequence.extend([
            FlowStep(seed_views.SeedWordsBackupTestSuccessView, before_run=self.inspect_backup_context,
                     screen_return_value=0),
            FlowStep(seed_views.SeedBIP85LoadChildView, is_redirect=True),
            FlowStep(seed_views.SeedBIP85SaveChildView, before_run=self.inspect_save,
                     button_data_selection=seed_views.SeedBIP85SaveChildView.LOAD_SEPARATELY),
            FlowStep(seed_views.SeedOptionsView),
        ])
        self.run_sequence(sequence, initial_destination_view_args={"seed": self.parent, "bip85_data": data})
        assert len(self.controller.storage.seeds) == 3
        assert self.controller.storage.seeds[1] is self.child
        assert self.controller.storage.seeds[-1].mnemonic_list == sibling_words
        assert self.controller.storage.seeds[-1].bip85_child_index == LAST_INDEX
        assert self.controller.storage.get_pending_seed() is self.pending
