import re

from typing import List
from seedsigner.models.seed import Seed, ElectrumSeed, InvalidSeedException
from seedsigner.models.settings_definition import SettingsConstants



class SeedStorage:
    def __init__(self) -> None:
        self.seeds: List[Seed] = []
        self.pending_seed: Seed = None
        self._pending_mnemonic: List[str] = []
        self._pending_is_electrum : bool = False


    def set_pending_seed(self, seed: Seed):
        self.pending_seed = seed


    def get_pending_seed(self) -> Seed:
        return self.pending_seed


    def finalize_pending_seed(self) -> Seed:
        # Store the pending seed and return it
        seed = self.add_seed(self.pending_seed)
        self.pending_seed = None
        return seed


    def add_seed(self, seed: Seed) -> Seed:
        """Load a separate seed without disturbing pending mnemonic entry."""
        for loaded_seed in self.seeds:
            if loaded_seed == seed:
                # Compare full seed bytes and return the stored instance. Neither
                # fingerprints nor derivation relationships identify duplicates.
                self._merge_bip85_metadata(loaded_seed, loaded_seed, seed)
                return loaded_seed
        self.seeds.append(seed)
        return seed


    def clear_pending_seed(self):
        self.pending_seed = None


    def replace_seed(self, original: Seed, replacement: Seed) -> Seed:
        """Commit a reviewed wallet change and return the selected loaded instance."""
        # A stale View must not replace an equal seed that was loaded later.
        original_index = next((i for i, seed in enumerate(self.seeds) if seed is original), None)
        if original_index is None:
            raise ValueError("The selected seed is no longer loaded")

        if replacement == original:
            self._merge_bip85_metadata(original, original, replacement)
            return original

        # Seed equality compares the full derived seed bytes. A master fingerprint is
        # too short to safely decide whether two loaded wallets are the same.
        for seed in self.seeds:
            if seed == replacement:
                self._merge_bip85_metadata(seed, seed, original, replacement)
                del self.seeds[original_index]
                return seed

        self._merge_bip85_metadata(replacement, original, replacement)
        self.seeds[original_index] = replacement
        return replacement


    @staticmethod
    def has_complete_bip85_origin(seed: Seed) -> bool:
        """Whether public metadata fully specifies a supported child derivation."""
        return (
            isinstance(seed.bip85_parent_fingerprint, str)
            and re.fullmatch(r"[0-9a-fA-F]{8}", seed.bip85_parent_fingerprint) is not None
            and type(seed.bip85_child_index) is int
            and 0 <= seed.bip85_child_index < 2**31
            and type(seed.bip85_num_words) is int
            and seed.bip85_num_words in (12, 24)
            and seed.bip85_num_words == len(seed.mnemonic_list)
        )


    @classmethod
    def _merge_bip85_metadata(cls, target: Seed, *sources: Seed):
        """Preserve one compatible origin, never splice unrelated derivations."""
        origin = None
        complete_origin = False
        is_child = False
        for source in sources:
            # A sibling replaces a different mnemonic. Its old sibling's origin
            # and index must not be carried into the replacement.
            if source.mnemonic_list != target.mnemonic_list:
                continue
            is_child = is_child or source.is_bip85_child
            candidate = (source.bip85_parent_fingerprint, source.bip85_child_index, source.bip85_num_words)
            if not any(value is not None for value in candidate):
                continue
            if origin is None:
                origin = candidate
                complete_origin = cls.has_complete_bip85_origin(source)
            elif not complete_origin and cls.has_complete_bip85_origin(source) and all(
                    known is None or known == incoming
                    or (index == 0 and isinstance(known, str) and known.lower() == incoming.lower())
                    for index, (known, incoming) in enumerate(zip(origin, candidate))):
                # Fill partial metadata only from a complete compatible tuple.
                # A full canonical tuple is already fixed and cannot be changed.
                origin = candidate
                complete_origin = True

        target.is_bip85_child = is_child
        (target.bip85_parent_fingerprint, target.bip85_child_index, target.bip85_num_words) = origin or (None, None, None)


    def get_bip85_parent(self, child: Seed) -> Seed:
        """Resolve a loaded parent by full derivation, without retaining it."""
        if not self.has_complete_bip85_origin(child):
            return None
        parent = None
        for candidate in self.seeds:
            if not candidate.bip85_supported:
                continue
            if candidate.get_fingerprint().lower() != child.bip85_parent_fingerprint.lower():
                continue
            mnemonic = candidate.get_bip85_child_mnemonic(child.bip85_child_index, child.bip85_num_words).split()
            if mnemonic == child.mnemonic_list:
                if parent is not None:
                    # Never select an arbitrary parent if the loaded set is
                    # ambiguous, even when its public fingerprints match.
                    return None
                parent = candidate
        return parent


    def validate_mnemonic(self, mnemonic: List[str]) -> bool:
        try:
            Seed(mnemonic=mnemonic)
        except InvalidSeedException as e:
            return False
        
        return True


    def num_seeds(self):
        return len(self.seeds)
    

    @property
    def pending_mnemonic(self) -> List[str]:
        # Always return a copy so that the internal List can't be altered
        return list(self._pending_mnemonic)


    @property
    def pending_mnemonic_length(self) -> int:
        return len(self._pending_mnemonic)


    def init_pending_mnemonic(self, num_words:int = 12, is_electrum:bool = False):
        self._pending_mnemonic = [None] * num_words
        self._pending_is_electrum = is_electrum


    def update_pending_mnemonic(self, word: str, index: int):
        """
        Replaces the nth word in the pending mnemonic.

        * may specify a negative `index` (e.g. -1 is the last word).
        """
        if index >= len(self._pending_mnemonic):
            raise Exception(f"index {index} is too high")
        self._pending_mnemonic[index] = word
    

    def get_pending_mnemonic_word(self, index: int) -> str:
        if index < len(self._pending_mnemonic):
            return self._pending_mnemonic[index]
        return None
    

    def get_pending_mnemonic_fingerprint(self, network: str = SettingsConstants.MAINNET) -> str:
        try:
            if self._pending_is_electrum:
                seed = ElectrumSeed(self._pending_mnemonic)
            else:
                seed = Seed(self._pending_mnemonic)
            return seed.get_fingerprint(network)
        except InvalidSeedException:
            return None


    def convert_pending_mnemonic_to_pending_seed(self):
        if self._pending_is_electrum:
            self.pending_seed = ElectrumSeed(self._pending_mnemonic)
        else:
            self.pending_seed = Seed(self._pending_mnemonic)
        self.discard_pending_mnemonic()
    

    def discard_pending_mnemonic(self):
        self._pending_mnemonic = []
        self._pending_is_electrum = False
