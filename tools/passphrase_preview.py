#!/usr/bin/env python3
"""Run the real passphrase, LifeHash and BIP-85 screens without Raspberry Pi hardware.

Install requirements.txt, tests/requirements.txt and l10n/requirements-l10n.txt
in a Python 3.10–3.12 virtual environment, then compile catalogs with
``python setup.py compile_catalog``. A native libzbar is needed by the app's
imports. On macOS, a temporary build can be exposed with DYLD_LIBRARY_PATH.

    python tools/passphrase_preview.py
    python tools/passphrase_preview.py --screenshots /tmp/passphrase-screenshots

The browser receives real 240x240 PIL frames and sends hardware-button events.
Fingerprint LifeHashes follow Blockchain Commons' C++ LifeHash v2 reference.
Only this feature's navigation is enabled. All seeds are public test fixtures;
settings are not persisted. Do not enter real secrets into this developer tool.
"""

import argparse
import io
import json
import logging
from pathlib import Path
from queue import Queue
import sys
import tempfile
from threading import Lock, Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Import the real input constants while replacing only the Raspberry Pi module.
gpio = MagicMock()
gpio.RPI_INFO = {"P1_REVISION": 3}
sys.modules["RPi"] = MagicMock()
sys.modules["RPi.GPIO"] = gpio

from PIL import Image, ImageDraw, features
from seedsigner.controller import Controller, BackgroundImportThread
from seedsigner.gui.renderer import Renderer
from seedsigner.gui.components import GUIConstants
from seedsigner.hardware.buttons import HardwareButtons, HardwareButtonsConstants
from seedsigner.hardware.microsd import MicroSD
from seedsigner.models.seed import Seed
from seedsigner.models.seed_storage import SeedStorage
from seedsigner.models.settings import Settings
from seedsigner.models.settings_definition import SettingsConstants
from seedsigner.views import seed_views, settings_views
from seedsigner.views.screensaver import OpeningSplashView
from seedsigner.views.view import Destination, View


MNEMONIC = ["abandon"] * 11 + ["about"]
DEMO_PASSPHRASE = "preview"
KEYS = {
    "up": HardwareButtonsConstants.KEY_UP,
    "down": HardwareButtonsConstants.KEY_DOWN,
    "left": HardwareButtonsConstants.KEY_LEFT,
    "right": HardwareButtonsConstants.KEY_RIGHT,
    "press": HardwareButtonsConstants.KEY_PRESS,
    "key1": HardwareButtonsConstants.KEY1,
    "key2": HardwareButtonsConstants.KEY2,
    "key3": HardwareButtonsConstants.KEY3,
}


class ResetPreview(BaseException):
    def __init__(self, scenario):
        self.scenario = scenario


class ScreenshotComplete(Exception):
    pass


class PreviewButtons:
    def __init__(self):
        self.events = Queue()

    def wait_for(self, keys=None, **kwargs):
        while True:
            event = self.events.get()
            if isinstance(event, str):
                raise ResetPreview(event)
            if keys is None or event in keys:
                return event

    def update_last_input_time(self):
        pass

    def check_for_low(self, *args, **kwargs):
        return False

    def has_any_input(self):
        return not self.events.empty()

    def trigger_override(self):
        self.events.put(HardwareButtonsConstants.OVERRIDE)


class PreviewRenderer(Renderer):
    def __init__(self):
        self.canvas_width = self.canvas_height = 240
        self.canvas = Image.new("RGB", (240, 240))
        self.draw = ImageDraw.Draw(self.canvas)
        self.frame_lock = Lock()
        self.frame = b""
        self.version = 0
        self.view_name = ""
        self.notice = ""
        self.capture_path = None

    @property
    def is_screenshot_generator(self):
        return self.capture_path is not None

    def show_image(self, image=None, alpha_overlay=None, **kwargs):
        if kwargs.get("is_background_thread") and self.capture_path:
            return
        if image is not None:
            self.canvas.paste(image)
        frame = self.canvas.copy()
        if alpha_overlay is not None:
            frame = Image.alpha_composite(frame.convert("RGBA"), alpha_overlay)
        output = io.BytesIO()
        frame.save(output, format="PNG")
        with self.frame_lock:
            self.frame = output.getvalue()
            self.version += 1
        if self.capture_path:
            self.capture_path.write_bytes(output.getvalue())
            raise ScreenshotComplete()


HTML = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>SeedSigner · Passphrase preview</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#101214;color:#eceff1}
body{max-width:900px;margin:32px auto;padding:0 24px}h1{font-size:24px;margin-bottom:8px}
p{color:#aeb8c0;line-height:1.5}.tag{font-size:12px;color:#f5a623;letter-spacing:.1em}
.device{display:flex;align-items:center;justify-content:center;gap:24px;background:#191c20;
 border:1px solid #353a42;padding:28px;border-radius:18px;margin:24px 0;flex-wrap:wrap}
#screen{width:480px;height:480px;image-rendering:pixelated;max-width:100%;object-fit:contain;background:#000}
button,select{background:#2c3139;border:1px solid #505862;color:#fff;border-radius:8px;padding:12px 16px;
 font:inherit;cursor:pointer}button:hover{border-color:#f5a623}button:active{background:#805817}
.side{display:grid;gap:28px}.pad{display:grid;grid-template-columns:repeat(3,54px);gap:6px}
.pad button{padding:12px 0}.spacer{visibility:hidden}.settings{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
#status{font:13px ui-monospace,monospace;overflow-wrap:anywhere}a{color:#f5a623}
@media(max-width:600px){#screen{width:240px;height:240px}.device{gap:16px;padding:16px}.side{display:flex;gap:8px}}
</style>
<div class="tag">ACTUAL APPLICATION RENDERER · PUBLIC TEST SEED</div>
<h1>SeedSigner passphrase, LifeHash and BIP-85 preview</h1>
<p>Use the directional pad and three side buttons, just as on the device.
Arrow keys move; Enter selects; 1, 2 and 3 press the side buttons.</p>
<div class="settings"><select id="scenario" aria-label="Demo scenario">
<option value="bare">Seed without passphrase</option>
<option value="existing">Seed with “preview” passphrase</option>
<option value="save-choice">Review “aaa”, then choose how to load</option>
<option value="disabled">Passphrase support disabled</option>
<option value="bip85-bare">BIP-85 from seed without passphrase</option>
<option value="bip85-existing">BIP-85 from passphrased seed</option>
<option value="bip85-loaded">Loaded BIP-85 child (parent retained)</option>
<option value="bip85-loaded-existing">Loaded child of passphrased parent</option>
<option value="bip85-loaded-existing-passphrase">Passphrased child of passphrased parent</option>
<option value="bip85-change">Change child index (parent retained)</option>
<option value="bip85-grandchild">Derive from a loaded child</option>
<option value="bip85-parent-missing">Change index with parent unloaded</option>
<option value="lineage">In-Memory Seeds: wallet relationships</option>
<option value="settings">BIP-39 passphrase setting</option></select>
<button id="reset">Reset demo</button><a href="/frame.png" download="seedsigner-preview.png">Save screen</a></div>
<div class="device"><div class="pad">
<span></span><button data-key="up" aria-label="Up">↑</button><span></span>
<button data-key="left" aria-label="Left">←</button><button data-key="press" aria-label="Select">●</button>
<button data-key="right" aria-label="Right">→</button><span></span><button data-key="down" aria-label="Down">↓</button>
</div><img id="screen" alt="Live SeedSigner device screen" src="/frame.png">
<div class="side"><button data-key="key1">1</button><button data-key="key2">2</button><button data-key="key3">3</button></div></div>
<p id="status">Starting…</p>
<p>Mnemonic: <code>abandon</code> × 11, <code>about</code>. For development only: never enter real secrets.
The seed menu, settings, passphrase and BIP-85 flows use the application code. Wallet fingerprints remain visible
beside their LifeHash v2 images. Other features return to the main menu.</p>
<script>
const screen=document.querySelector('#screen'),status=document.querySelector('#status');let version=-1;
async function post(path,value){await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});}
document.querySelectorAll('[data-key]').forEach(b=>b.onclick=()=>post('/key',{key:b.dataset.key}));
document.querySelector('#reset').onclick=()=>post('/reset',{scenario:document.querySelector('#scenario').value});
document.addEventListener('keydown',e=>{if(e.target.tagName==='SELECT')return;
 const keys={ArrowUp:'up',ArrowDown:'down',ArrowLeft:'left',ArrowRight:'right',Enter:'press','1':'key1','2':'key2','3':'key3'};
 if(keys[e.key]){e.preventDefault();if(!e.repeat)post('/key',{key:keys[e.key]});}});
async function poll(){try{const data=await(await fetch('/state')).json();
 if(data.version!==version){version=data.version;screen.src='/frame.png?v='+version;}
 status.textContent=data.view+' · Loaded: '+data.fingerprints.join(', ')+(data.notice?' · '+data.notice:'');
 }catch(e){status.textContent='Preview is disconnected. Restart the Python command.';}setTimeout(poll,150);}poll();
</script></html>"""


def configure_controller(scenario="bare"):
    Settings._instance = None
    Controller._instance = None
    controller = Controller.get_instance()
    controller._storage = SeedStorage()
    settings = controller.settings
    settings.set_value(SettingsConstants.SETTING__MICROSD_TOAST_TIMER, 0)
    settings.set_value(SettingsConstants.SETTING__PASSPHRASE,
                       SettingsConstants.OPTION__DISABLED if scenario == "disabled" else SettingsConstants.OPTION__ENABLED)
    settings.set_value(SettingsConstants.SETTING__BIP85_CHILD_SEEDS, SettingsConstants.OPTION__ENABLED)
    seed = Seed(MNEMONIC, passphrase=DEMO_PASSPHRASE if scenario in {
        "existing", "bip85-existing", "bip85-loaded-existing", "bip85-loaded-existing-passphrase",
        "bip85-change", "bip85-grandchild", "bip85-parent-missing",
    } else "")
    controller.storage.seeds.append(seed)
    if scenario in {"bip85-loaded", "bip85-loaded-existing", "bip85-loaded-existing-passphrase",
                    "bip85-change", "bip85-grandchild", "bip85-parent-missing"}:
        destination = seed_views.SeedBIP85LoadChildView(seed=seed, num_words=12, child_index=0).run()
        seed = destination.view_args["seed"]
        if scenario in {"bip85-loaded-existing-passphrase", "bip85-grandchild"}:
            # Apply the public demo passphrase through the actual save operation,
            # preserving the child's stored deriving-parent fingerprint.
            with patch.object(seed_views.SeedPassphraseSaveView, "run_screen", return_value=0):
                destination = seed_views.SeedPassphraseSaveView(seed=seed, passphrase="child-preview").run()
            seed = destination.view_args["seed"]
        if scenario == "bip85-parent-missing":
            controller.storage.seeds = [seed]
    elif scenario == "lineage":
        child_words = seed.get_bip85_child_mnemonic(0, 12).split()
        parent_fingerprint = seed.get_fingerprint()
        controller.storage.seeds.extend([
            Seed(MNEMONIC, passphrase=DEMO_PASSPHRASE),
            Seed(child_words, bip85_parent_fingerprint=parent_fingerprint),
            Seed(child_words, passphrase="child-preview", bip85_parent_fingerprint=parent_fingerprint),
        ])
    return controller, seed


def generate_screenshots(output, renderer):
    from embit.bip32 import HDKey
    from embit.descriptor import Descriptor

    output.mkdir(parents=True, exist_ok=True)
    controller, bare = configure_controller()
    protected = Seed(MNEMONIC, passphrase=DEMO_PASSPHRASE)
    controller.storage.seeds.append(protected)
    controller.storage.set_pending_seed(Seed(MNEMONIC, passphrase=DEMO_PASSPHRASE))
    edit_a = Seed(MNEMONIC, passphrase="a")
    controller.storage.seeds.append(edit_a)
    edit_aa = Seed(MNEMONIC, passphrase="aa")
    controller.storage.seeds.append(edit_aa)
    long_passphrase = "long passphrase review " * 8
    long_initial_seed = Seed(MNEMONIC, passphrase=long_passphrase)
    final_initial_page = len(seed_views.seed_screens.SeedReviewPassphraseScreen.passphrase_pages(long_passphrase)) - 1
    final_loaded_page = len(seed_views.seed_screens.SeedConfirmPassphraseScreen.passphrase_pages(long_passphrase)) - 1

    # Public fixtures exercise the actual descriptor View's four-key pagination.
    descriptor_keys = []
    for passphrase in ["", DEMO_PASSPHRASE, "preview2", "cosigner3", "cosigner4"]:
        seed = Seed(MNEMONIC, passphrase=passphrase)
        xpub = HDKey.from_seed(seed.seed_bytes).derive("m/48h/0h/0h/2h").to_public().to_base58()
        descriptor_keys.append(f"[{seed.get_fingerprint()}/48h/0h/0h/2h]{xpub}/0/*")
    controller.multisig_wallet_descriptor = Descriptor.from_string(
        f"wsh(sortedmulti(3,{','.join(descriptor_keys)}))"
    )
    cases = [
        ("01-passphrase-setting", settings_views.SettingsEntryUpdateSelectionView,
         {"attr_name": SettingsConstants.SETTING__PASSPHRASE}),
        ("02-seed-options", seed_views.SeedOptionsView, {"seed": bare}),
        ("04-add-keyboard", seed_views.SeedEditPassphraseView, {"seed": bare}),
        ("05-add-confirmation", seed_views.SeedConfirmPassphraseView,
         {"seed": bare, "passphrase": DEMO_PASSPHRASE}),
        ("06-edit-menu", seed_views.SeedPassphraseMenuView, {"seed": protected}),
        ("07-edit-keyboard", seed_views.SeedEditPassphraseView, {"seed": protected}),
        ("08-edit-confirmation", seed_views.SeedConfirmPassphraseView,
         {"seed": protected, "passphrase": "preview2"}),
        ("09-remove-confirmation", seed_views.SeedConfirmPassphraseView,
         {"seed": protected, "passphrase": ""}),
        ("10-cancel-confirmation", seed_views.SeedCancelPassphraseView,
         {"seed": protected, "passphrase": "preview2"}),
        ("11-long-passphrase", seed_views.SeedConfirmPassphraseView,
         {"seed": protected, "passphrase": long_passphrase}),
        ("12-seed-list", seed_views.SeedsMenuView, {}),
        ("13-seed-finalize", seed_views.SeedFinalizeView, {}),
        ("14-initial-passphrase-review", seed_views.SeedReviewPassphraseView, {}),
        ("15-multisig-keys-page-1", seed_views.MultisigWalletDescriptorView, {"page_index": 0}),
        ("16-multisig-keys-page-2", seed_views.MultisigWalletDescriptorView, {"page_index": 1}),
        ("17-discard-seed", seed_views.SeedDiscardView, {"seed": protected}),
        ("18-edit-aa-review", seed_views.SeedConfirmPassphraseView,
         {"seed": edit_a, "passphrase": "aa"}),
        ("19-initial-long-page-1", seed_views.SeedReviewPassphraseView, {"page_index": 0}),
        ("20-initial-long-last-page", seed_views.SeedReviewPassphraseView, {"page_index": final_initial_page}),
        ("21-loaded-long-last-page", seed_views.SeedConfirmPassphraseView,
         {"seed": protected, "passphrase": long_passphrase, "page_index": final_loaded_page}),
        ("22-seed-options-passphrase", seed_views.SeedOptionsView, {"seed": edit_aa}),
        ("23-bip85-bare-review", seed_views.SeedBIP85ReviewView,
         {"seed": bare, "num_words": 12, "child_index": 0}),
        ("24-bip85-bare-words-first", seed_views.SeedWordsView,
         {"seed": bare, "bip85_data": {"num_words": 12, "child_index": 0}}),
        ("25-bip85-bare-words-last", seed_views.SeedWordsView,
         {"seed": bare, "bip85_data": {"num_words": 12, "child_index": 0}, "page_index": 3}),
        ("26-bip85-passphrased-review", seed_views.SeedBIP85ReviewView,
         {"seed": protected, "num_words": 24, "child_index": 0}),
        ("27-bip85-passphrased-words-first", seed_views.SeedWordsView,
         {"seed": protected, "bip85_data": {"num_words": 24, "child_index": 0}}),
        ("28-bip85-passphrased-words-last", seed_views.SeedWordsView,
         {"seed": protected, "bip85_data": {"num_words": 24, "child_index": 0}, "page_index": 7}),
        ("29-bip85-max-index-review", seed_views.SeedBIP85ReviewView,
         {"seed": protected, "num_words": 24, "child_index": 2**31 - 1}),
        ("30-bip85-max-index-words-last", seed_views.SeedWordsView,
         {"seed": protected, "bip85_data": {"num_words": 24, "child_index": 2**31 - 1}, "page_index": 7}),
        ("31-bip85-load-child-prompt", seed_views.SeedWordsBackupTestPromptView,
         {"seed": bare, "bip85_data": {"num_words": 12, "child_index": 0}}),
        ("32-bip85-child-loaded", seed_views.SeedBIP85LoadChildView,
         {"seed": bare, "num_words": 12, "child_index": 0}),
        ("33-bip85-parent-and-child", seed_views.SeedsMenuView, {}),
        ("34-bip85-child-passphrase-review", seed_views.SeedConfirmPassphraseView,
         lambda: {"seed": controller.storage.seeds[-1], "passphrase": "child-preview"}),
        ("35-bip85-child-passphrase-menu", seed_views.SeedConfirmPassphraseView,
         lambda: {"seed": controller.storage.seeds[-1], "passphrase": "child-preview"}),
        ("36-in-memory-wallet-relationships", seed_views.SeedsMenuView, {}),
        ("37-in-memory-child-passphrase-selected", seed_views.SeedsMenuView, {}),
        ("38-child-passphrase-bip85-selected", seed_views.SeedOptionsView,
         lambda: {"seed": controller.storage.seeds[-1]}),
        ("39-passphrase-load-choice", seed_views.SeedConfirmPassphraseView,
         lambda: {"seed": controller.storage.seeds[0], "passphrase": "aaa"}),
        ("40-passphrase-loaded-separately", seed_views.SeedConfirmPassphraseView,
         lambda: {"seed": controller.storage.seeds[0], "passphrase": "aaa"}),
        ("41-bip85-loaded-passphrased-parent", seed_views.SeedOptionsView,
         lambda: {"seed": controller.storage.seeds[-1]}),
        ("42-bip85-passphrased-child-passphrased-parent", seed_views.SeedOptionsView,
         lambda: {"seed": controller.storage.seeds[-1]}),
        ("43-bip85-child-menu", seed_views.SeedBIP85ChildMenuView,
         lambda: {"seed": controller.storage.seeds[-1]}),
        ("44-bip85-change-index-prefilled", seed_views.SeedBIP85SelectChildIndexView,
         lambda: {"seed": controller.storage.seeds[0], "num_words": 12,
                  "change_from_seed": controller.storage.seeds[1]}),
        ("45-bip85-sibling-review", seed_views.SeedBIP85ReviewView,
         lambda: {"seed": controller.storage.seeds[0], "num_words": 12, "child_index": 1,
                  "change_from_seed": controller.storage.seeds[1]}),
        ("46-bip85-sibling-load-choice", seed_views.SeedBIP85LoadChildView,
         lambda: {"seed": controller.storage.seeds[0], "num_words": 12, "child_index": 1,
                  "change_from_seed": controller.storage.seeds[1]}),
        ("47-bip85-sibling-loaded-separately", seed_views.SeedBIP85LoadChildView,
         lambda: {"seed": controller.storage.seeds[0], "num_words": 12, "child_index": 1,
                  "change_from_seed": controller.storage.seeds[1]}),
        ("48-bip85-grandchild-review", seed_views.SeedBIP85ReviewView,
         lambda: {"seed": controller.storage.seeds[-1], "num_words": 12, "child_index": 0}),
        ("49-bip85-grandchild-loaded", seed_views.SeedBIP85LoadChildView,
         lambda: {"seed": controller.storage.seeds[-1], "num_words": 12, "child_index": 0}),
        ("50-bip85-parent-needed", seed_views.SeedBIP85ChildMenuView,
         lambda: {"seed": controller.storage.seeds[-1]}),
        ("51-bip85-origin-unavailable", seed_views.SeedBIP85ChildMenuView,
         lambda: {"seed": controller.storage.seeds[-1]}),
    ]
    original_run_screen = View.run_screen

    def focus_passphrase(view, Screen_cls, **kwargs):
        if (renderer.capture_path.stem == "37-in-memory-child-passphrase-selected"
                and isinstance(view, seed_views.SeedsMenuView)):
            kwargs["selected_button"] = 3
        if (renderer.capture_path.stem in {"35-bip85-child-passphrase-menu",
                                          "39-passphrase-load-choice", "40-passphrase-loaded-separately"}
                and isinstance(view, seed_views.SeedConfirmPassphraseView)):
            # Continue through the real review into its save-choice View.
            return kwargs["button_data"].index(view.APPLY)
        if isinstance(view, seed_views.SeedPassphraseSaveView):
            if renderer.capture_path.stem == "35-bip85-child-passphrase-menu":
                return kwargs["button_data"].index(view.REPLACE)
            if renderer.capture_path.stem == "40-passphrase-loaded-separately":
                return kwargs["button_data"].index(view.LOAD_SEPARATELY)
        if (renderer.capture_path.stem == "47-bip85-sibling-loaded-separately"
                and isinstance(view, seed_views.SeedBIP85SaveChildView)):
            return kwargs["button_data"].index(view.LOAD_SEPARATELY)
        if (renderer.capture_path.stem in {"50-bip85-parent-needed", "51-bip85-origin-unavailable"}
                and isinstance(view, seed_views.SeedBIP85ChildMenuView)):
            return kwargs["button_data"].index(view.CHANGE_INDEX)
        if isinstance(view, seed_views.SeedOptionsView):
            is_bip85_selected = renderer.capture_path.stem == "38-child-passphrase-bip85-selected"
            target_label = "BIP-85 child seed" if is_bip85_selected else "BIP-39 Passphrase"
            for index, option in enumerate(kwargs.get("button_data", [])):
                if option.button_label == target_label:
                    kwargs["selected_button"] = index
            if is_bip85_selected:
                kwargs["scroll_y_initial_offset"] = GUIConstants.BUTTON_HEIGHT + GUIConstants.LIST_ITEM_PADDING
        return original_run_screen(view, Screen_cls, **kwargs)

    with patch.object(View, "run_screen", focus_passphrase):
        for name, view_class, kwargs in cases:
            if name in {"19-initial-long-page-1", "20-initial-long-last-page"}:
                controller.storage.set_pending_seed(long_initial_seed)
            elif name == "32-bip85-child-loaded":
                controller.storage.seeds = [bare]
            elif name == "36-in-memory-wallet-relationships":
                controller, _ = configure_controller("lineage")
            elif name == "39-passphrase-load-choice":
                controller, _ = configure_controller()
            elif name == "41-bip85-loaded-passphrased-parent":
                controller, _ = configure_controller("bip85-loaded-existing")
            elif name == "42-bip85-passphrased-child-passphrased-parent":
                controller, _ = configure_controller("bip85-loaded-existing-passphrase")
            elif name == "43-bip85-child-menu":
                controller, _ = configure_controller("bip85-change")
            elif name == "48-bip85-grandchild-review":
                controller, _ = configure_controller("bip85-grandchild")
            elif name == "50-bip85-parent-needed":
                controller, _ = configure_controller("bip85-parent-missing")
            elif name == "51-bip85-origin-unavailable":
                controller, child = configure_controller("bip85-loaded-existing")
                # Legacy children may know their parent fingerprint but lack the
                # derivation index and word count needed for verified changes.
                controller.storage.seeds[-1] = Seed(child.mnemonic_list,
                    bip85_parent_fingerprint=child.bip85_parent_fingerprint)
            if callable(kwargs):
                kwargs = kwargs()
            renderer.capture_path = output / f"{name}.png"
            try:
                destination = Destination(view_class, kwargs)
                while True:
                    destination = destination.run()
                    if (name in {"40-passphrase-loaded-separately", "47-bip85-sibling-loaded-separately"}
                            and destination.View_cls is seed_views.SeedOptionsView):
                        # Show both retained entries after the real load operation.
                        destination = Destination(seed_views.SeedsMenuView)
            except ScreenshotComplete:
                print(renderer.capture_path)
            else:
                raise RuntimeError(f"{name} did not render")
    renderer.capture_path = None
    cards = "".join(f'<figure><img src="{name}.png"><figcaption>{name}</figcaption></figure>' for name, _, _ in cases)
    (output / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Passphrase screens</title>'
        '<style>body{background:#181818;color:white;font:14px system-ui;display:flex;flex-wrap:wrap;gap:24px}'
        'figure{margin:0}img{width:240px;image-rendering:pixelated}figcaption{padding:10px 0}</style>' + cards)


def serve_preview(renderer, buttons, port):
    allowed = {"MainMenuView", "SeedsMenuView", "SeedOptionsView", "SeedDiscardView", "SeedPassphraseMenuView",
               "SeedEditPassphraseView", "SeedConfirmPassphraseView", "SeedPassphraseSaveView", "SeedCancelPassphraseView",
               "SettingsMenuView", "SettingsEntryUpdateSelectionView", "OptionDisabledView",
               "SeedBackupView", "SeedBIP85SelectNumWordsView", "SeedBIP85SelectChildIndexView",
               "SeedBIP85InvalidChildIndexView", "SeedBIP85ReviewView", "SeedWordsWarningView",
               "SeedBIP85LoadChildView", "SeedBIP85ChildMenuView", "SeedBIP85ParentUnavailableView",
               "SeedBIP85SaveChildView",
               "SeedWordsView", "SeedWordsBackupTestPromptView", "SeedWordsBackupTestView",
               "SeedWordsBackupTestMistakeView", "SeedWordsBackupTestSuccessView"}
    original_run = Destination._run_view

    def run_view(destination):
        name = destination.View_cls.__name__
        unsupported_setting = (
            name == "SettingsEntryUpdateSelectionView"
            and (destination.view_args or {}).get("attr_name") not in {
                SettingsConstants.SETTING__PASSPHRASE, SettingsConstants.SETTING__BIP85_CHILD_SEEDS,
            }
        )
        if name not in allowed or unsupported_setting:
            renderer.notice = "This preview supports passphrase editing, BIP-85 and seed-word backup."
            # Home invokes the Controller's normal flow-state cleanup. Going straight
            # back to SeedOptions could auto-resume the unsupported flow indefinitely.
            return Destination(None, clear_history=True)
        renderer.view_name = name
        return original_run(destination)

    def worker():
        scenario = "bare"
        with patch.object(Destination, "_run_view", run_view):
            while True:
                controller, seed = configure_controller(scenario)
                renderer.notice = ""
                destination = Destination(seed_views.SeedOptionsView, {"seed": seed})
                if scenario == "settings":
                    destination = Destination(settings_views.SettingsEntryUpdateSelectionView,
                                              {"attr_name": SettingsConstants.SETTING__PASSPHRASE})
                elif scenario in {"bip85-bare", "bip85-existing"}:
                    destination = Destination(seed_views.SeedBIP85SelectNumWordsView, {"seed": seed})
                elif scenario == "lineage":
                    destination = Destination(seed_views.SeedsMenuView)
                elif scenario == "save-choice":
                    destination = Destination(seed_views.SeedConfirmPassphraseView,
                                              {"seed": seed, "passphrase": "aaa"})
                elif scenario in {"bip85-change", "bip85-parent-missing"}:
                    destination = Destination(seed_views.SeedBIP85ChildMenuView, {"seed": seed})
                elif scenario == "bip85-grandchild":
                    destination = Destination(seed_views.SeedBIP85SelectNumWordsView, {"seed": seed})
                # The preview enters mid-flow. In normal navigation this destination
                # is already the current back-stack entry; settings replaces it after
                # a selection with skip_current_view=True.
                controller.back_stack.append(destination)
                try:
                    controller.start(initial_destination=destination)
                except ResetPreview as reset:
                    scenario = reset.scenario
                    while not buttons.events.empty():
                        buttons.events.get_nowait()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, content, content_type):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                return self.send(HTML.encode(), "text/html; charset=utf-8")
            if path == "/frame.png":
                with renderer.frame_lock:
                    frame = renderer.frame
                return self.send(frame, "image/png")
            if path == "/state":
                controller = Controller.get_instance()
                state = {"version": renderer.version, "view": renderer.view_name,
                         "notice": renderer.notice,
                         "fingerprints": [seed.get_fingerprint() for seed in controller.storage.seeds]}
                return self.send(json.dumps(state).encode(), "application/json")
            self.send_error(404)

        def do_POST(self):
            if self.headers.get("Content-Type") != "application/json":
                return self.send_error(415)
            length = int(self.headers.get("Content-Length", 0))
            if length > 256:
                return self.send_error(413)
            try:
                data = json.loads(self.rfile.read(length))
                if self.path == "/key" and data.get("key") in KEYS:
                    buttons.events.put(KEYS[data["key"]])
                elif self.path == "/reset" and data.get("scenario") in {
                    "bare", "existing", "save-choice", "disabled", "settings", "bip85-bare", "bip85-existing", "bip85-loaded",
                    "bip85-loaded-existing", "bip85-loaded-existing-passphrase", "lineage",
                    "bip85-change", "bip85-grandchild", "bip85-parent-missing",
                }:
                    buttons.events.put(data["scenario"])
                else:
                    return self.send_error(400)
            except (ValueError, TypeError):
                return self.send_error(400)
            self.send(b"{}", "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    Thread(target=worker, daemon=True).start()
    print(f"Passphrase preview: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if not features.check("raqm"):
        print("libraqm unavailable: preview uses Pillow's basic text layout; verify translations on a full build.")
    renderer = PreviewRenderer()
    buttons = PreviewButtons()
    Renderer._instance = renderer
    with tempfile.TemporaryDirectory(prefix="seedsigner-preview-") as temp_dir:
        Settings.SETTINGS_FILENAME = str(Path(temp_dir) / "settings.json")
        with (patch.object(Renderer, "configure_instance"),
              patch.object(HardwareButtons, "get_instance", return_value=buttons),
              patch.object(BackgroundImportThread, "start"),
              patch.object(MicroSD, "start_detection"),
              patch.object(OpeningSplashView, "run"),
              patch.object(Settings, "save")):
            if args.screenshots:
                generate_screenshots(args.screenshots.resolve(), renderer)
            else:
                serve_preview(renderer, buttons, args.port)


if __name__ == "__main__":
    main()
