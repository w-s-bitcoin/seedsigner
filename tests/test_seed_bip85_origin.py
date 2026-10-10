import gc
import weakref

import pytest

from seedsigner.models.seed import ElectrumSeed, Seed
from seedsigner.models.seed_storage import SeedStorage


MNEMONIC = ["abandon"] * 11 + ["about"]
PARENT_FINGERPRINT = "b4e3f5ed"
CHILD_WORDS = "climb typical because giraffe beach wool fit ship common chapter hotel arm".split()


def child_seed(words=CHILD_WORDS, passphrase="", origin=(PARENT_FINGERPRINT, 0, 12)):
    return Seed(words, passphrase, bip85_parent_fingerprint=origin[0],
                bip85_child_index=origin[1], bip85_num_words=origin[2])


def origin(seed):
    return seed.bip85_parent_fingerprint, seed.bip85_child_index, seed.bip85_num_words


@pytest.mark.parametrize("num_words,index,mnemonic", [
    (12, 0, "climb typical because giraffe beach wool fit ship common chapter hotel arm"),
    (12, 2**31 - 1, "always have female giant cannon resource mercy blue real when modify trouble"),
    (24, 0, "guess violin output company next ribbon submit simple balance toss buffalo number fire horn mystery assault require opinion social pony obey system winter pupil"),
    (24, 2**31 - 1, "rate flash cycle boat unfair fortune humor tunnel song hurt club round famous resource rent inspire lounge hour used spare front mix rough scorpion"),
])
def test_parent_lookup_verifies_full_child_mnemonic_at_index_boundaries(num_words, index, mnemonic):
    # Public vectors derived independently using the BIP85 path and HMAC-SHA512.
    parent = Seed(MNEMONIC, "TREZOR")
    child = child_seed(mnemonic.split(), "child's own passphrase", (PARENT_FINGERPRINT, index, num_words))
    storage = SeedStorage()
    storage.seeds = [parent, child]
    parent_bytes, child_bytes = parent.seed_bytes, child.seed_bytes

    assert storage.has_complete_bip85_origin(child)
    assert storage.get_bip85_parent(child) is parent
    assert parent.seed_bytes is parent_bytes
    assert child.seed_bytes is child_bytes
    assert child.passphrase == "child's own passphrase"
    assert child.is_bip85_child


@pytest.mark.parametrize("correct_parent_loaded", [False, True])
def test_parent_fingerprint_collision_cannot_select_wrong_parent(correct_parent_loaded, monkeypatch):
    wrong_parent = Seed(MNEMONIC)  # Same mnemonic, different deriving passphrase.
    correct_parent = Seed(MNEMONIC, "TREZOR")
    child = child_seed()
    monkeypatch.setattr(wrong_parent, "get_fingerprint", lambda *args, **kwargs: PARENT_FINGERPRINT)
    storage = SeedStorage()
    storage.seeds = [wrong_parent, child]
    if correct_parent_loaded:
        storage.seeds.append(correct_parent)

    assert storage.get_bip85_parent(child) is (correct_parent if correct_parent_loaded else None)


def test_parent_lookup_rejects_multiple_verified_matches():
    parent = Seed(MNEMONIC, "TREZOR")
    clone = Seed(MNEMONIC, "TREZOR")
    child = child_seed()
    storage = SeedStorage()
    # Normal storage deduplicates these, but lookup must not arbitrarily pick one
    # if an ambiguous loaded set is supplied.
    storage.seeds = [parent, clone, child]

    assert storage.get_bip85_parent(child) is None


def test_parent_lookup_ignores_non_bip85_seed_even_with_matching_fingerprint(monkeypatch):
    parent = ElectrumSeed("regular reject rare profit once math fringe chase until ketchup century escape".split())
    child = child_seed()
    monkeypatch.setattr(parent, "get_fingerprint", lambda *args, **kwargs: PARENT_FINGERPRINT)
    monkeypatch.setattr(parent, "get_bip85_child_mnemonic", lambda *args: pytest.fail("Electrum cannot derive BIP85"))
    storage = SeedStorage()
    storage.seeds = [parent, child]

    assert storage.get_bip85_parent(child) is None


@pytest.mark.parametrize("invalid_origin", [
    (None, 0, 12), (PARENT_FINGERPRINT, None, 12), (PARENT_FINGERPRINT, 0, None),
    ("bad", 0, 12), ("zzzzzzzz", 0, 12), (12345678, 0, 12),
    (PARENT_FINGERPRINT, -1, 12), (PARENT_FINGERPRINT, 2**31, 12),
    (PARENT_FINGERPRINT, True, 12), (PARENT_FINGERPRINT, "0", 12),
    (PARENT_FINGERPRINT, 0, 18), (PARENT_FINGERPRINT, 0, 24),
])
def test_incomplete_or_invalid_origin_cannot_resolve_parent(invalid_origin, monkeypatch):
    parent = Seed(MNEMONIC, "TREZOR")
    child = child_seed(origin=invalid_origin)
    storage = SeedStorage()
    storage.seeds = [parent, child]
    monkeypatch.setattr(parent, "get_bip85_child_mnemonic", lambda *args: pytest.fail("Invalid origin must not derive"))

    assert not storage.has_complete_bip85_origin(child)
    assert storage.get_bip85_parent(child) is None


def test_parent_edit_discard_and_reload_never_retain_a_hidden_parent():
    parent = Seed(MNEMONIC, "TREZOR")
    child = child_seed(passphrase="child extension")
    storage = SeedStorage()
    storage.seeds = [parent, child]
    assert storage.get_bip85_parent(child) is parent
    reference = weakref.ref(parent)

    changed = Seed(MNEMONIC, "different deriving wallet")
    storage.replace_seed(parent, changed)
    assert storage.get_bip85_parent(child) is None
    del parent
    gc.collect()
    assert reference() is None
    storage.seeds.remove(changed)
    assert storage.get_bip85_parent(child) is None

    reloaded = Seed(MNEMONIC, "TREZOR")
    storage.add_seed(reloaded)
    assert storage.get_bip85_parent(child) is reloaded
    assert origin(child) == (PARENT_FINGERPRINT, 0, 12)


@pytest.mark.parametrize("existing_origin,incoming_origin,expected_origin", [
    ((None, None, None), (PARENT_FINGERPRINT, 0, 12), (PARENT_FINGERPRINT, 0, 12)),
    ((PARENT_FINGERPRINT, None, None), (PARENT_FINGERPRINT, 0, 12), (PARENT_FINGERPRINT, 0, 12)),
    ((PARENT_FINGERPRINT, 0, None), (PARENT_FINGERPRINT, 0, 12), (PARENT_FINGERPRINT, 0, 12)),
    ((PARENT_FINGERPRINT.upper(), None, None), (PARENT_FINGERPRINT, 0, 12), (PARENT_FINGERPRINT, 0, 12)),
    ((PARENT_FINGERPRINT.upper(), 0, 12), (PARENT_FINGERPRINT, 0, 12), (PARENT_FINGERPRINT.upper(), 0, 12)),
    ((PARENT_FINGERPRINT, None, None), ("01020304", 1, 12), (PARENT_FINGERPRINT, None, None)),
    ((PARENT_FINGERPRINT, 1, None), (PARENT_FINGERPRINT, 0, 12), (PARENT_FINGERPRINT, 1, None)),
    ((PARENT_FINGERPRINT, None, 12), (PARENT_FINGERPRINT, 0, None), (PARENT_FINGERPRINT, None, 12)),
    ((PARENT_FINGERPRINT, 0, 12), ("01020304", 1, 12), (PARENT_FINGERPRINT, 0, 12)),
])
def test_canonical_origin_is_merged_as_one_compatible_tuple(existing_origin, incoming_origin, expected_origin):
    canonical = child_seed(origin=existing_origin)
    incoming = child_seed(origin=incoming_origin)
    storage = SeedStorage()
    storage.seeds = [canonical]

    assert storage.add_seed(incoming) is canonical
    assert origin(canonical) == expected_origin
    assert origin(incoming) == incoming_origin
    assert len(storage.seeds) == 1


@pytest.mark.parametrize("replacement_origin", [(None, None, None), ("01020304", 7, 12)])
def test_passphrase_clone_keeps_original_complete_origin(replacement_origin):
    original = child_seed()
    replacement = child_seed(passphrase="new child extension", origin=replacement_origin)
    storage = SeedStorage()
    storage.seeds = [original]

    assert storage.replace_seed(original, replacement) is replacement
    assert origin(replacement) == (PARENT_FINGERPRINT, 0, 12)
    assert origin(original) == (PARENT_FINGERPRINT, 0, 12)
    assert not original.has_passphrase


def test_equivalent_replacement_can_complete_legacy_child_origin_without_replacing_instance():
    canonical = child_seed(origin=(PARENT_FINGERPRINT, None, None))
    replacement = child_seed()
    storage = SeedStorage()
    storage.seeds = [canonical]

    assert storage.replace_seed(canonical, replacement) is canonical
    assert storage.has_complete_bip85_origin(canonical)
    assert origin(canonical) == (PARENT_FINGERPRINT, 0, 12)


@pytest.mark.parametrize("already_loaded", [False, True])
def test_sibling_replacement_keeps_new_index_instead_of_original_child_index(already_loaded):
    parent = Seed(MNEMONIC, "TREZOR")
    original = child_seed(passphrase="old child extension")
    words = parent.get_bip85_child_mnemonic(1, 12).split()
    sibling = child_seed(words, origin=(PARENT_FINGERPRINT, 1, 12))
    canonical = Seed(words)
    storage = SeedStorage()
    storage.seeds = [parent, original]
    if already_loaded:
        storage.seeds.append(canonical)

    selected = storage.replace_seed(original, sibling)

    assert selected is (canonical if already_loaded else sibling)
    assert origin(selected) == (PARENT_FINGERPRINT, 1, 12)
    assert storage.get_bip85_parent(selected) is parent
    assert storage.seeds[0] is parent
    assert len(storage.seeds) == 2
    assert original.passphrase == "old child extension"
    assert origin(original) == (PARENT_FINGERPRINT, 0, 12)


def test_sibling_canonical_complete_origin_wins_without_grafting_original_index():
    parent = Seed(MNEMONIC, "TREZOR")
    original = child_seed()
    words = parent.get_bip85_child_mnemonic(1, 12).split()
    sibling = child_seed(words, origin=(PARENT_FINGERPRINT, 1, 12))
    canonical = child_seed(words, origin=("01020304", 9, 12))
    storage = SeedStorage()
    storage.seeds = [original, canonical]

    assert storage.replace_seed(original, sibling) is canonical
    assert origin(canonical) == ("01020304", 9, 12)
    assert len(storage.seeds) == 1


def test_replacing_child_with_unrelated_mnemonic_does_not_copy_origin_or_marker():
    original = child_seed()
    replacement = Seed(MNEMONIC)
    storage = SeedStorage()
    storage.seeds = [original]

    assert storage.replace_seed(original, replacement) is replacement
    assert origin(replacement) == (None, None, None)
    assert not replacement.is_bip85_child
