import pytest

# Install the test suite's hardware mocks before importing Controller.
from base import BaseTest

from seedsigner.controller import BackStack, Controller
from seedsigner.models.seed import ElectrumSeed, Seed
from seedsigner.models.seed_storage import SeedStorage
from seedsigner.models.settings import SettingsConstants


MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about".split()
ELECTRUM_MNEMONIC = "regular reject rare profit once math fringe chase until ketchup century escape".split()
WALLET_STATE_FIELDS = (
    "psbt", "psbt_parser", "psbt_seed", "resume_main_flow",
    "multisig_wallet_descriptor", "unverified_address", "address_explorer_data",
    "sign_message_data",
)


@pytest.mark.parametrize("seed_type,mnemonic", [(Seed, MNEMONIC), (ElectrumSeed, ELECTRUM_MNEMONIC)])
@pytest.mark.parametrize("network", [SettingsConstants.MAINNET, SettingsConstants.TESTNET, SettingsConstants.REGTEST])
@pytest.mark.parametrize("passphrase", ["", " Caf\u00e9 wallet "])
def test_fingerprint_without_passphrase_preserves_loaded_seed(monkeypatch, seed_type, mnemonic, network, passphrase):
    original = seed_type(mnemonic, passphrase)
    expected = seed_type(mnemonic).get_fingerprint(network)
    original_fingerprint = original.get_fingerprint(network)
    original_bytes = original.seed_bytes
    original_mnemonic = original.mnemonic_list
    original_passphrase = original.passphrase
    original_language = original.wordlist_language_code
    calls = []
    get_fingerprint = seed_type.get_fingerprint

    def record_fingerprint(seed, requested_network=SettingsConstants.MAINNET):
        calls.append((seed, requested_network))
        return get_fingerprint(seed, requested_network)

    def reject_mutation(*args, **kwargs):
        pytest.fail("Fingerprint derivation must not temporarily change the loaded seed")

    monkeypatch.setattr(seed_type, "get_fingerprint", record_fingerprint)
    monkeypatch.setattr(original, "set_passphrase", reject_mutation)

    assert original.get_fingerprint_without_passphrase(network) == expected
    assert len(calls) == 1
    derived_seed, requested_network = calls[0]
    assert requested_network == network
    assert type(derived_seed) is seed_type
    if original.has_passphrase:
        assert derived_seed is not original
        assert derived_seed.mnemonic_list is not original_mnemonic
        assert derived_seed.passphrase == ""
        assert expected != original_fingerprint
    else:
        assert derived_seed is original

    assert original.seed_bytes is original_bytes
    assert original.mnemonic_list is original_mnemonic
    assert original.mnemonic_list == mnemonic
    assert original.passphrase == original_passphrase
    assert original.wordlist_language_code == original_language
    assert get_fingerprint(original, network) == original_fingerprint


def test_finalize_pending_duplicate_returns_loaded_instance():
    storage = SeedStorage()
    loaded = Seed(MNEMONIC, "wallet")
    storage.seeds = [loaded]
    storage.set_pending_seed(Seed(MNEMONIC, "wallet"))

    finalized = storage.finalize_pending_seed()

    assert finalized is loaded
    assert storage.seeds == [loaded]
    assert storage.pending_seed is None
    # Re-entering the same seed must still allow the identity-checked edit flow.
    replacement = Seed(MNEMONIC, "updated wallet")
    assert storage.replace_seed(finalized, replacement) is replacement


@pytest.mark.parametrize("old_passphrase,new_passphrase", [
    ("", "new wallet"),
    ("old wallet", "new wallet"),
    ("old wallet", ""),
])
def test_replace_seed_preserves_order_and_original(old_passphrase, new_passphrase):
    storage = SeedStorage()
    before = Seed(MNEMONIC, "before")
    original = Seed(MNEMONIC, old_passphrase)
    after = Seed(MNEMONIC, "after")
    storage.seeds = [before, original, after]
    original_bytes = original.seed_bytes
    replacement = Seed(original.mnemonic_list, new_passphrase)

    selected = storage.replace_seed(original, replacement)

    assert selected is replacement
    assert len(storage.seeds) == 3
    assert storage.seeds[0] is before
    assert storage.seeds[1] is replacement
    assert storage.seeds[2] is after
    assert original.passphrase == old_passphrase
    assert original.seed_bytes == original_bytes
    assert original.mnemonic_list == replacement.mnemonic_list


@pytest.mark.parametrize("existing_first", [True, False])
def test_replace_seed_uses_existing_canonical_instance(existing_first):
    storage = SeedStorage()
    original = Seed(MNEMONIC, "old wallet")
    existing = Seed(MNEMONIC, "new wallet")
    other = Seed(MNEMONIC, "other wallet")
    storage.seeds = [existing, other, original] if existing_first else [original, other, existing]
    replacement = Seed(MNEMONIC, "new wallet")

    selected = storage.replace_seed(original, replacement)

    assert selected is existing
    assert len(storage.seeds) == 2
    assert storage.seeds[0] is (existing if existing_first else other)
    assert storage.seeds[1] is (other if existing_first else existing)
    assert all(seed is not replacement and seed is not original for seed in storage.seeds)


def test_replace_seed_noop_keeps_original_instance():
    storage = SeedStorage()
    original = Seed(MNEMONIC, "caf\u00e9")
    storage.seeds = [original]

    selected = storage.replace_seed(original, Seed(MNEMONIC, "cafe\u0301"))

    assert selected is original
    assert storage.seeds[0] is original


@pytest.mark.parametrize("equal_replacement", [True, False])
def test_replace_seed_rejects_stale_equal_original(equal_replacement):
    storage = SeedStorage()
    stale_original = Seed(MNEMONIC, "old wallet")
    loaded = Seed(MNEMONIC, "old wallet")
    storage.seeds = [loaded]
    replacement = Seed(MNEMONIC, "old wallet" if equal_replacement else "new wallet")

    with pytest.raises(ValueError, match="no longer loaded"):
        storage.replace_seed(stale_original, replacement)

    assert len(storage.seeds) == 1
    assert storage.seeds[0] is loaded


def test_replace_seed_does_not_deduplicate_by_fingerprint(monkeypatch):
    storage = SeedStorage()
    original = Seed(MNEMONIC, "old wallet")
    other = Seed(MNEMONIC, "other wallet")
    replacement = Seed(MNEMONIC, "new wallet")
    storage.seeds = [original, other]
    monkeypatch.setattr(Seed, "get_fingerprint", lambda self, *args, **kwargs: "12345678")

    selected = storage.replace_seed(original, replacement)

    assert selected is replacement
    assert len(storage.seeds) == 2
    assert storage.seeds[1] is other


@pytest.fixture
def controller_with_wallet_state():
    # This unit test does not need to start the Controller's background threads.
    controller = Controller.__new__(Controller)
    controller._storage = SeedStorage()
    for field in WALLET_STATE_FIELDS:
        setattr(controller, field, object())
    controller.back_stack = BackStack([object()])
    return controller


@pytest.mark.parametrize("already_loaded", [True, False])
def test_controller_replacement_clears_wallet_state(controller_with_wallet_state, already_loaded):
    controller = controller_with_wallet_state
    original = Seed(MNEMONIC, "old wallet")
    replacement = Seed(MNEMONIC, "new wallet")
    controller.storage.seeds = [original]
    canonical = Seed(MNEMONIC, "new wallet") if already_loaded else replacement
    if already_loaded:
        controller.storage.seeds.append(canonical)

    selected = controller.replace_seed(original, replacement)

    assert selected is canonical
    assert len(controller.storage.seeds) == 1
    assert controller.storage.seeds[0] is canonical
    for field in WALLET_STATE_FIELDS:
        assert getattr(controller, field) is None
    assert isinstance(controller.back_stack, BackStack)
    assert controller.back_stack == []


@pytest.mark.parametrize("stale_original", [True, False])
def test_controller_noop_or_failure_preserves_state(controller_with_wallet_state, stale_original):
    controller = controller_with_wallet_state
    original = Seed(MNEMONIC, "wallet")
    controller.storage.seeds = [Seed(MNEMONIC, "wallet") if stale_original else original]
    old_state = {field: getattr(controller, field) for field in WALLET_STATE_FIELDS}
    old_back_stack = controller.back_stack

    if stale_original:
        with pytest.raises(ValueError, match="no longer loaded"):
            controller.replace_seed(original, Seed(MNEMONIC, "new wallet"))
    else:
        assert controller.replace_seed(original, Seed(MNEMONIC, "wallet")) is original

    for field in WALLET_STATE_FIELDS:
        assert getattr(controller, field) is old_state[field]
    assert controller.back_stack is old_back_stack
    assert len(controller.back_stack) == 1


class TestControllerTemporaryViewCleanup(BaseTest):
    def test_redirect_drops_view_after_clearing_history(self):
        import gc
        import weakref

        from seedsigner.controller import StopFlowBasedTest
        from seedsigner.views.view import Destination, View

        references = []
        released = []

        class StartView(View):
            def run(self):
                return Destination(RedirectView)

        class RedirectView(View):
            def __init__(self):
                super().__init__()
                self.candidate = Seed(MNEMONIC, "temporary candidate")
                references.append(weakref.ref(self))
                self.set_redirect(Destination(FinishView, clear_history=True))

        class FinishView(View):
            def run(self):
                gc.collect()
                released.append(references[0]() is None)
                raise StopFlowBasedTest()

        # Exercise the real Controller navigation loop, including its redirect log.
        self.controller.start(initial_destination=Destination(StartView))
        assert released == [True]
