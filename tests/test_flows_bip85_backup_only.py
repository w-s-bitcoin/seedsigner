"""Copying or verifying a BIP-85 backup must not require loading its wallet."""
from unittest.mock import patch

import pytest

# Install hardware mocks before importing application Views.
from base import FlowStep, FlowTest

from seedsigner.controller import StopFlowBasedTest
from seedsigner.models.seed import Seed
from seedsigner.models.settings import SettingsConstants
from seedsigner.views import seed_views
from seedsigner.views.view import MainMenuView


MNEMONIC = ["abandon"] * 11 + ["about"]


class TestBIP85BackupOnly(FlowTest):
    def prepare_backup(self, scenario, num_words):
        root = Seed(MNEMONIC, "TREZOR")
        child = Seed(
            root.get_bip85_child_mnemonic(0, num_words).split(), "child extension",
            bip85_parent_fingerprint=root.get_fingerprint(),
            bip85_child_index=0, bip85_num_words=num_words,
        )
        # Keep a crowded list, unrelated pending seed and incomplete entry intact.
        self.originals = [root, child] + [Seed(MNEMONIC, f"other {i}") for i in range(10)]
        self.controller.storage.seeds = list(self.originals)
        self.pending = Seed(MNEMONIC, "pending")
        self.controller.storage.set_pending_seed(self.pending)
        self.controller.storage.init_pending_mnemonic(12)
        self.controller.storage.update_pending_mnemonic("abandon", 0)
        self.pending_words = self.controller.storage.pending_mnemonic
        self.identities = [self.identity(seed) for seed in self.originals]
        self.settings.set_value(SettingsConstants.SETTING__BIP85_CHILD_SEEDS, SettingsConstants.OPTION__ENABLED)
        self.settings.set_value(SettingsConstants.SETTING__PASSPHRASE, SettingsConstants.OPTION__ENABLED)
        parent = child if scenario == "grandchild" else root
        selected = child if scenario == "sibling" else parent
        context = {"num_words": num_words, "child_index": 1}
        if scenario == "sibling":
            context["change_from_seed"] = child
        return parent, selected, context

    @staticmethod
    def identity(seed):
        return (
            seed.seed_bytes, tuple(seed.mnemonic_list), seed.passphrase,
            seed.is_bip85_child, seed.bip85_parent_fingerprint,
            seed.bip85_child_index, seed.bip85_num_words,
        )

    def assert_unchanged(self):
        assert len(self.controller.storage.seeds) == len(self.originals)
        assert all(actual is original for actual, original in zip(self.controller.storage.seeds, self.originals))
        assert [self.identity(seed) for seed in self.controller.storage.seeds] == self.identities
        assert self.controller.storage.get_pending_seed() is self.pending
        assert self.controller.storage.pending_mnemonic == self.pending_words

    @pytest.mark.parametrize("scenario", ["child", "grandchild", "sibling"])
    @pytest.mark.parametrize("num_words", [12, 24])
    @pytest.mark.parametrize("verify", [False, True])
    def test_finish_without_loading_returns_to_original_wallet(self, scenario, num_words, verify):
        parent, selected, context = self.prepare_backup(scenario, num_words)
        child_words = parent.get_bip85_child_mnemonic(context["child_index"], num_words).split()

        def answer_word(view):
            self.assert_unchanged()
            assert view.mnemonic_list == child_words
            view.cur_index = next(i for i in range(num_words) if i not in view.confirmed_list)
            run_screen = view.run_screen

            def choose_correct_word(*args, **kwargs):
                run_screen(*args, **kwargs)
                return next(i for i, option in enumerate(kwargs["button_data"])
                            if option.button_label == child_words[view.cur_index])

            view.run_screen = choose_correct_word

        def inspect_return(view):
            assert view.seed is selected
            self.assert_unchanged()

        sequence = [
            FlowStep(seed_views.SeedWordsView, button_data_selection=seed_views.SeedWordsView.DONE),
            FlowStep(seed_views.SeedWordsBackupTestPromptView, button_data_selection=(
                seed_views.SeedWordsBackupTestPromptView.VERIFY_CHILD if verify
                else seed_views.SeedWordsBackupTestPromptView.DONE_CHILD)),
        ]
        if verify:
            sequence.extend(FlowStep(seed_views.SeedWordsBackupTestView, before_run=answer_word,
                                     screen_return_value=0) for _ in range(num_words))
            sequence.append(FlowStep(seed_views.SeedWordsBackupTestSuccessView,
                                     button_data_selection=seed_views.SeedWordsBackupTestSuccessView.DONE_CHILD))
        sequence.append(FlowStep(seed_views.SeedOptionsView, before_run=inspect_return,
                                 screen_return_value=StopFlowBasedTest()))
        with patch.object(self.controller, "load_seed") as load, patch.object(self.controller, "replace_seed") as replace:
            self.run_sequence(sequence, initial_destination_view_args={
                "seed": parent, "bip85_data": context, "page_index": num_words // 3 - 1,
            })
            load.assert_not_called()
            replace.assert_not_called()
        self.assert_unchanged()
        assert len(self.controller.back_stack) == 1
        assert self.controller.back_stack[-1].view_args == {"seed": selected}

    @pytest.mark.parametrize("scenario", ["child", "grandchild", "sibling"])
    @pytest.mark.parametrize("after_verification", [False, True])
    @pytest.mark.parametrize("seeds_remain", [False, True])
    def test_stale_completion_never_reopens_removed_wallet(self, scenario, after_verification, seeds_remain):
        parent, selected, context = self.prepare_backup(scenario, 12)
        cls = (seed_views.SeedWordsBackupTestSuccessView if after_verification
               else seed_views.SeedWordsBackupTestPromptView)
        view = cls(seed=parent, bip85_data=context)

        def finish(*args, **kwargs):
            # Replace by an equal object while the screen is displayed. Identity,
            # not an XFP or full seed equality, determines whether it is still loaded.
            self.controller.storage.seeds = [Seed(selected.mnemonic_list, selected.passphrase)] if seeds_remain else []
            return kwargs["button_data"].index(cls.DONE_CHILD)

        with patch.object(view, "run_screen", side_effect=finish):
            destination = view.run()
        assert destination.View_cls is (seed_views.SeedsMenuView if seeds_remain else MainMenuView)
        assert destination.clear_history
        assert self.controller.storage.get_pending_seed() is self.pending
        assert self.controller.storage.pending_mnemonic == self.pending_words
