import logging
import random
import time

from binascii import hexlify
from gettext import gettext as _

from embit.descriptor import Descriptor

from seedsigner.gui.components import FontAwesomeIconConstants, GUIConstants, SeedSignerIconConstants
from seedsigner.gui.screens import (RET_CODE__BACK_BUTTON, ButtonListScreen,
    WarningScreen, DireWarningScreen, seed_screens)
from seedsigner.gui.screens.screen import ButtonOption, ButtonOptionWithoutTranslation
from seedsigner.models.encode_qr import CompactSeedQrEncoder, GenericStaticQrEncoder, SeedQrEncoder, SpecterLegacyXPubQrEncoder, StaticXpubQrEncoder, UrXpubQrEncoder
from seedsigner.models.qr_type import QRType
from seedsigner.models.seed import ElectrumSeed, Seed
from seedsigner.models.settings import Settings, SettingsConstants
from seedsigner.models.settings_definition import SettingsDefinition
from seedsigner.models.threads import BaseThread, ThreadsafeCounter
from seedsigner.views.view import NotYetImplementedView, OptionDisabledView, View, Destination, BackStackView, MainMenuView

logger = logging.getLogger(__name__)



class SeedsMenuView(View):
    LOAD = ButtonOption("Load a seed")

    def __init__(self):
        super().__init__()
        self.seeds = []
        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
        for seed in self.controller.storage.seeds:
            fingerprint = seed.get_fingerprint(network)
            fingerprints = []
            arrow_colors = []
            selected_arrow_colors = []
            # Display only the immediate relationship, even for a passphrased child.
            if seed.has_passphrase:
                fingerprints.append(seed.get_fingerprint_without_passphrase(network))
                arrow_colors.append(GUIConstants.PASSPHRASE_COLOR)
                selected_arrow_colors.append(GUIConstants.PASSPHRASE_COLOR_SELECTED)
            elif seed.bip85_parent_fingerprint is not None:
                fingerprints.append(seed.bip85_parent_fingerprint)
                arrow_colors.append(GUIConstants.BIP85_COLOR)
                selected_arrow_colors.append(GUIConstants.BIP85_COLOR_SELECTED)
            fingerprints.append(fingerprint)
            self.seeds.append({
                "fingerprint": fingerprint,
                "lifehash_fingerprints": tuple(fingerprints),
                "lifehash_arrow_colors": tuple(arrow_colors),
                "selected_lifehash_arrow_colors": tuple(selected_arrow_colors),
            })


    def run(self):
        if not self.seeds:
            # Nothing to do here unless we have a seed loaded
            return Destination(LoadSeedView, clear_history=True)

        button_data = []
        for seed in self.seeds:
            button_data.append(ButtonOption(
                seed["fingerprint"],
                lifehash_fingerprints=seed["lifehash_fingerprints"],
                lifehash_arrow_colors=seed["lifehash_arrow_colors"],
                selected_lifehash_arrow_colors=seed["selected_lifehash_arrow_colors"],
                font_name=GUIConstants.FIXED_WIDTH_FONT_NAME,
                font_size=20,
            ))
        button_data.append(self.LOAD)

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title=_("In-Memory Seeds"),
            is_button_text_centered=False,
            button_data=button_data
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        elif len(self.seeds) > 0 and selected_menu_num < len(self.seeds):
            selected_seed = self.controller.storage.seeds[selected_menu_num]
            return Destination(SeedOptionsView, view_args={"seed": selected_seed})

        elif button_data[selected_menu_num] == self.LOAD:
            return Destination(LoadSeedView)



class SeedSelectSeedView(View):
    """
    Reusable seed selection UI. Prompts the user to select amongst the already-loaded
    seeds OR to load a seed.

    * `flow`: indicates which user flow is in progress during seed selection (e.g.
                verify single sig addr or sign message).
    """
    SCAN_SEED = ButtonOption("Scan a seed", SeedSignerIconConstants.QRCODE)
    TYPE_12WORD = ButtonOption("Enter 12-word seed", FontAwesomeIconConstants.KEYBOARD)
    TYPE_24WORD = ButtonOption("Enter 24-word seed", FontAwesomeIconConstants.KEYBOARD)
    TYPE_ELECTRUM = ButtonOption("Enter Electrum seed", FontAwesomeIconConstants.KEYBOARD)


    def __init__(self, flow: str):
        super().__init__()
        self.flow = flow


    def run(self):
        from seedsigner.controller import Controller
        seeds = self.controller.storage.seeds

        if self.flow == Controller.FLOW__VERIFY_SINGLESIG_ADDR:
            title = _("Verify Address")
            if not seeds:
                text = _("Load the seed to verify")
            else: 
                text = _("Select seed to verify")

        elif self.flow == Controller.FLOW__SIGN_MESSAGE:
            title = _("Sign Message")
            if not seeds:
                text = _("Load the seed to sign with")
            else:
                text = _("Select seed to sign with")

        else:
            raise Exception(f"Unsupported `flow` specified: {self.flow}")

        button_data = []
        for seed in seeds:
            button_str = seed.get_fingerprint(self.settings.get_value(SettingsConstants.SETTING__NETWORK))
            button_data.append(ButtonOption(button_str, SeedSignerIconConstants.FINGERPRINT, icon_color="blue",
                                            lifehash_fingerprint=button_str))
        
        button_data.append(self.SCAN_SEED)
        button_data.append(self.TYPE_12WORD)
        button_data.append(self.TYPE_24WORD)

        if self.settings.get_value(SettingsConstants.SETTING__ELECTRUM_SEEDS) == SettingsConstants.OPTION__ENABLED:
            button_data.append(self.TYPE_ELECTRUM)

        selected_menu_num = self.run_screen(
            seed_screens.SeedSelectSeedScreen,
            title=title,
            text=text,
            is_button_text_centered=False,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        
        if len(seeds) > 0 and selected_menu_num < len(seeds):
            # User selected one of the n seeds
            seed = seeds[selected_menu_num]
            if self.flow == Controller.FLOW__VERIFY_SINGLESIG_ADDR:
                return Destination(SeedAddressVerificationView, view_args={"seed": seed})

            elif self.flow == Controller.FLOW__SIGN_MESSAGE:
                self.controller.sign_message_data["seed"] = seed
                return Destination(SeedSignMessageConfirmMessageView)

        self.controller.resume_main_flow = self.flow

        if button_data[selected_menu_num] == self.SCAN_SEED:
            from seedsigner.views.scan_views import ScanView
            return Destination(ScanView)

        elif button_data[selected_menu_num] in [self.TYPE_12WORD, self.TYPE_24WORD]:
            from seedsigner.views.seed_views import SeedMnemonicEntryView
            if button_data[selected_menu_num] == self.TYPE_12WORD:
                self.controller.storage.init_pending_mnemonic(num_words=12)
            else:
                self.controller.storage.init_pending_mnemonic(num_words=24)
            return Destination(SeedMnemonicEntryView)

        elif button_data[selected_menu_num] == self.TYPE_ELECTRUM:
            return Destination(SeedElectrumMnemonicStartView)



"""****************************************************************************
    Loading seeds, passphrases, etc
****************************************************************************"""
class LoadSeedView(View):
    SEED_QR = ButtonOption("Scan a SeedQR", SeedSignerIconConstants.QRCODE)
    TYPE_12WORD = ButtonOption("Enter 12-word seed", FontAwesomeIconConstants.KEYBOARD)
    TYPE_24WORD = ButtonOption("Enter 24-word seed", FontAwesomeIconConstants.KEYBOARD)
    TYPE_ELECTRUM = ButtonOption("Enter Electrum seed", FontAwesomeIconConstants.KEYBOARD)
    CREATE = ButtonOption("Create a seed", SeedSignerIconConstants.PLUS)

    def run(self):
        button_data = [
            self.SEED_QR,
            self.TYPE_12WORD,
            self.TYPE_24WORD,
        ]

        if self.settings.get_value(SettingsConstants.SETTING__ELECTRUM_SEEDS) == SettingsConstants.OPTION__ENABLED:
            button_data.append(self.TYPE_ELECTRUM)
        
        button_data.append(self.CREATE)

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title=_("Load a Seed"),
            is_button_text_centered=False,
            button_data=button_data
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        
        if button_data[selected_menu_num] == self.SEED_QR:
            from .scan_views import ScanSeedQRView
            return Destination(ScanSeedQRView)
        
        elif button_data[selected_menu_num] == self.TYPE_12WORD:
            self.controller.storage.init_pending_mnemonic(num_words=12)
            return Destination(SeedMnemonicEntryView)

        elif button_data[selected_menu_num] == self.TYPE_24WORD:
            self.controller.storage.init_pending_mnemonic(num_words=24)
            return Destination(SeedMnemonicEntryView)

        elif button_data[selected_menu_num] == self.TYPE_ELECTRUM:
            return Destination(SeedElectrumMnemonicStartView)

        elif button_data[selected_menu_num] == self.CREATE:
            from .tools_views import ToolsMenuView
            return Destination(ToolsMenuView)



class SeedMnemonicEntryView(View):
    def __init__(self, cur_word_index: int = 0, is_calc_final_word: bool=False):
        super().__init__()
        self.cur_word_index = cur_word_index
        self.cur_word = self.controller.storage.get_pending_mnemonic_word(cur_word_index)
        self.is_calc_final_word = is_calc_final_word


    def run(self):
        ret = self.run_screen(
            seed_screens.SeedMnemonicEntryScreen,
            # TRANSLATOR_NOTE: Inserts the word number (e.g. "Seed Word #6")
            title=_("Seed Word #{}").format(self.cur_word_index + 1),  # Human-readable 1-indexing!
            initial_letters=list(self.cur_word) if self.cur_word else ["a"],
            wordlist=Seed.get_wordlist(wordlist_language_code=self.settings.get_value(SettingsConstants.SETTING__WORDLIST_LANGUAGE)),
        )

        if ret == RET_CODE__BACK_BUTTON:
            # This handles two possible scenarios:
            # 1. Backing out of the first word cancels the mnemonic entry process;
            #    return to whichever `View` routed us here initially.
            # 2. Backing out of the current word returns to the previous word.
            if self.cur_word_index == 0:
                self.controller.storage.discard_pending_mnemonic()
            return Destination(BackStackView)
        
        # ret will be our new mnemonic word
        self.controller.storage.update_pending_mnemonic(ret, self.cur_word_index)

        if self.is_calc_final_word and self.cur_word_index == self.controller.storage.pending_mnemonic_length - 2:
            # Time to calculate the last word. User must decide how they want to specify
            # the last bits of entropy for the final word.
            from seedsigner.views.tools_views import ToolsCalcFinalWordFinalizePromptView
            return Destination(ToolsCalcFinalWordFinalizePromptView)

        if self.is_calc_final_word and self.cur_word_index == self.controller.storage.pending_mnemonic_length - 1:
            # Time to calculate the last word. User must either select a final word to
            # contribute entropy to the checksum word OR we assume 0 ("abandon").
            from seedsigner.views.tools_views import ToolsCalcFinalWordShowFinalWordView
            return Destination(ToolsCalcFinalWordShowFinalWordView)

        if self.cur_word_index < self.controller.storage.pending_mnemonic_length - 1:
            return Destination(
                SeedMnemonicEntryView,
                view_args={
                    "cur_word_index": self.cur_word_index + 1,
                    "is_calc_final_word": self.is_calc_final_word
                }
            )
        else:
            # Attempt to finalize the mnemonic
            from seedsigner.models.seed import InvalidSeedException
            try:
                self.controller.storage.convert_pending_mnemonic_to_pending_seed()
            except InvalidSeedException:
                return Destination(SeedMnemonicInvalidView)

            return Destination(SeedFinalizeView)



class SeedMnemonicInvalidView(View):
    EDIT = ButtonOption("Review & edit")
    DISCARD = ButtonOption("Discard", button_label_color="red")

    def __init__(self):
        super().__init__()
        self.mnemonic: list[str] = self.controller.storage.pending_mnemonic


    def run(self):
        button_data = [self.EDIT, self.DISCARD]
        selected_menu_num = self.run_screen(
            DireWarningScreen,
            title=_("Invalid Mnemonic!"),
            status_icon_name=SeedSignerIconConstants.ERROR,
            status_headline=None,
            text=_("Checksum failure; not a valid seed phrase."),
            show_back_button=False,
            button_data=button_data,
        )

        if button_data[selected_menu_num] == self.EDIT:
            return Destination(SeedMnemonicEntryView, view_args={"cur_word_index": 0})

        elif button_data[selected_menu_num] == self.DISCARD:
            self.controller.storage.discard_pending_mnemonic()
            return Destination(MainMenuView)



class SeedFinalizeView(View):
    FINALIZE = ButtonOption("Done")
    PASSPHRASE = ButtonOption("BIP-39 Passphrase")

    def __init__(self):
        super().__init__()
        self.seed = self.controller.storage.get_pending_seed()

        self.fingerprint = self.seed.get_fingerprint_without_passphrase(
            network=self.settings.get_value(SettingsConstants.SETTING__NETWORK))


    def run(self):
        button_data = [self.FINALIZE]
        self.PASSPHRASE.button_label = self.seed.passphrase_label
        if self.settings.get_value(SettingsConstants.SETTING__PASSPHRASE) != SettingsConstants.OPTION__DISABLED:
            button_data.append(self.PASSPHRASE)

        selected_menu_num = self.run_screen(
            seed_screens.SeedFinalizeScreen,
            fingerprint=self.fingerprint,
            button_data=button_data,
        )

        if button_data[selected_menu_num] == self.FINALIZE:
            seed = self.controller.storage.finalize_pending_seed()
            return Destination(SeedOptionsView, view_args={"seed": seed}, clear_history=True)

        elif button_data[selected_menu_num] == self.PASSPHRASE:
            return Destination(SeedAddPassphraseView)



class SeedAddPassphraseView(View):
    """
    initial_keyboard: used by the screenshot generator to render each different keyboard layout.
    """
    def __init__(self, initial_keyboard: str = seed_screens.SeedAddPassphraseScreen.KEYBOARD__LOWERCASE_BUTTON_TEXT):
        super().__init__()
        self.initial_keyboard = initial_keyboard
        self.seed = self.controller.storage.get_pending_seed()


    def run(self):
        passphrase_title=self.seed.passphrase_label
        ret_dict = self.run_screen(
            seed_screens.SeedAddPassphraseScreen,
            passphrase=self.seed.passphrase,
            title=passphrase_title,
            initial_keyboard=self.initial_keyboard,
        )

        # The new passphrase will be the return value; it might be empty.
        self.seed.set_passphrase(ret_dict["passphrase"])

        if "is_back_button" in ret_dict or len(self.seed.passphrase) == 0:
            return Destination(SeedAddPassphraseExitDialogView)
                    
        else:
            return Destination(SeedReviewPassphraseView)



class SeedAddPassphraseExitDialogView(View):
    EDIT = ButtonOption("Edit passphrase")
    DISCARD = ButtonOption("Discard passphrase", button_label_color="red")
    SKIP = ButtonOption("Skip passphrase")  # NOT red since we're not throwing anything away

    def __init__(self):
        super().__init__()
        self.seed = self.controller.storage.get_pending_seed()


    def run(self):
        if self.seed.passphrase:
            title = _("Discard passphrase?")
            message = _("Your current passphrase entry will be erased.")
            button_data = [self.EDIT, self.DISCARD]
        else:
            title = _("Skip passphrase?")
            message = _("You have not entered a passphrase yet.")
            button_data = [self.EDIT, self.SKIP]
        
        selected_menu_num = self.run_screen(
            WarningScreen,
            title=title,
            status_headline=None,
            text=message,
            show_back_button=False,
            button_data=button_data,
        )

        if button_data[selected_menu_num] == self.EDIT:
            return Destination(SeedAddPassphraseView)

        elif button_data[selected_menu_num] in [self.DISCARD, self.SKIP]:
            self.seed.set_passphrase("")
            return Destination(SeedFinalizeView)
        


class SeedReviewPassphraseView(View):
    """
        Display the completed passphrase back to the user.
    """
    EDIT = ButtonOption("Edit passphrase")
    DONE = ButtonOption("Done")
    NEXT = ButtonOption("Next")

    def __init__(self, page_index: int = 0):
        super().__init__()
        self.seed = self.controller.storage.get_pending_seed()
        self.page_index = page_index


    def run(self):
        # Derive both display identities without changing the pending seed.
        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
        fingerprint_with = self.seed.get_fingerprint(network=network)
        fingerprint_without = self.seed.get_fingerprint_without_passphrase(network=network)
        
        pages = seed_screens.SeedReviewPassphraseScreen.passphrase_pages(self.seed.passphrase)
        last_page = self.page_index == len(pages) - 1
        button_data = [self.EDIT, self.DONE if last_page else self.NEXT]

        # Because we have an explicit "Edit" button, we disable "BACK" to keep the
        # routing options sane.
        selected_menu_num = self.run_screen(
            seed_screens.SeedReviewPassphraseScreen,
            fingerprint_without=fingerprint_without,
            fingerprint_with=fingerprint_with,
            passphrase=self.seed.passphrase,
            page_index=self.page_index,
            button_data=button_data,
            show_back_button=False,
        )

        if button_data[selected_menu_num] == self.EDIT:
            return Destination(SeedAddPassphraseView)

        elif button_data[selected_menu_num] == self.NEXT:
            return Destination(SeedReviewPassphraseView, view_args={"page_index": self.page_index + 1})
        
        elif button_data[selected_menu_num] == self.DONE:
            seed = self.controller.storage.finalize_pending_seed()
            return Destination(SeedOptionsView, view_args={"seed": seed}, clear_history=True)
            

            
class SeedLoadedPassphraseView(View):
    """Edit a private candidate; never put passphrase text in logged Destinations."""

    def __init__(self, seed: Seed, passphrase: str = None, candidate: Seed = None):
        super().__init__()
        self.seed = seed
        unavailable = self.validate_source()
        if unavailable:
            self.set_redirect(unavailable)
            return

        # Keep finalized Seeds immutable until the user explicitly confirms. In
        # particular, existing PSBT parsers may still reference the source object.
        self.candidate = candidate if candidate is not None else Seed(
            mnemonic=seed.mnemonic_list,
            passphrase=seed.passphrase if passphrase is None else passphrase,
            wordlist_language_code=seed.wordlist_language_code,
            is_bip85_child=seed.is_bip85_child,
            bip85_parent_fingerprint=seed.bip85_parent_fingerprint,
            bip85_child_index=seed.bip85_child_index,
            bip85_num_words=seed.bip85_num_words,
        )

    def validate_source(self):
        if not any(loaded is self.seed for loaded in self.controller.storage.seeds):
            return Destination(SeedsMenuView, clear_history=True)
        if (isinstance(self.seed, ElectrumSeed)
                or self.settings.get_value(SettingsConstants.SETTING__PASSPHRASE) == SettingsConstants.OPTION__DISABLED):
            return Destination(SeedOptionsView, view_args={"seed": self.seed}, clear_history=True)
        return None

    def destination(self, view_cls, **kwargs):
        return Destination(view_cls, view_args={"seed": self.seed, "candidate": self.candidate, **kwargs})

    def cancel(self):
        # Clearing history drops references to the discarded candidate too.
        return Destination(SeedOptionsView, view_args={"seed": self.seed}, clear_history=True)


class SeedPassphraseMenuView(SeedLoadedPassphraseView):
    EDIT = ButtonOption("Edit passphrase")
    CHANGE = ButtonOption("Different passphrase")
    REMOVE = ButtonOption("Remove passphrase", button_label_color="red")

    def __init__(self, seed: Seed):
        super().__init__(seed)
        if not self.has_redirect and not seed.has_passphrase:
            self.set_redirect(self.destination(SeedEditPassphraseView))

    def run(self):
        button_data = [self.EDIT, self.CHANGE, self.REMOVE]
        selected = self.run_screen(ButtonListScreen, title=_("BIP-39 Passphrase"), button_data=button_data)
        if selected == RET_CODE__BACK_BUTTON:
            return self.cancel()
        if button_data[selected] == self.EDIT:
            return self.destination(SeedEditPassphraseView)
        self.candidate.set_passphrase("")
        if button_data[selected] == self.CHANGE:
            return self.destination(SeedEditPassphraseView)
        return self.destination(SeedConfirmPassphraseView)


class SeedEditPassphraseView(SeedLoadedPassphraseView):
    def run(self):
        result = self.run_screen(seed_screens.SeedAddPassphraseScreen,
                                 passphrase=self.candidate.passphrase,
                                 title=self.seed.passphrase_label)
        self.candidate.set_passphrase(result["passphrase"])
        if "is_back_button" in result:
            return self.destination(SeedCancelPassphraseView)
        return self.destination(SeedConfirmPassphraseView)


class SeedCancelPassphraseView(SeedLoadedPassphraseView):
    KEEP_EDITING = ButtonOption("Keep editing")
    DISCARD = ButtonOption("Discard changes", button_label_color="red")

    def run(self):
        button_data = [self.KEEP_EDITING, self.DISCARD]
        selected = self.run_screen(WarningScreen, title=_("Discard Changes?"),
                                   status_headline=None,
                                   text=_("The loaded wallet will stay unchanged."),
                                   show_back_button=False, button_data=button_data)
        if button_data[selected] == self.KEEP_EDITING:
            return self.destination(SeedEditPassphraseView)
        return self.cancel()


class SeedConfirmPassphraseView(SeedLoadedPassphraseView):
    EDIT = ButtonOption("Edit passphrase")
    APPLY = ButtonOption("Continue")
    CANCEL = ButtonOption("Cancel")
    NEXT = ButtonOption("Next")
    REMOVE = ButtonOption("Remove passphrase", button_label_color="red")

    def __init__(self, seed: Seed, passphrase: str = None, candidate: Seed = None, page_index: int = 0):
        super().__init__(seed, passphrase, candidate)
        self.page_index = page_index
        if not self.has_redirect and not self.seed.has_passphrase and not self.candidate.has_passphrase:
            # Submitting an empty addition does not remove anything. Leave the
            # loaded seed, pending entry, and signing state untouched.
            self.set_redirect(self.cancel())

    def run(self):
        pages = seed_screens.SeedConfirmPassphraseScreen.passphrase_pages(self.candidate.passphrase_display)
        last_page = self.page_index == len(pages) - 1
        button_data = [self.APPLY if last_page else self.NEXT, self.EDIT, self.CANCEL]
        if not self.candidate.has_passphrase:
            button_data = [self.CANCEL, self.REMOVE]
        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
        # The review always starts from the mnemonic without a passphrase,
        # even when replacing an existing one. Derive this display identity
        # separately: signing state may still reference the loaded Seed.
        fingerprint_without = self.seed.get_fingerprint_without_passphrase(network)
        selected = self.run_screen(seed_screens.SeedConfirmPassphraseScreen,
                                   fingerprint_without=fingerprint_without,
                                   fingerprint_new=self.candidate.get_fingerprint(network),
                                   passphrase=self.candidate.passphrase_display,
                                   page_index=self.page_index,
                                   button_data=button_data,
                                   selected_button=0,
                                   show_back_button=False)
        # Recheck after input before removal or entering the save choice. The
        # source may have been discarded or editing disabled while this ran.
        unavailable = self.validate_source()
        if unavailable:
            return unavailable
        if selected == RET_CODE__BACK_BUTTON or button_data[selected] == self.CANCEL:
            return self.cancel()
        if button_data[selected] == self.EDIT:
            return self.destination(SeedEditPassphraseView)
        if button_data[selected] == self.NEXT:
            return self.destination(SeedConfirmPassphraseView, page_index=self.page_index + 1)
        if button_data[selected] == self.APPLY:
            return self.destination(SeedPassphraseSaveView)

        # Removal keeps its explicit confirmation and returns to the unextended
        # wallet without an additional save choice.
        seed = self.controller.replace_seed(self.seed, self.candidate)
        return Destination(SeedOptionsView, view_args={"seed": seed}, clear_history=True)


class SeedPassphraseSaveView(SeedLoadedPassphraseView):
    REPLACE = ButtonOption("Replace current")
    LOAD_SEPARATELY = ButtonOption("Load separately")
    CANCEL = ButtonOption("Cancel")

    def __init__(self, seed: Seed, passphrase: str = None, candidate: Seed = None):
        super().__init__(seed, passphrase, candidate)
        if not self.has_redirect and not self.candidate.has_passphrase:
            self.set_redirect(self.destination(SeedConfirmPassphraseView))

    def run(self):
        button_data = [self.REPLACE, self.LOAD_SEPARATELY, self.CANCEL]
        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
        selected = self.run_screen(
            seed_screens.SeedPassphraseSaveScreen,
            fingerprint_without=self.seed.get_fingerprint_without_passphrase(network),
            fingerprint_new=self.candidate.get_fingerprint(network),
            fingerprint_current=self.seed.get_fingerprint(network),
            button_data=button_data,
            selected_button=0,
        )
        unavailable = self.validate_source()
        if unavailable:
            return unavailable
        if selected == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        if button_data[selected] == self.CANCEL:
            return self.cancel()
        if button_data[selected] == self.LOAD_SEPARATELY:
            seed = self.controller.load_seed(self.candidate)
        else:
            seed = self.controller.replace_seed(self.seed, self.candidate)
        return Destination(SeedOptionsView, view_args={"seed": seed}, clear_history=True)


class SeedDiscardView(View):
    KEEP = ButtonOption("Keep seed")
    DISCARD = ButtonOption("Discard", button_label_color="red")

    def __init__(self, seed: Seed = None):
        super().__init__()
        if seed is None:
            self.is_pending_seed = True
            self.seed = self.controller.storage.get_pending_seed()
        else:
            self.is_pending_seed = False
            self.seed = seed
            unavailable = self.validate_loaded_seed()
            if unavailable:
                self.set_redirect(unavailable)


    def validate_loaded_seed(self):
        if not self.is_pending_seed and not any(loaded is self.seed for loaded in self.controller.storage.seeds):
            return Destination(SeedsMenuView if self.controller.storage.num_seeds() else MainMenuView,
                               clear_history=True)
        return None


    def run(self):
        button_data = [self.KEEP, self.DISCARD]

        fingerprint = self.seed.get_fingerprint(self.settings.get_value(SettingsConstants.SETTING__NETWORK))
        # TRANSLATOR_NOTE: Inserts the fingerprint of the seed being discarded.
        text = _("Wipe seed {} from the device?").format(fingerprint)
        selected_menu_num = self.run_screen(
            WarningScreen,
            title=_("Discard Seed?"),
            status_headline=None,
            text=text,
            lifehash_fingerprint=fingerprint,
            show_back_button=False,
            button_data=button_data,
        )

        unavailable = self.validate_loaded_seed()
        if unavailable:
            return unavailable
        if button_data[selected_menu_num] == self.KEEP:
            # Use skip_current_view=True to prevent BACK from landing on this warning screen
            if self.is_pending_seed:
                return Destination(SeedFinalizeView, skip_current_view=True)
            else:
                return Destination(SeedOptionsView, view_args={"seed": self.seed}, skip_current_view=True)

        elif button_data[selected_menu_num] == self.DISCARD:
            if self.is_pending_seed:
                self.controller.storage.clear_pending_seed()
            else:
                self.controller.discard_seed(self.seed)
                # Returning directly to the seed list must still release wallet
                # state that was previously cleared on arrival at the main menu.
                self.controller.clear_wallet_state()
                if self.controller.storage.num_seeds() > 0:
                    return Destination(SeedsMenuView, clear_history=True)
            return Destination(MainMenuView, clear_history=True)



class SeedElectrumMnemonicStartView(View):
    """
    Currently just a warning display before entering an Electrum seed.
    
    Could be expanded with a follow-up View to specify Electrum seed type.
    """
    def run(self):
        self.run_screen(
                WarningScreen,
                title=_("Electrum Warning"),
                status_headline=None,
                text=_("Some features are disabled for Electrum seeds."),
                show_back_button=False,
        )

        self.controller.storage.init_pending_mnemonic(num_words=12, is_electrum=True)

        return Destination(SeedMnemonicEntryView)



"""****************************************************************************
    Views for actions on individual seeds:
****************************************************************************"""
class SeedOptionsView(View):
    SCAN_PSBT = ButtonOption("Scan transaction", SeedSignerIconConstants.QRCODE)
    EXPORT_XPUB = ButtonOption("Export xpub")
    EXPLORER = ButtonOption("Address explorer")
    SIGN_MESSAGE = ButtonOption("Sign message")
    BACKUP = ButtonOption("Backup seed", right_icon_name=SeedSignerIconConstants.CHEVRON_RIGHT)
    BIP85_CHILD_SEED = ButtonOption("BIP-85 child seed")
    PASSPHRASE = ButtonOption("BIP-39 Passphrase", right_icon_name=SeedSignerIconConstants.CHEVRON_RIGHT)
    DISCARD = ButtonOption("Discard seed", button_label_color="red")


    def __init__(self, seed: Seed):
        super().__init__()
        self.seed = seed


    def run(self):
        from seedsigner.controller import Controller
        from seedsigner.views.psbt_views import PSBTOverviewView

        if self.controller.unverified_address:
            if self.controller.resume_main_flow == Controller.FLOW__VERIFY_SINGLESIG_ADDR:
                # Jump straight back into the single sig addr verification flow
                self.controller.resume_main_flow = None
                return Destination(SeedAddressVerificationView, view_args=dict(seed=self.seed), skip_current_view=True)

        if self.controller.resume_main_flow == Controller.FLOW__ADDRESS_EXPLORER:
            # Jump straight back into the address explorer script type selection flow
            # But don't cancel the `resume_main_flow` as we'll still need that after
            # derivation path is specified.
            return Destination(SeedExportXpubScriptTypeView, view_args=dict(seed=self.seed, sig_type=SettingsConstants.SINGLE_SIG), skip_current_view=True)

        elif self.controller.resume_main_flow == Controller.FLOW__SIGN_MESSAGE:
            self.controller.sign_message_data["seed"] = self.seed
            return Destination(SeedSignMessageConfirmMessageView, skip_current_view=True)

        if self.controller.psbt:
            from seedsigner.models.psbt_parser import PSBTParser
            if PSBTParser.has_matching_input_fingerprint(self.controller.psbt, self.seed, network=self.settings.get_value(SettingsConstants.SETTING__NETWORK)):
                if self.controller.resume_main_flow and self.controller.resume_main_flow == Controller.FLOW__PSBT:
                    # Re-route us directly back to the start of the PSBT flow
                    self.controller.resume_main_flow = None
                    self.controller.psbt_seed = self.seed
                    return Destination(PSBTOverviewView, skip_current_view=True)

        button_data = []

        button_data.append(self.SCAN_PSBT)
        
        button_data.append(self.EXPORT_XPUB)

        button_data.append(self.EXPLORER)
        button_data.append(self.BACKUP)

        if self.settings.get_value(SettingsConstants.SETTING__MESSAGE_SIGNING) == SettingsConstants.OPTION__ENABLED:
            button_data.append(self.SIGN_MESSAGE)
        
        if self.settings.get_value(SettingsConstants.SETTING__BIP85_CHILD_SEEDS) == SettingsConstants.OPTION__ENABLED and self.seed.bip85_supported:
            button_data.append(self.BIP85_CHILD_SEED)

        # Follow the existing passphrase setting, including Required. Keep the
        # neutral label near the bottom as discussed in #419.
        if (not isinstance(self.seed, ElectrumSeed)
                and self.settings.get_value(SettingsConstants.SETTING__PASSPHRASE) != SettingsConstants.OPTION__DISABLED):
            button_data.append(self.PASSPHRASE)

        button_data.append(self.DISCARD)

        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
        checked_button_colors = {}
        selected_checked_button_colors = {}
        for index, option in enumerate(button_data):
            if option == self.BIP85_CHILD_SEED and self.seed.is_bip85_child:
                checked_button_colors[index] = GUIConstants.BIP85_COLOR
                selected_checked_button_colors[index] = GUIConstants.BIP85_COLOR_SELECTED
            elif option == self.PASSPHRASE and self.seed.has_passphrase:
                checked_button_colors[index] = GUIConstants.PASSPHRASE_COLOR
                selected_checked_button_colors[index] = GUIConstants.PASSPHRASE_COLOR_SELECTED
        
        selected_menu_num = self.run_screen(
            seed_screens.SeedOptionsScreen,
            button_data=button_data,
            fingerprint=self.seed.get_fingerprint(network),
            fingerprint_without=(self.seed.get_fingerprint_without_passphrase(network)
                                 if self.seed.has_passphrase else None),
            fingerprint_parent=self.seed.bip85_parent_fingerprint,
            checked_button_indices=list(checked_button_colors),
            checked_button_colors=checked_button_colors,
            selected_checked_button_colors=selected_checked_button_colors,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            # Leaving a wallet still clears its workflow state, even when we
            # return to the seed list instead of passing through Home.
            self.controller.clear_wallet_state()
            return Destination(SeedsMenuView, clear_history=True)

        if button_data[selected_menu_num] == self.SCAN_PSBT:
            from seedsigner.views.scan_views import ScanPSBTView
            self.controller.psbt_seed = self.seed
            return Destination(ScanPSBTView)

        elif button_data[selected_menu_num] == self.EXPORT_XPUB:
            return Destination(SeedExportXpubSigTypeView, view_args=dict(seed=self.seed))

        elif button_data[selected_menu_num] == self.EXPLORER:
            self.controller.resume_main_flow = Controller.FLOW__ADDRESS_EXPLORER
            return Destination(SeedExportXpubScriptTypeView, view_args=dict(seed=self.seed, sig_type=SettingsConstants.SINGLE_SIG))

        elif button_data[selected_menu_num] == self.SIGN_MESSAGE:
            from seedsigner.views.scan_views import ScanView
            self.controller.sign_message_data = dict(seed=self.seed)
            self.controller.resume_main_flow = Controller.FLOW__SIGN_MESSAGE
            return Destination(ScanView)

        elif button_data[selected_menu_num] == self.BACKUP:
            return Destination(SeedBackupView, view_args=dict(seed=self.seed))

        elif button_data[selected_menu_num] == self.BIP85_CHILD_SEED:
            return Destination(SeedBIP85ChildMenuView if self.seed.is_bip85_child else SeedBIP85SelectNumWordsView,
                               view_args={"seed": self.seed})

        elif button_data[selected_menu_num] == self.PASSPHRASE:
            return Destination(SeedPassphraseMenuView, view_args={"seed": self.seed})

        elif button_data[selected_menu_num] == self.DISCARD:
            return Destination(SeedDiscardView, view_args=dict(seed=self.seed))



class SeedBackupView(View):
    VIEW_WORDS = ButtonOption("View seed words")
    EXPORT_SEEDQR = ButtonOption("Export as SeedQR")

    def __init__(self, seed: Seed):
        super().__init__()
        self.seed = seed
    

    def run(self):
        button_data = [self.VIEW_WORDS]

        if self.seed.seedqr_supported:
            button_data.append(self.EXPORT_SEEDQR)

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title=_("Backup Seed"),
            button_data=button_data,
            is_bottom_list=True,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        elif button_data[selected_menu_num] == self.VIEW_WORDS:
            return Destination(SeedWordsWarningView, view_args={"seed": self.seed})

        elif button_data[selected_menu_num] == self.EXPORT_SEEDQR:
            return Destination(SeedTranscribeSeedQRFormatView, view_args={"seed": self.seed})



"""****************************************************************************
    Export Xpub flow
****************************************************************************"""
class SeedExportXpubSigTypeView(View):
    SINGLE_SIG = ButtonOption("Single Sig", return_data=SettingsConstants.SINGLE_SIG)
    MULTISIG = ButtonOption("Multisig", return_data=SettingsConstants.MULTISIG)

    def __init__(self, seed: Seed):
        super().__init__()
        self.seed = seed


    def run(self):
        if len(self.settings.get_value(SettingsConstants.SETTING__SIG_TYPES)) == 1:
            # Nothing to select; skip this screen
            return Destination(SeedExportXpubScriptTypeView, view_args={"seed": self.seed, "sig_type": self.settings.get_value(SettingsConstants.SETTING__SIG_TYPES)[0]}, skip_current_view=True)

        button_data = [self.SINGLE_SIG, self.MULTISIG]

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title=_("Export Xpub"),
            button_data=button_data
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        return Destination(SeedExportXpubScriptTypeView, view_args={"seed": self.seed, "sig_type": button_data[selected_menu_num].return_data})



class SeedExportXpubScriptTypeView(View):
    def __init__(self, seed: Seed, sig_type: str):
        super().__init__()
        self.seed = seed
        self.sig_type = sig_type


    def run(self):
        from seedsigner.controller import Controller
        from .tools_views import ToolsAddressExplorerAddressTypeView
        args = {"seed": self.seed, "sig_type": self.sig_type}

        script_types = self.settings.get_value(SettingsConstants.SETTING__SCRIPT_TYPES)

        if self.seed.script_override:
            # This seed only allows one script type
            # TODO: Does it matter if the Settings don't have the override script type
            # enabled?
            script_types = [self.seed.script_override]

        if len(script_types) == 1:
            # Nothing to select; skip this screen
            args["script_type"] = script_types[0]

            if self.controller.resume_main_flow == Controller.FLOW__ADDRESS_EXPLORER:
                del args["sig_type"]
                return Destination(ToolsAddressExplorerAddressTypeView, view_args=args, skip_current_view=True)
            else:
                return Destination(SeedExportXpubQRFormatView, view_args=args, skip_current_view=True)
        
        title = _("Export Xpub")
        if self.controller.resume_main_flow == Controller.FLOW__ADDRESS_EXPLORER:
            title = _("Address Explorer")

        button_data = []
        for script_type, display_name in SettingsConstants.ALL_SCRIPT_TYPES:
            if script_type in self.settings.get_value(SettingsConstants.SETTING__SCRIPT_TYPES):
                button_data.append(ButtonOption(display_name, return_data=script_type))

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title=title,
            is_button_text_centered=False,
            button_data=button_data,
            is_bottom_list=True,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            # If previous view is SeedOptionsView then that should be where resume_main_flow started (otherwise it would have been skipped).
            if len(self.controller.back_stack) >= 2 and self.controller.back_stack[-2].View_cls == SeedOptionsView:
                self.controller.resume_main_flow = None
            return Destination(BackStackView)

        else:
            args["script_type"] = button_data[selected_menu_num].return_data

            if args["script_type"] == SettingsConstants.CUSTOM_DERIVATION:
                return Destination(SeedExportXpubCustomDerivationView, view_args=args)

            if self.controller.resume_main_flow == Controller.FLOW__ADDRESS_EXPLORER:
                del args["sig_type"]
                return Destination(ToolsAddressExplorerAddressTypeView, view_args=args)
            else:
                return Destination(SeedExportXpubQRFormatView, view_args=args)



class SeedExportXpubCustomDerivationView(View):
    def __init__(self, seed: Seed, sig_type: str, script_type: str):
        super().__init__()
        self.seed = seed
        self.sig_type = sig_type
        self.script_type = script_type
        self.custom_derivation_path = "m/"


    def run(self):
        from seedsigner.controller import Controller
        ret = self.run_screen(
            seed_screens.SeedExportXpubCustomDerivationScreen,
            initial_value=self.custom_derivation_path,
        )

        if ret == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        
        # ret will be the custom derivation path
        custom_derivation = ret

        if self.controller.resume_main_flow == Controller.FLOW__ADDRESS_EXPLORER:
            from .tools_views import ToolsAddressExplorerAddressTypeView
            return Destination(ToolsAddressExplorerAddressTypeView, view_args=dict(seed=self.seed, script_type=self.script_type, custom_derivation=custom_derivation))

        return Destination(
            SeedExportXpubQRFormatView,
            view_args={
                "seed": self.seed,
                "sig_type": self.sig_type,
                "script_type": self.script_type,
                "custom_derivation": custom_derivation,
            }
        )



class SeedExportXpubQRFormatView(View):
    def __init__(self, seed: Seed, sig_type: str, script_type: str, custom_derivation: str = None):
        super().__init__()
        self.seed = seed
        self.sig_type = sig_type
        self.script_type = script_type
        self.custom_derivation = custom_derivation


    def run(self):
        args = {
            "seed": self.seed,
            "sig_type": self.sig_type,
            "script_type": self.script_type,
            "custom_derivation": self.custom_derivation,
        }
        if len(self.settings.get_value(SettingsConstants.SETTING__XPUB_QR_FORMAT)) == 1:
            # Nothing to select; skip this screen
            args["xpub_qr_format"] = self.settings.get_value(SettingsConstants.SETTING__XPUB_QR_FORMAT)[0]
            return Destination(SeedExportXpubWarningView, view_args=args, skip_current_view=True)

        button_data = []
        for display_name, setting_option in zip(self.settings.get_multiselect_value_display_names(SettingsConstants.SETTING__XPUB_QR_FORMAT), self.settings.get_value(SettingsConstants.SETTING__XPUB_QR_FORMAT)):
            button_data.append(ButtonOption(display_name, return_data=setting_option))

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title=_("Xpub QR Format"),
            is_button_text_centered=False,
            button_data=button_data,
            is_bottom_list=True,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        args["xpub_qr_format"] = button_data[selected_menu_num].return_data

        return Destination(SeedExportXpubWarningView, view_args=args)



class SeedExportXpubWarningView(View):
    def __init__(self, seed: Seed, sig_type: str, script_type: str, xpub_qr_format: str, custom_derivation: str):
        super().__init__()
        self.seed = seed
        self.sig_type = sig_type
        self.script_type = script_type
        self.xpub_qr_format = xpub_qr_format
        self.custom_derivation = custom_derivation


    def run(self):
        destination = Destination(
            SeedExportXpubDetailsView,
            view_args={
                "seed": self.seed,
                "sig_type": self.sig_type,
                "script_type": self.script_type,
                "xpub_qr_format": self.xpub_qr_format,
                "custom_derivation": self.custom_derivation,
            },
            skip_current_view=True,  # Prevent going BACK to WarningViews
        )

        if self.settings.get_value(SettingsConstants.SETTING__PRIVACY_WARNINGS) == SettingsConstants.OPTION__DISABLED:
            # Skip the WarningView entirely
            return destination

        selected_menu_num = self.run_screen(
            WarningScreen,
            status_headline=_("Privacy Leak!"),
            text=_("Xpub can be used to view all future transactions."),
        )

        if selected_menu_num == 0:
            # User clicked "I Understand"
            return destination

        elif selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)



class SeedExportXpubDetailsView(View):
    """
        Collects the user input from all the previous screens leading up to this and
        finally calculates the xpub and displays the summary view to the user.
    """
    def __init__(self, seed: Seed, sig_type: str, script_type: str, xpub_qr_format: str, custom_derivation: str):
        super().__init__()
        self.sig_type = sig_type
        self.script_type = script_type
        self.xpub_qr_format = xpub_qr_format
        self.custom_derivation = custom_derivation
        
        self.seed = seed


    def run(self):
        seed_derivation_override = self.seed.derivation_override(self.sig_type)
        if self.script_type == SettingsConstants.CUSTOM_DERIVATION:
            derivation_path = self.custom_derivation
        elif seed_derivation_override:
            derivation_path = seed_derivation_override
        else:
            from seedsigner.helpers import embit_utils
            derivation_path = embit_utils.get_standard_derivation_path(
                network=self.settings.get_value(SettingsConstants.SETTING__NETWORK),
                wallet_type=self.sig_type,
                script_type=self.script_type
            )

        if self.settings.get_value(SettingsConstants.SETTING__XPUB_DETAILS) == SettingsConstants.OPTION__DISABLED:
            # We're just skipping right past this screen
            selected_menu_num = 0

        else:
            # The derivation calc takes a few moments. Run the loading screen while we wait.
            from seedsigner.gui.screens.screen import LoadingScreenThread
            self.loading_screen = LoadingScreenThread(text=_("Generating xpub..."))
            self.loading_screen.start()

            try:
                from embit.bip32 import HDKey
                from embit.networks import NETWORKS
                embit_network = NETWORKS[SettingsConstants.map_network_to_embit(self.settings.get_value(SettingsConstants.SETTING__NETWORK))]
                version = self.seed.detect_version(
                    derivation_path,
                    self.settings.get_value(SettingsConstants.SETTING__NETWORK),
                    self.sig_type
                )
                root = HDKey.from_seed(
                    self.seed.seed_bytes,
                    version=embit_network["xprv"]
                )
                fingerprint = hexlify(root.child(0).fingerprint).decode('utf-8')
                xprv = root.derive(derivation_path)
                xpub = xprv.to_public()
                xpub_base58 = xpub.to_string(version=version)

            finally:
                self.loading_screen.stop()

            selected_menu_num = self.run_screen(
                seed_screens.SeedExportXpubDetailsScreen,
                fingerprint=fingerprint,
                derivation_path=derivation_path,
                xpub=xpub_base58,
            )

        if selected_menu_num == 0:
            return Destination(
                SeedExportXpubQRDisplayView,
                dict(seed=self.seed,
                     xpub_qr_format=self.xpub_qr_format,
                     derivation_path=derivation_path,
                     sig_type=self.sig_type
                )
            )

        elif selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)



class SeedExportXpubQRDisplayView(View):
    def __init__(self, seed: Seed, xpub_qr_format: str, derivation_path: str, sig_type: str = SettingsConstants.SINGLE_SIG):
        super().__init__()
        self.seed = seed

        encoder_args = dict(
            seed=self.seed,
            derivation=derivation_path,
            network=self.settings.get_value(SettingsConstants.SETTING__NETWORK),
            qr_density=self.settings.get_value(SettingsConstants.SETTING__QR_DENSITY),
            sig_type=sig_type
        )

        if xpub_qr_format == SettingsConstants.XPUB_QR_FORMAT__STATIC:
            self.qr_encoder = StaticXpubQrEncoder(**encoder_args)

        elif xpub_qr_format == SettingsConstants.XPUB_QR_FORMAT__SPECTER_LEGACY:
            self.qr_encoder = SpecterLegacyXPubQrEncoder(**encoder_args)

        else:
            # Default: UR crypto-address
            self.qr_encoder = UrXpubQrEncoder(**encoder_args)


    def run(self):
        from seedsigner.gui.screens.screen import QRDisplayScreen
        self.run_screen(
            QRDisplayScreen,
            qr_encoder=self.qr_encoder
        )

        return Destination(MainMenuView)



"""****************************************************************************
    View Seed Words flow
****************************************************************************"""
class SeedWordsWarningView(View):
    def __init__(self, seed: Seed, bip85_data: dict = None):
        super().__init__()
        self.seed = seed
        self.bip85_data = bip85_data


    def run(self):
        destination = Destination(
            SeedWordsView,
            view_args=dict(
                seed=self.seed,
                page_index=0,
                bip85_data=self.bip85_data
            ),
            skip_current_view=True,  # Prevent going BACK to WarningViews
        )
        if self.settings.get_value(SettingsConstants.SETTING__DIRE_WARNINGS) == SettingsConstants.OPTION__DISABLED:
            # Forward straight to showing the words
            return destination

        selected_menu_num = self.run_screen(
            DireWarningScreen,
            text=_("You must keep your seed words private & away from all online devices."),
        )

        if selected_menu_num == 0:
            # User clicked "I Understand"
            return destination

        elif selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)



class SeedWordsView(View):
    NEXT = ButtonOption("Next")
    DONE = ButtonOption("Done")

    def __init__(self, seed: Seed, bip85_data: dict = None, page_index: int = 0):
        super().__init__()
        if seed is None:
            self.is_pending_seed = True
            self.seed = self.controller.storage.get_pending_seed()
        else:
            self.is_pending_seed = False
            self.seed = seed
        self.bip85_data = bip85_data
        self.page_index = page_index


    def run(self):
        words_per_page = 4
        identity_kwargs = {}

        if self.bip85_data is not None:
            mnemonic = self.seed.get_bip85_child_mnemonic(self.bip85_data["child_index"], self.bip85_data["num_words"]).split()
            # Leave room for the parent -> child identity and child/page context.
            words_per_page = 3
            network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
            identity_kwargs = dict(
                fingerprint_parent=self.seed.get_fingerprint(network),
                fingerprint_child=Seed(mnemonic).get_fingerprint(network),
                child_index=self.bip85_data["child_index"],
            )
            # TRANSLATOR_NOTE: Inserts the child index (e.g. "Child #0")
            title = _("Child #{}").format(self.bip85_data["child_index"])
        else:
            mnemonic = self.seed.mnemonic_display_list
            title = _("Seed Words")
        words = mnemonic[self.page_index*words_per_page:(self.page_index + 1)*words_per_page]

        button_data = []
        num_pages = int(len(mnemonic)/words_per_page)
        if self.page_index < num_pages - 1 or self.is_pending_seed:
            button_data.append(self.NEXT)
        else:
            button_data.append(self.DONE)

        selected_menu_num = self.run_screen(
            seed_screens.SeedWordsScreen,
            title=f"{title}: {self.page_index+1}/{num_pages}",
            words=words,
            page_index=self.page_index,
            num_pages=num_pages,
            button_data=button_data,
            **identity_kwargs,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        if self.is_pending_seed:
            self.seed = None # Set to None for next View to know it's a pending seed

        if button_data[selected_menu_num] == self.NEXT:
            if self.is_pending_seed and self.page_index == num_pages - 1:
                return Destination(
                    SeedWordsBackupTestPromptView,
                    view_args=dict(seed=self.seed, bip85_data=self.bip85_data),
                )
            else:
                return Destination(
                    SeedWordsView,
                    view_args=dict(seed=self.seed, page_index=self.page_index + 1, bip85_data=self.bip85_data)
                )

        elif button_data[selected_menu_num] == self.DONE:
            # Must clear history to avoid BACK button returning to private info
            return Destination(
                SeedWordsBackupTestPromptView,
                view_args=dict(seed=self.seed, bip85_data=self.bip85_data),
            )



"""****************************************************************************
    BIP-85 - Derive child mnemonic (seed) flow (Application number 39')
****************************************************************************"""
def _bip85_change_redirect(view, child: Seed, parent: Seed = None):
    """Reject stale index-change flows without holding a hidden parent secret."""
    storage = view.controller.storage
    if not any(loaded is child for loaded in storage.seeds):
        return Destination(SeedsMenuView, clear_history=True)
    if (not child.bip85_supported
            or view.settings.get_value(SettingsConstants.SETTING__BIP85_CHILD_SEEDS) != SettingsConstants.OPTION__ENABLED):
        return Destination(SeedOptionsView, view_args=dict(seed=child), clear_history=True)
    missing_origin = not storage.has_complete_bip85_origin(child)
    verified_parent = storage.get_bip85_parent(child)
    if missing_origin or verified_parent is None or (parent is not None and verified_parent is not parent):
        return Destination(SeedBIP85ParentUnavailableView,
                           view_args=dict(seed=child, missing_origin=missing_origin), clear_history=True)
    return None


class SeedBIP85ChildMenuView(View):
    CHANGE_INDEX = ButtonOption("Change child index")
    DERIVE_CHILD = ButtonOption("Derive new child")

    def __init__(self, seed: Seed):
        super().__init__()
        self.seed = seed
        if not any(loaded is seed for loaded in self.controller.storage.seeds):
            self.set_redirect(Destination(SeedsMenuView, clear_history=True))
        elif (not seed.bip85_supported
                or self.settings.get_value(SettingsConstants.SETTING__BIP85_CHILD_SEEDS) != SettingsConstants.OPTION__ENABLED):
            self.set_redirect(Destination(SeedOptionsView, view_args=dict(seed=seed), clear_history=True))
        elif not seed.is_bip85_child:
            self.set_redirect(Destination(SeedBIP85SelectNumWordsView, view_args=dict(seed=seed)))

    def run(self):
        button_data = [self.CHANGE_INDEX, self.DERIVE_CHILD]
        known_origin = self.controller.storage.has_complete_bip85_origin(self.seed)
        selected = self.run_screen(
            seed_screens.SeedBIP85ChildMenuScreen,
            child_index=self.seed.bip85_child_index if known_origin else None,
            num_words=self.seed.bip85_num_words if known_origin else None,
            button_data=button_data,
        )
        if selected == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        if button_data[selected] == self.DERIVE_CHILD:
            # This wallet, including its own passphrase, becomes the new parent.
            return Destination(SeedBIP85SelectNumWordsView, view_args=dict(seed=self.seed))
        unavailable = _bip85_change_redirect(self, self.seed)
        if unavailable:
            return unavailable
        return Destination(SeedBIP85SelectChildIndexView, view_args=dict(
            seed=self.controller.storage.get_bip85_parent(self.seed),
            num_words=self.seed.bip85_num_words, change_from_seed=self.seed))


class SeedBIP85ParentUnavailableView(View):
    def __init__(self, seed: Seed, missing_origin: bool = False):
        super().__init__()
        self.seed = seed
        self.missing_origin = missing_origin

    def run(self):
        self.run_screen(
            WarningScreen,
            title=_("Origin Unavailable") if self.missing_origin else _("Parent Needed"),
            status_headline=None,
            text=(_("Derive this child again from its original parent to change its index.")
                  if self.missing_origin else
                  _("Load the original parent with its original passphrase to change this child's index.")),
            button_data=[ButtonOption("OK")], show_back_button=False,
        )
        return Destination(SeedOptionsView, view_args=dict(seed=self.seed), clear_history=True)


class SeedBIP85DerivationView(View):
    """Carry an optional sibling replacement through the ordinary backup flow."""
    def __init__(self, seed: Seed, num_words: int, change_from_seed: Seed = None):
        super().__init__()
        self.seed = seed
        self.num_words = num_words
        self.change_from_seed = change_from_seed
        if change_from_seed is not None:
            unavailable = _bip85_change_redirect(self, change_from_seed, seed)
            if unavailable:
                self.set_redirect(unavailable)

    def derivation_args(self, **kwargs):
        args = dict(seed=self.seed, num_words=self.num_words, **kwargs)
        if self.change_from_seed is not None:
            args["change_from_seed"] = self.change_from_seed
        return args


class SeedBIP85SelectNumWordsView(View):
    WORDS_12 = ButtonOption("12 Words")
    WORDS_24 = ButtonOption("24 Words")

    def __init__(self, seed: Seed):
        super().__init__()
        self.seed = seed
        self.num_words = 0


    def run(self):
        button_data = [self.WORDS_12, self.WORDS_24]

        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title=_("BIP-85 Num Words"),
            button_data=button_data
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        if button_data[selected_menu_num] == self.WORDS_12:
            self.num_words = 12
        elif button_data[selected_menu_num] == self.WORDS_24:
            self.num_words = 24

        return Destination(
            SeedBIP85SelectChildIndexView,
            view_args=dict(seed=self.seed, num_words=self.num_words)
        )



class SeedBIP85SelectChildIndexView(SeedBIP85DerivationView):
    # View to retrieve the derived seed index
    def run(self):
        # TODO: Change this later to use the generic Screen input keyboard
        screen_args = (dict(initial_index=self.change_from_seed.bip85_child_index)
                       if self.change_from_seed is not None else {})
        ret = self.run_screen(seed_screens.SeedBIP85SelectChildIndexScreen, **screen_args)

        if ret == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        try:
            child_index = int(ret)
        except (ValueError, TypeError):
            child_index = -1
        if not 0 <= child_index < 2**31:
            return Destination(
                SeedBIP85InvalidChildIndexView,
                view_args=self.derivation_args(),
                skip_current_view=True
            )

        if self.change_from_seed is not None and child_index == self.change_from_seed.bip85_child_index:
            # Keeping the same path must also keep the current child's passphrase.
            return Destination(SeedOptionsView, view_args=dict(seed=self.change_from_seed), clear_history=True)

        return Destination(
            SeedBIP85ReviewView,
            view_args=self.derivation_args(child_index=child_index)
        )



class SeedBIP85ReviewView(SeedBIP85DerivationView):
    VIEW_WORDS = ButtonOption("View seed words")

    def __init__(self, seed: Seed, num_words: int, child_index: int, change_from_seed: Seed = None):
        super().__init__(seed, num_words, change_from_seed)
        self.child_index = child_index


    def run(self):
        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
        child = Seed(self.seed.get_bip85_child_mnemonic(self.child_index, self.num_words).split())
        selected_menu_num = self.run_screen(
            seed_screens.SeedBIP85ReviewScreen,
            # The deriving parent includes its current passphrase. The new child
            # identity is the derived mnemonic with no passphrase of its own.
            fingerprint_parent=self.seed.get_fingerprint(network),
            fingerprint_child=child.get_fingerprint(network),
            child_index=self.child_index,
            num_words=self.num_words,
            button_data=[self.VIEW_WORDS],
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        bip85_data = dict(child_index=self.child_index, num_words=self.num_words)
        if self.change_from_seed is not None:
            bip85_data["change_from_seed"] = self.change_from_seed
        return Destination(
            SeedWordsWarningView,
            view_args=dict(
                seed=self.seed,
                bip85_data=bip85_data,
            ),
        )



class SeedBIP85InvalidChildIndexView(SeedBIP85DerivationView):
    def run(self):
        self.run_screen(
            DireWarningScreen,
            title=_("BIP-85 Index Error"),
            show_back_button=False,
            status_icon_name=SeedSignerIconConstants.ERROR,
            status_headline=_("Invalid Child Index"),
            text=_("BIP-85 Child Index must be between 0 and 2^31-1."),
            button_data=[ButtonOption("Try again")]
        )

        return Destination(
                SeedBIP85SelectChildIndexView,
                view_args=self.derivation_args(),
                skip_current_view=True
            )



class SeedBIP85LoadChildView(SeedBIP85DerivationView):
    def __init__(self, seed: Seed, num_words: int, child_index: int, change_from_seed: Seed = None):
        super().__init__(seed, num_words, change_from_seed)
        self.child_index = child_index


    def run(self):
        # The parent's passphrase participates in derivation, but is not inherited
        # by the child. Subsequent menu actions must target this independent Seed.
        child = Seed(self.seed.get_bip85_child_mnemonic(self.child_index, self.num_words).split(),
                     is_bip85_child=True,
                     bip85_parent_fingerprint=self.seed.get_fingerprint(
                         self.settings.get_value(SettingsConstants.SETTING__NETWORK)),
                     bip85_child_index=self.child_index, bip85_num_words=self.num_words)
        if self.change_from_seed is not None:
            # The original child stays loaded until the final explicit choice.
            # Skip this screenless transition so Back returns to the backup page.
            return Destination(SeedBIP85SaveChildView,
                               view_args=dict(seed=self.change_from_seed, parent=self.seed, candidate=child),
                               skip_current_view=True)
        child = self.controller.load_seed(child)
        return Destination(SeedOptionsView, view_args=dict(seed=child), clear_history=True)


class SeedBIP85SaveChildView(View):
    REPLACE = ButtonOption("Replace current")
    LOAD_SEPARATELY = ButtonOption("Load separately")
    CANCEL = ButtonOption("Cancel")

    def __init__(self, seed: Seed, parent: Seed, candidate: Seed):
        super().__init__()
        self.seed = seed
        self.parent = parent
        self.candidate = candidate
        unavailable = self.validate_change()
        if unavailable:
            self.set_redirect(unavailable)

    def validate_change(self):
        unavailable = _bip85_change_redirect(self, self.seed, self.parent)
        if unavailable:
            return unavailable
        # Check the exact candidate too: a fingerprint is a visual cue, not proof
        # of its derivation. A sibling starts without a passphrase of its own.
        if (self.candidate.has_passphrase
                or self.candidate.bip85_num_words != self.seed.bip85_num_words
                or self.controller.storage.get_bip85_parent(self.candidate) is not self.parent):
            return Destination(SeedBIP85ChildMenuView, view_args=dict(seed=self.seed), clear_history=True)
        return None

    def run(self):
        button_data = [self.REPLACE, self.LOAD_SEPARATELY, self.CANCEL]
        network = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
        selected = self.run_screen(
            seed_screens.SeedBIP85SaveChildScreen,
            fingerprint_parent=self.parent.get_fingerprint(network),
            fingerprint_new=self.candidate.get_fingerprint(network),
            fingerprint_current=self.seed.get_fingerprint(network),
            button_data=button_data, selected_button=0,
        )
        if selected == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        if button_data[selected] == self.CANCEL:
            return Destination(SeedOptionsView, view_args=dict(seed=self.seed), clear_history=True)
        unavailable = self.validate_change()
        if unavailable:
            return unavailable
        if button_data[selected] == self.LOAD_SEPARATELY:
            child = self.controller.load_seed(self.candidate)
        else:
            child = self.controller.replace_seed(self.seed, self.candidate)
        return Destination(SeedOptionsView, view_args=dict(seed=child), clear_history=True)



"""****************************************************************************
    Seed Words Backup Test
****************************************************************************"""
def _finish_bip85_backup(view):
    """Forget the derived backup pages without loading or replacing any seed."""
    seed = view.bip85_data.get("change_from_seed", view.seed)
    if any(loaded is seed for loaded in view.controller.storage.seeds):
        return Destination(SeedOptionsView, view_args=dict(seed=seed), clear_history=True)
    # A stale backup screen must not return to a wallet that has been removed.
    return Destination(SeedsMenuView if view.controller.storage.seeds else MainMenuView,
                       clear_history=True)


class SeedWordsBackupTestPromptView(View):
    VERIFY = ButtonOption("Verify")
    SKIP = ButtonOption("Skip")
    VERIFY_CHILD = ButtonOption("Verify backup")
    LOAD_CHILD = ButtonOption("Load child")
    DONE_CHILD = ButtonOption("Done, don't load")

    def __init__(self, seed: Seed, bip85_data: dict = None):
        super().__init__()
        self.seed = seed
        self.bip85_data = bip85_data


    def run(self):
        button_data = ([self.VERIFY_CHILD, self.LOAD_CHILD, self.DONE_CHILD] if self.bip85_data is not None
                       else [self.VERIFY, self.SKIP])
        selected_menu_num = self.run_screen(
            seed_screens.SeedWordsBackupTestPromptScreen,
            button_data=button_data,
            is_bip85_child=self.bip85_data is not None,
        )

        if button_data[selected_menu_num] == self.DONE_CHILD:
            return _finish_bip85_backup(self)

        if button_data[selected_menu_num] in [self.VERIFY, self.VERIFY_CHILD]:
            return Destination(
                SeedWordsBackupTestView,
                view_args=dict(seed=self.seed, bip85_data=self.bip85_data),
            )

        elif button_data[selected_menu_num] in [self.SKIP, self.LOAD_CHILD]:
            if self.bip85_data is not None:
                return Destination(SeedBIP85LoadChildView,
                                   view_args=dict(seed=self.seed, **self.bip85_data))
            elif self.seed is None:
                return Destination(SeedFinalizeView)
            else:
                return Destination(SeedOptionsView, view_args=dict(seed=self.seed))



class SeedWordsBackupTestView(View):
    def __init__(self, seed: Seed, bip85_data: dict = None, confirmed_list: list[bool] = None, cur_index: int = None, rand_seed: int = None):
        """
        Note: `rand_seed` is ONLY USED BY THE SCREENSHOT GENERATOR!!! (to ensure
        consistent screenshot results).
        """
        super().__init__()
        if seed is None:
            self.is_pending_seed = True
            self.seed = self.controller.storage.get_pending_seed()
        else:
            self.is_pending_seed = False
            self.seed = seed
        self.bip85_data = bip85_data

        if self.bip85_data is not None:
            self.mnemonic_list = self.seed.get_bip85_child_mnemonic(self.bip85_data["child_index"], self.bip85_data["num_words"]).split()
        else:
            self.mnemonic_list = self.seed.mnemonic_display_list

        self.confirmed_list = confirmed_list
        if not self.confirmed_list:
            self.confirmed_list = []

        self.cur_index = cur_index
        self.rand_seed = rand_seed


    def run(self):
        from embit import bip39

        if self.rand_seed is not None:
            random.seed(self.rand_seed + self.cur_index if self.cur_index is not None else 0)

        if self.cur_index is None:
            self.cur_index = int(random.random() * len(self.mnemonic_list))
            while self.cur_index in self.confirmed_list:
                self.cur_index = int(random.random() * len(self.mnemonic_list))

        real_word = ButtonOptionWithoutTranslation(self.mnemonic_list[self.cur_index])
        fake_word1 = ButtonOptionWithoutTranslation(bip39.WORDLIST[int(random.random() * 2047)])
        fake_word2 = ButtonOptionWithoutTranslation(bip39.WORDLIST[int(random.random() * 2047)])
        fake_word3 = ButtonOptionWithoutTranslation(bip39.WORDLIST[int(random.random() * 2047)])

        button_data = [real_word, fake_word1, fake_word2, fake_word3]
        random.shuffle(button_data)

        # TRANSLATOR_NOTE: Inserts the word number (e.g. "Verify Word #1")
        title = _("Verify Word #{}").format(self.cur_index + 1)
        selected_menu_num = self.run_screen(
            ButtonListScreen,
            title=title,
            show_back_button=False,
            button_data=button_data,
            is_bottom_list=True,
            is_button_text_centered=True,
        )

        if self.is_pending_seed:
            self.seed = None # Set to None for next View to know it's a pending seed

        if button_data[selected_menu_num] == real_word:
            self.confirmed_list.append(self.cur_index)
            if len(self.confirmed_list) == len(self.mnemonic_list):
                # Successfully confirmed the full mnemonic!
                return Destination(
                    SeedWordsBackupTestSuccessView,
                    view_args=dict(seed=self.seed, bip85_data=self.bip85_data),
                )
            else:
                # Continue testing the remaining words
                return Destination(
                    SeedWordsBackupTestView,
                    view_args=dict(seed=self.seed, confirmed_list=self.confirmed_list, bip85_data=self.bip85_data),
                )

        else:
            # Picked the WRONG WORD!
            return Destination(
                SeedWordsBackupTestMistakeView,
                view_args=dict(
                    seed=self.seed,
                    bip85_data=self.bip85_data,
                    cur_index=self.cur_index,
                    wrong_word=button_data[selected_menu_num].button_label,
                    confirmed_list=self.confirmed_list,
                )
            )



class SeedWordsBackupTestMistakeView(View):
    REVIEW = ButtonOption("Review seed words")
    RETRY = ButtonOption("Try again")

    def __init__(self, seed: Seed, bip85_data: dict = None, cur_index: int = None, wrong_word: str = None, confirmed_list: list[bool] = None):
        super().__init__()
        self.seed = seed
        self.bip85_data = bip85_data
        self.cur_index = cur_index
        self.wrong_word = wrong_word
        self.confirmed_list = confirmed_list


    def run(self):
        button_data = [self.REVIEW, self.RETRY]

        # TRANSLATOR_NOTE: Inserts the word number and the word (e.g. "Word #1 is not "apple"!")
        text = _("Word #{} is not \"{}\"!").format(self.cur_index + 1, self.wrong_word)

        # TRANSLATOR_NOTE: User selected the wrong word during the mnemonic backup test (e.g. incorrectly said the 5th word was "zoo")
        status_headline = _("Wrong Word!")

        selected_menu_num = self.run_screen(
            DireWarningScreen,
            title=_("Verification Error"),
            show_back_button=False,
            status_icon_name=SeedSignerIconConstants.ERROR,
            status_headline=status_headline,
            button_data=button_data,
            text=text,
        )

        if button_data[selected_menu_num] == self.REVIEW:
            return Destination(
                SeedWordsView,
                view_args=dict(seed=self.seed, bip85_data=self.bip85_data),
            )

        elif button_data[selected_menu_num] == self.RETRY:
            return Destination(
                SeedWordsBackupTestView,
                view_args=dict(
                    seed=self.seed,
                    confirmed_list=self.confirmed_list,
                    cur_index=self.cur_index,
                    bip85_data=self.bip85_data,
                )
            )



class SeedWordsBackupTestSuccessView(View):
    LOAD_CHILD = SeedWordsBackupTestPromptView.LOAD_CHILD
    DONE_CHILD = SeedWordsBackupTestPromptView.DONE_CHILD

    def __init__(self, seed: Seed, bip85_data: dict = None):
        super().__init__()
        self.seed = seed
        self.bip85_data = bip85_data

    def run(self):
        from seedsigner.gui.screens.screen import LargeIconStatusScreen
        button_data = ([self.LOAD_CHILD, self.DONE_CHILD] if self.bip85_data is not None
                       else [ButtonOption("OK")])
        selected = self.run_screen(
            LargeIconStatusScreen,
            title=_("Backup Verified"),
            show_back_button=False,
            status_headline=_("Success!"),
            text=_("All words verified.") if self.bip85_data is not None else _("All mnemonic backup words were successfully verified!"),
            button_data=button_data,
        )

        if self.bip85_data is not None:
            if button_data[selected] == self.DONE_CHILD:
                return _finish_bip85_backup(self)
            return Destination(SeedBIP85LoadChildView,
                               view_args=dict(seed=self.seed, **self.bip85_data))
        elif self.seed is None:
            return Destination(SeedFinalizeView)
        else:
            return Destination(SeedOptionsView, view_args=dict(seed=self.seed), clear_history=True)



"""****************************************************************************
    Export as SeedQR
****************************************************************************"""
class SeedTranscribeSeedQRFormatView(View):
    # SeedQR dims for 12-word seeds
    STANDARD_12 = ButtonOption("Standard: 25x25", return_data=25)
    COMPACT_12 = ButtonOption("Compact: 21x21", return_data=21)

    # SeedQR dims for 24-word seeds
    STANDARD_24 = ButtonOption("Standard: 29x29", return_data=29)
    COMPACT_24 = ButtonOption("Compact: 25x25", return_data=25)

    def __init__(self, seed: Seed):
        super().__init__()
        self.seed = seed


    def run(self):

        if self.settings.get_value(SettingsConstants.SETTING__COMPACT_SEEDQR) != SettingsConstants.OPTION__ENABLED:
            # Only configured for standard SeedQR
            return Destination(
                SeedTranscribeSeedQRWarningView,
                view_args={
                    "seed": self.seed,
                    "seedqr_format": QRType.SEED__SEEDQR,
                    "num_modules": self.STANDARD_12.return_data,
                },
                skip_current_view=True,
            )

        if len(self.seed.mnemonic_list) == 12:
            button_data = [self.STANDARD_12, self.COMPACT_12]
        else:
            button_data = [self.STANDARD_24, self.COMPACT_24]

        selected_menu_num = self.run_screen(
            seed_screens.SeedTranscribeSeedQRFormatScreen,
            title=_("SeedQR Format"),
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        
        if button_data[selected_menu_num] in [self.STANDARD_12, self.STANDARD_24]:
            seedqr_format = QRType.SEED__SEEDQR
        else:
            seedqr_format = QRType.SEED__COMPACTSEEDQR

        num_modules = button_data[selected_menu_num].return_data
        
        return Destination(
            SeedTranscribeSeedQRWarningView,
                view_args={
                    "seed": self.seed,
                    "seedqr_format": seedqr_format,
                    "num_modules": num_modules,
                }
            )



class SeedTranscribeSeedQRWarningView(View):
    def __init__(self, seed: Seed, seedqr_format: str = QRType.SEED__SEEDQR, num_modules: int = 29):
        super().__init__()
        self.seed = seed
        self.seedqr_format = seedqr_format
        self.num_modules = num_modules
    

    def run(self):
        destination = Destination(
            SeedTranscribeSeedQRWholeQRView,
            view_args={
                "seed": self.seed,
                "seedqr_format": self.seedqr_format,
                "num_modules": self.num_modules,
            },
            skip_current_view=True,  # Prevent going BACK to WarningViews
        )

        if self.settings.get_value(SettingsConstants.SETTING__DIRE_WARNINGS) == SettingsConstants.OPTION__DISABLED:
            # Forward straight to transcribing the SeedQR
            return destination

        selected_menu_num = self.run_screen(
            DireWarningScreen,
            status_headline=_("SeedQR is your private key!"),
            text=_("Never photograph or scan it into a device that connects to the internet."),
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        else:
            # User clicked "I Understand"
            return destination
    


class SeedTranscribeSeedQRWholeQRView(View):
    def __init__(self, seed: Seed, seedqr_format: str, num_modules: int):
        super().__init__()
        self.seed = seed
        self.seedqr_format = seedqr_format
        self.num_modules = num_modules
    

    def run(self):
        encoder_args = dict(mnemonic=self.seed.mnemonic_list,
                            wordlist_language_code=self.settings.get_value(SettingsConstants.SETTING__WORDLIST_LANGUAGE))
        if self.seedqr_format == QRType.SEED__SEEDQR:
            e = SeedQrEncoder(**encoder_args)
        elif self.seedqr_format == QRType.SEED__COMPACTSEEDQR:
            e = CompactSeedQrEncoder(**encoder_args)

        data = e.next_part()

        ret = self.run_screen(
            seed_screens.SeedTranscribeSeedQRWholeQRScreen,
            qr_data=data,
            num_modules=self.num_modules,
        )

        if ret == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)
        
        else:
            return Destination(
                SeedTranscribeSeedQRZoomedInView,
                view_args={
                    "seed": self.seed,
                    "seedqr_format": self.seedqr_format
                }
            )



class SeedTranscribeSeedQRZoomedInView(View):
    """
    intial_zone_x, initial_zone_y: Used by the screenshot generator to shift the view
    to a more interesting part of the QR code template.
    """
    def __init__(self, seed: Seed, seedqr_format: str, initial_zone_x: int = 0, initial_zone_y: int = 0):
        super().__init__()
        self.seed = seed
        self.seedqr_format = seedqr_format
        self.initial_zone_x = initial_zone_x
        self.initial_zone_y = initial_zone_y
        self.is_screensaver_allowed = False


    def run(self):
        encoder_args = dict(mnemonic=self.seed.mnemonic_list,
                            wordlist_language_code=self.settings.get_value(SettingsConstants.SETTING__WORDLIST_LANGUAGE))
        if self.seedqr_format == QRType.SEED__SEEDQR:
            e = SeedQrEncoder(**encoder_args)
        elif self.seedqr_format == QRType.SEED__COMPACTSEEDQR:
            e = CompactSeedQrEncoder(**encoder_args)

        data = e.next_part()

        if len(self.seed.mnemonic_list) == 24:
            if self.seedqr_format == QRType.SEED__COMPACTSEEDQR:
                num_modules = 25
            else:
                num_modules = 29
        else:
            if self.seedqr_format == QRType.SEED__COMPACTSEEDQR:
                num_modules = 21
            else:
                num_modules = 25

        self.run_screen(
            seed_screens.SeedTranscribeSeedQRZoomedInScreen,
            qr_data=data,
            num_modules=num_modules,
            initial_zone_x=self.initial_zone_x,
            initial_zone_y=self.initial_zone_y,
        )

        return Destination(SeedTranscribeSeedQRConfirmQRPromptView, view_args={"seed": self.seed})



class SeedTranscribeSeedQRConfirmQRPromptView(View):
    SCAN = ButtonOption("Confirm SeedQR", SeedSignerIconConstants.QRCODE)
    DONE = ButtonOption("Done")

    def __init__(self, seed: Seed):
        super().__init__()
        self.seed = seed
    

    def run(self):
        button_data = [self.SCAN, self.DONE]

        selected_menu_option = self.run_screen(
            seed_screens.SeedTranscribeSeedQRConfirmQRPromptScreen,
            title=_("Confirm SeedQR?"),
            button_data=button_data,
        )

        if selected_menu_option == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        elif button_data[selected_menu_option] == self.SCAN:
            return Destination(SeedTranscribeSeedQRConfirmScanView, view_args={"seed": self.seed})

        elif button_data[selected_menu_option] == self.DONE:
            return Destination(SeedOptionsView, view_args={"seed": self.seed}, clear_history=True)



class SeedTranscribeSeedQRConfirmScanView(View):
    def __init__(self, seed: Seed):
        from seedsigner.models.decode_qr import DecodeQR
        super().__init__()
        self.seed = seed
        wordlist_language_code = self.settings.get_value(SettingsConstants.SETTING__WORDLIST_LANGUAGE)
        self.decoder = DecodeQR(wordlist_language_code=wordlist_language_code)

    def run(self):
        from seedsigner.gui.screens.scan_screens import ScanScreen

        # Run the live preview and QR code capture process
        # TODO: Does this belong in its own BaseThread?
        scanning_done=self.run_screen(
            ScanScreen,
            decoder=self.decoder,
            instructions_text=_("Scan your SeedQR")
        )

        # If the scanning was canceled because the back button was pressed, return to BackStackView (SeedTranscribeSeedQRConfirmQRPromptView).
        if scanning_done==False:
           return Destination(BackStackView, skip_current_view=False)

        if self.decoder.is_complete:
            if self.decoder.is_seed:
                seed_mnemonic = self.decoder.get_seed_phrase()
                # Found a valid mnemonic seed! But does it match?
                if seed_mnemonic != self.seed.mnemonic_list:
                    return Destination(SeedTranscribeSeedQRConfirmWrongSeedView, skip_current_view=True)
                else:
                    return Destination(SeedTranscribeSeedQRConfirmSuccessView, view_args={"seed": self.seed})

        # Will trigger if a different kind of QR code is scanned (non SeedQR)
        return Destination(SeedTranscribeSeedQRConfirmInvalidQRView, skip_current_view=True)



class SeedTranscribeSeedQRConfirmWrongSeedView(View):
    """
    A valid SeedQR was scanned but it did NOT match the one we just transcribed!
    """
    def run(self):
        self.run_screen(
            DireWarningScreen,
            title=_("Confirm SeedQR"),
            status_headline=_("Error!"),
            text=_("Your transcribed SeedQR does not match your original seed!"),
            show_back_button=False,
            button_data=[ButtonOption("Review SeedQR")],
        )

        # Skip BACK to the zoomed in transcription view
        return Destination(BackStackView, skip_current_view=True)



class SeedTranscribeSeedQRConfirmInvalidQRView(View):
    """
    A QR code was scanned but it was not a SeedQR and certainly not the SeedQR we just
    transcribed!
    """
    def run(self):
        # TODO: A better error message would be something like: "The QR code you scanned does not contain a valid SeedQR."
        self.run_screen(
            DireWarningScreen,
            title=_("Confirm SeedQR"),
            status_headline=_("Error!"),
            text=_("Your transcribed SeedQR could not be read!"),
            show_back_button=False,
            button_data=[ButtonOption("Review SeedQR")],
        )

        # Skip BACK to the zoomed in transcription view
        return Destination(BackStackView, skip_current_view=True)



class SeedTranscribeSeedQRConfirmSuccessView(View):
    """
    The SeedQR we just scanned matched the one we just transcribed.
    """
    def __init__(self, seed: Seed):
        super().__init__()
        self.seed = seed


    def run(self):
        from seedsigner.gui.screens.screen import LargeIconStatusScreen
        self.run_screen(
            LargeIconStatusScreen,
            title=_("Confirm SeedQR"),
            status_headline=_("Success!"),
            text=_("Your transcribed SeedQR successfully scanned and yielded the same seed."),
            show_back_button=False,
            button_data=[ButtonOption("OK")],
        )

        return Destination(SeedOptionsView, view_args={"seed": self.seed})



"""****************************************************************************
    Address verification
****************************************************************************"""
class AddressVerificationStartView(View):
    def __init__(self, address: str, script_type: str, network: str):
        super().__init__()
        self.controller.unverified_address = dict(
            address=address,
            script_type=script_type,
            network=network
        )


    def run(self):
        from seedsigner.helpers import embit_utils
        from seedsigner.controller import Controller

        if self.controller.unverified_address["script_type"] == SettingsConstants.LEGACY_P2PKH:
            # Legacy P2PKH addresses are always singlesig
            sig_type = SettingsConstants.SINGLE_SIG
            destination = Destination(SeedSelectSeedView, view_args=dict(flow=Controller.FLOW__VERIFY_SINGLESIG_ADDR), skip_current_view=True)

        if self.controller.unverified_address["script_type"] == SettingsConstants.NESTED_SEGWIT:
            # No way to differentiate single sig from multisig
            return Destination(AddressVerificationSigTypeView, skip_current_view=True)

        if self.controller.unverified_address["script_type"] == SettingsConstants.NATIVE_SEGWIT:
            if len(self.controller.unverified_address["address"]) >= 62:
                # Mainnet/testnet are 62, regtest is 64
                sig_type = SettingsConstants.MULTISIG
                if self.controller.multisig_wallet_descriptor:
                    # Can jump straight to the brute-force verification View
                    destination = Destination(SeedAddressVerificationView, skip_current_view=True)
                else:
                    self.controller.resume_main_flow = Controller.FLOW__VERIFY_MULTISIG_ADDR
                    destination = Destination(LoadMultisigWalletDescriptorView, skip_current_view=True)

            else:
                sig_type = SettingsConstants.SINGLE_SIG
                destination = Destination(SeedSelectSeedView, view_args=dict(flow=Controller.FLOW__VERIFY_SINGLESIG_ADDR), skip_current_view=True)

        elif self.controller.unverified_address["script_type"] == SettingsConstants.TAPROOT:
            sig_type = SettingsConstants.SINGLE_SIG
            destination = Destination(SeedSelectSeedView, view_args=dict(flow=Controller.FLOW__VERIFY_SINGLESIG_ADDR), skip_current_view=True)

        derivation_path = embit_utils.get_standard_derivation_path(
            network=self.controller.unverified_address["network"],
            wallet_type=sig_type,
            script_type=self.controller.unverified_address["script_type"]
        )

        self.controller.unverified_address["sig_type"] = sig_type
        self.controller.unverified_address["derivation_path"] = derivation_path

        return destination



class AddressVerificationSigTypeView(View):
    SINGLE_SIG = ButtonOption("Single Sig")
    MULTISIG = ButtonOption("Multisig")

    def run(self):
        from seedsigner.helpers import embit_utils
        from seedsigner.controller import Controller
        button_data = [self.SINGLE_SIG, self.MULTISIG]
        selected_menu_num = self.run_screen(
            seed_screens.AddressVerificationSigTypeScreen,
            title=_("Verify Address"),
            text=_("Sig type can't be auto-detected from this address. Please specify:"),
            button_data=button_data,
            is_bottom_list=True,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            self.controller.unverified_address = None
            return Destination(BackStackView)
        
        elif button_data[selected_menu_num] == self.SINGLE_SIG:
            sig_type = SettingsConstants.SINGLE_SIG
            destination = Destination(SeedSelectSeedView, view_args=dict(flow=Controller.FLOW__VERIFY_SINGLESIG_ADDR))

        elif button_data[selected_menu_num] == self.MULTISIG:
            sig_type = SettingsConstants.MULTISIG
            if self.controller.multisig_wallet_descriptor:
                destination = Destination(SeedAddressVerificationView)
            else:
                self.controller.resume_main_flow = Controller.FLOW__VERIFY_MULTISIG_ADDR
                destination = Destination(LoadMultisigWalletDescriptorView)

        self.controller.unverified_address["sig_type"] = sig_type
        derivation_path = embit_utils.get_standard_derivation_path(
            network=self.controller.unverified_address["network"],
            wallet_type=sig_type,
            script_type=self.controller.unverified_address["script_type"]
        )
        self.controller.unverified_address["derivation_path"] = derivation_path

        return destination



class SeedAddressVerificationView(View):
    """
        Creates a worker thread to brute-force calculate addresses. Writes its
        iteration status to a shared `ThreadsafeCounter`.

        The `ThreadsafeCounter` is sent to the display Screen which is monitored in
        its own `ProgressThread` to show the current iteration onscreen.

        Performs single sig verification on `seed` if specified, otherwise assumes
        multisig.
    """
    # TRANSLATOR_NOTE: Option when scanning for a matching address; skips ten addresses ahead
    SKIP_10 = ButtonOption("Skip 10")
    CANCEL = ButtonOption("Cancel")

    def __init__(self, seed: Seed = None):
        super().__init__()
        self.seed = seed
        self.is_multisig = self.controller.unverified_address["sig_type"] == SettingsConstants.MULTISIG
        self.seed_derivation_override = ""
        if not self.is_multisig:
            if self.seed is None:
                # Shouldn't be able to get here
                raise Exception("Can't validate a single sig addr without specifying a seed")
            self.seed_derivation_override = self.seed.derivation_override(sig_type=SettingsConstants.SINGLE_SIG)
        self.address = self.controller.unverified_address["address"]
        self.derivation_path = self.seed_derivation_override if self.seed_derivation_override else self.controller.unverified_address["derivation_path"]
        self.script_type = self.controller.unverified_address["script_type"]
        self.sig_type = self.controller.unverified_address["sig_type"]
        self.network = self.controller.unverified_address["network"]

        # TODO: This should be in `Seed` or `PSBT` utility class
        embit_network = SettingsConstants.map_network_to_embit(self.network)

        # The ThreadsafeCounter will be shared by the brute-force thread to keep track of
        # its current addr index number and the Screen to display its progress and
        # respond to UI requests to jump the index ahead.
        self.threadsafe_counter = ThreadsafeCounter()

        # Shared coordination var so the display thread can detect success
        self.verified_index = ThreadsafeCounter(initial_value=None)
        self.verified_index_is_change = ThreadsafeCounter(initial_value=None)

        # Create the brute-force calculation thread that will run in the background
        self.addr_verification_thread = self.BruteForceAddressVerificationThread(
            address=self.address,
            seed=None if self.is_multisig else self.seed,
            descriptor=self.controller.multisig_wallet_descriptor,
            script_type=self.script_type,
            embit_network=embit_network,
            derivation_path=self.derivation_path,
            threadsafe_counter=self.threadsafe_counter,
            verified_index=self.verified_index,
            verified_index_is_change=self.verified_index_is_change,
        )


    def run(self):
        # Start brute-force calculations from the zero-th index
        try:
            self.addr_verification_thread.start()

            button_data = [self.SKIP_10, self.CANCEL]

            script_type_settings_entry = SettingsDefinition.get_settings_entry(SettingsConstants.SETTING__SCRIPT_TYPES)
            script_type_display = script_type_settings_entry.get_selection_option_display_name_by_value(self.script_type)

            sig_type_settings_entry = SettingsDefinition.get_settings_entry(SettingsConstants.SETTING__SIG_TYPES)
            sig_type_display = sig_type_settings_entry.get_selection_option_display_name_by_value(self.sig_type)

            network_settings_entry = SettingsDefinition.get_settings_entry(SettingsConstants.SETTING__NETWORK)
            network_display = network_settings_entry.get_selection_option_display_name_by_value(self.network)
            mainnet = network_settings_entry.get_selection_option_display_name_by_value(SettingsConstants.MAINNET)

            # Display the Screen to show the brute-forcing progress.
            # Using a loop here to handle the SKIP_10 button presses to increment the counter
            # and resume displaying the screen. User won't even notice that the Screen is
            # being re-constructed.
            while True:
                selected_menu_num = self.run_screen(
                    seed_screens.SeedAddressVerificationScreen,
                    address=self.address,
                    derivation_path=self.derivation_path,
                    script_type=script_type_display,
                    sig_type=sig_type_display,
                    network=network_display,
                    is_mainnet=network_display == mainnet,
                    threadsafe_counter=self.threadsafe_counter,
                    verified_index=self.verified_index,
                    button_data=button_data,
                )

                if self.verified_index.cur_count is not None:
                    break

                if selected_menu_num == RET_CODE__BACK_BUTTON:
                    break

                if selected_menu_num is None:
                    # Only happens in the test suite; the screen isn't actually executed so
                    # it returns before the brute force thread has completed.
                    time.sleep(0.1)
                    continue

                if button_data[selected_menu_num] == self.SKIP_10:
                    self.threadsafe_counter.increment(10)

                elif button_data[selected_menu_num] == self.CANCEL:
                    break

            if self.verified_index.cur_count is not None:
                # Successfully verified the addr; update the data
                self.controller.unverified_address["verified_index"] = self.verified_index.cur_count
                self.controller.unverified_address["verified_index_is_change"] = self.verified_index_is_change.cur_count == 1
                return Destination(SeedAddressVerificationSuccessView)

        finally:
            # Halt the thread if the user gave up (will already be stopped if it verified the
            # target addr).
            self.addr_verification_thread.stop()

            # Block until the thread has stopped
            while self.addr_verification_thread.is_alive():
                time.sleep(0.01)

        return Destination(MainMenuView)



    class BruteForceAddressVerificationThread(BaseThread):
        def __init__(self, address: str, seed: Seed, descriptor: Descriptor, script_type: str, embit_network: str, derivation_path: str, threadsafe_counter: ThreadsafeCounter, verified_index: ThreadsafeCounter, verified_index_is_change: ThreadsafeCounter):
            """
                Either seed or descriptor will be None
            """
            super().__init__()
            self.address = address
            self.seed = seed
            self.descriptor = descriptor
            self.script_type = script_type
            self.embit_network = embit_network
            self.derivation_path = derivation_path
            self.threadsafe_counter = threadsafe_counter
            self.verified_index = verified_index
            self.verified_index_is_change = verified_index_is_change

            if self.seed:
                self.xpub = self.seed.get_xpub(wallet_path=self.derivation_path, network=Settings.get_instance().get_value(SettingsConstants.SETTING__NETWORK))


        def run(self):
            from seedsigner.helpers import embit_utils
            while self.keep_running:
                if self.threadsafe_counter.cur_count % 10 == 0:
                    logger.info(f"Incremented to {self.threadsafe_counter.cur_count}")
                
                i = self.threadsafe_counter.cur_count

                if self.descriptor:
                    receive_address = embit_utils.get_multisig_address(descriptor=self.descriptor, index=i, is_change=False, embit_network=self.embit_network)
                    change_address = embit_utils.get_multisig_address(descriptor=self.descriptor, index=i, is_change=True, embit_network=self.embit_network)

                else:
                    receive_address = embit_utils.get_single_sig_address(xpub=self.xpub, script_type=self.script_type, index=i, is_change=False, embit_network=self.embit_network)
                    change_address = embit_utils.get_single_sig_address(xpub=self.xpub, script_type=self.script_type, index=i, is_change=True, embit_network=self.embit_network)
                    
                if self.address == receive_address:
                    self.verified_index.set_value(i)
                    self.verified_index_is_change.set_value(0)
                    self.keep_running = False
                    break

                elif self.address == change_address:
                    self.verified_index.set_value(i)
                    self.verified_index_is_change.set_value(1)
                    self.keep_running = False
                    break

                # Increment our index counter
                self.threadsafe_counter.increment()



class SeedAddressVerificationSuccessView(View):
    def run(self):
        self.run_screen(
            seed_screens.SeedAddressVerificationSuccessScreen,
            address = self.controller.unverified_address["address"],
            verified_index = self.controller.unverified_address["verified_index"],
            verified_index_is_change = self.controller.unverified_address["verified_index_is_change"],
        )

        return Destination(MainMenuView)



class LoadMultisigWalletDescriptorView(View):
    SCAN = ButtonOption("Scan descriptor", SeedSignerIconConstants.QRCODE)
    CANCEL = ButtonOption("Cancel")

    def run(self):
        button_data = [self.SCAN, self.CANCEL]
        selected_menu_num = self.run_screen(
            seed_screens.LoadMultisigWalletDescriptorScreen,
            button_data=button_data,
            show_back_button=False,
        )

        if button_data[selected_menu_num] == self.SCAN:
            from seedsigner.views.scan_views import ScanWalletDescriptorView
            return Destination(ScanWalletDescriptorView)

        elif button_data[selected_menu_num] == self.CANCEL:
            from seedsigner.controller import Controller
            if self.controller.resume_main_flow == Controller.FLOW__PSBT:
                return Destination(BackStackView)
            else:
                return Destination(MainMenuView)



class MultisigWalletDescriptorView(View):
    RETURN = ButtonOption("Return to transaction")
    VERIFY_ADDR = ButtonOption("Verify addr")
    ADDRESS_EXPLORER = ButtonOption("Address explorer")
    OK = ButtonOption("OK")
    NEXT = ButtonOption("Next")

    def __init__(self, page_index: int = 0):
        super().__init__()
        self.page_index = page_index

    def run(self):
        descriptor = self.controller.multisig_wallet_descriptor

        fingerprints = []
        for key in descriptor.keys:
            fingerprint = hexlify(key.fingerprint).decode()
            fingerprints.append(fingerprint)
        
        from seedsigner.helpers.embit_utils import get_multisig_policy
        threshold, n = get_multisig_policy(descriptor)
        # TRANSLATOR_NOTE: Multisig policy. For a "2 of 3" policy, "threshold" = 2; "n" = 3
        policy = _("{threshold} of {n}").format(threshold=threshold, n=n)

        button_data = [self.OK]
        if self.controller.resume_main_flow:
            from seedsigner.controller import Controller
            if self.controller.resume_main_flow == Controller.FLOW__PSBT:
                button_data = [self.RETURN]
            elif self.controller.resume_main_flow == Controller.FLOW__VERIFY_MULTISIG_ADDR and self.controller.unverified_address:
                verify_addr_display = f"""{_(self.VERIFY_ADDR.button_label)} {self.controller.unverified_address["address"][:7]}"""
                button_data = [ButtonOption(verify_addr_display)]
            elif self.controller.resume_main_flow == Controller.FLOW__ADDRESS_EXPLORER:
                button_data = [self.ADDRESS_EXPLORER]

        page_size = seed_screens.MultisigWalletDescriptorScreen.FINGERPRINTS_PER_PAGE
        if (self.page_index + 1) * page_size < len(fingerprints):
            # Every signing key keeps both its hex fingerprint and LifeHash;
            # review additional keys before continuing the original flow.
            button_data = [self.NEXT]

        selected_menu_num = self.run_screen(
            seed_screens.MultisigWalletDescriptorScreen,
            policy=policy,
            fingerprints=fingerprints,
            page_index=self.page_index,
            button_data=button_data,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            if self.page_index == 0:
                self.controller.multisig_wallet_descriptor = None
            return Destination(BackStackView)

        elif button_data[selected_menu_num] == self.NEXT:
            return Destination(MultisigWalletDescriptorView, view_args={"page_index": self.page_index + 1})
        
        elif button_data[selected_menu_num] == self.RETURN:
            # Jump straight back to PSBT change verification
            from seedsigner.views.psbt_views import PSBTChangeDetailsView
            self.controller.resume_main_flow = None
            return Destination(PSBTChangeDetailsView, view_args=dict(change_address_num=0))

        elif button_data[selected_menu_num].button_label.startswith(_(self.VERIFY_ADDR.button_label)):
            self.controller.resume_main_flow = None
            return Destination(SeedAddressVerificationView)

        elif button_data[selected_menu_num] == self.ADDRESS_EXPLORER:
            from seedsigner.views.tools_views import ToolsAddressExplorerAddressTypeView
            self.controller.resume_main_flow = None
            return Destination(ToolsAddressExplorerAddressTypeView)

        return Destination(MainMenuView)



"""****************************************************************************
    Sign Message Views
****************************************************************************"""
class SeedSignMessageStartView(View):
    """
    Routes users straight through to the "Sign" screen if a signing `seed` has
    already been selected. Otherwise routes to `SeedSelectSeedView` to select or
    load a seed first.
    """
    def __init__(self, derivation_path: str, message: str):
        from seedsigner.helpers import embit_utils
        super().__init__()
        self.derivation_path = derivation_path
        self.message = message

        if self.settings.get_value(SettingsConstants.SETTING__MESSAGE_SIGNING) == SettingsConstants.OPTION__DISABLED:
            self.set_redirect(Destination(OptionDisabledView, view_args=dict(settings_attr=SettingsConstants.SETTING__MESSAGE_SIGNING)))
            return

        # calculate the actual receive address
        addr_format = embit_utils.parse_derivation_path(derivation_path)
        if not addr_format["clean_match"]:
            self.set_redirect(Destination(NotYetImplementedView, view_args=dict(text=f"Signing messages for custom derivation paths not supported")))
            self.controller.resume_main_flow = None
            return

        # Note: addr_format["network"] can be MAINNET or [TESTNET, REGTEST]
        if self.settings.get_value(SettingsConstants.SETTING__NETWORK) not in addr_format["network"]:
            from seedsigner.views.view import NetworkMismatchErrorView
            self.set_redirect(Destination(NetworkMismatchErrorView, view_args=dict(derivation_path=self.derivation_path)))

            # cleanup. Note: We could leave this in place so the user can resume the
            # flow, but for now we avoid complications and keep things simple.
            self.controller.resume_main_flow = None
            return

        data = self.controller.sign_message_data
        if data is None:
            data = {}
            self.controller.sign_message_data = data
        data["derivation_path"] = derivation_path
        data["message"] = message
        data["addr_format"] = addr_format

        if data.get("seed") is not None:
            # We already know which seed we're signing with
            self.set_redirect(Destination(SeedSignMessageConfirmMessageView, skip_current_view=True))
        else:
            from seedsigner.controller import Controller
            self.set_redirect(Destination(SeedSelectSeedView, view_args=dict(flow=Controller.FLOW__SIGN_MESSAGE), skip_current_view=True))



class SeedSignMessageConfirmMessageView(View):
    def __init__(self, page_num: int = 0):
        super().__init__()
        self.page_num = page_num  # Note: zero-indexed numbering!


    def run(self):
        from seedsigner.gui.screens.seed_screens import SeedSignMessageConfirmMessageScreen

        selected_menu_num = self.run_screen(
            SeedSignMessageConfirmMessageScreen,
            page_num=self.page_num,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            if self.page_num == 0:
                # We're exiting this flow entirely
                self.controller.resume_main_flow = None
                self.controller.sign_message_data = None
            return Destination(BackStackView)

        # User clicked "Next"
        if self.page_num == len(self.controller.sign_message_data["paged_message"]) - 1:
            # We've reached the end of the paged message
            return Destination(SeedSignMessageConfirmAddressView)
        else:
            return Destination(SeedSignMessageConfirmMessageView, view_args=dict(page_num=self.page_num + 1))



class SeedSignMessageConfirmAddressView(View):
    def __init__(self):
        from seedsigner.helpers import embit_utils
        super().__init__()
        data = self.controller.sign_message_data
        seed = data.get("seed")
        self.derivation_path = data.get("derivation_path")
        addr_format = data.get("addr_format")

        if seed is None or not self.derivation_path:
            raise Exception("Routing error: sign_message_data hasn't been set")

        if not addr_format["clean_match"] or addr_format["script_type"] == SettingsConstants.CUSTOM_DERIVATION:
            raise Exception(_("Signing messages for custom derivation paths not supported"))

        if addr_format["network"] != SettingsConstants.MAINNET:
            # We're in either Testnet or Regtest or...?
            if self.settings.get_value(SettingsConstants.SETTING__NETWORK) in [SettingsConstants.TESTNET, SettingsConstants.REGTEST]:
                addr_format["network"] = self.settings.get_value(SettingsConstants.SETTING__NETWORK)
            else:
                from seedsigner.views.view import NetworkMismatchErrorView
                self.set_redirect(Destination(NetworkMismatchErrorView, view_args=dict(derivation_path=self.derivation_path)))

                # cleanup. Note: We could leave this in place so the user can resume the
                # flow, but for now we avoid complications and keep things simple.
                self.controller.resume_main_flow = None
                self.controller.sign_message_data = None
                return

        xpub = seed.get_xpub(wallet_path=addr_format["wallet_derivation_path"], network=addr_format["network"])
        embit_network = embit_utils.get_embit_network_name(addr_format["network"])
        self.address = embit_utils.get_single_sig_address(xpub=xpub, script_type=addr_format["script_type"], index=addr_format["index"], is_change=addr_format["is_change"], embit_network=embit_network)


    def run(self):
        from seedsigner.gui.screens.seed_screens import SeedSignMessageConfirmAddressScreen
        selected_menu_num = self.run_screen(
            SeedSignMessageConfirmAddressScreen,
            derivation_path=self.derivation_path,
            address=self.address,
        )

        if selected_menu_num == RET_CODE__BACK_BUTTON:
            return Destination(BackStackView)

        # User clicked "Sign Message"
        return Destination(SeedSignMessageSignedMessageQRView)



class SeedSignMessageSignedMessageQRView(View):
    """
    Displays the signed message as a QR code.
    """
    def __init__(self):
        from seedsigner.helpers import embit_utils
        super().__init__()
        data = self.controller.sign_message_data

        self.seed = data["seed"]
        derivation_path = data["derivation_path"]
        message: str = data["message"]

        self.signed_message = embit_utils.sign_message(seed_bytes=self.seed.seed_bytes, derivation=derivation_path, msg=message.encode())


    def run(self):
        from seedsigner.gui.screens.screen import QRDisplayScreen
        qr_encoder = GenericStaticQrEncoder(data=self.signed_message)
        
        self.run_screen(
            QRDisplayScreen,
            qr_encoder=qr_encoder,
        )
    
        # cleanup
        self.controller.resume_main_flow = None
        self.controller.sign_message_data = None

        # Exiting/Canceling the QR display screen always returns Home
        return Destination(MainMenuView, skip_current_view=True)
