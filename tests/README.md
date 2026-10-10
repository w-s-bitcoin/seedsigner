# Running Tests

The tests are designed to be run on non-Raspi hardware.

## Setup
On your testing machine you'll have to install:
```bash
# general dependencies
pip3 install -r requirements.txt

# test suite dependencies
pip3 install -r tests/requirements.txt
```

Then make the `seedsigner` python module visible/importable to the tests by installing it:
```
pip3 install -e .
```

## Running all tests, calculating overall test coverage
tldr: just run the convenience script from the project root:

```bash
./tests/run_full_coverage.sh
```

## Running tests manually
Run the whole test suite:
```
pytest
```

Run a specific test file:
```
pytest tests/test_this_file.py
```

Run a specific test:
```
pytest tests/test_this_file.py::test_this_specific_test
```

Force pytest to show logging output:
```bash
pytest tests/test_this_file.py::test_this_specific_test -o log_cli=1

# or (same result)

pytest tests/test_this_file.py::test_this_specific_test --log-cli-level=DEBUG
```

Annoying complications:
* If you want to see `print()` statements that are in a test file, add `-s`
* Better idea: use a proper logger in the test file and use one of the above options to display logs


## Screenshot generator
The screenshot generator is meant to mostly be a utility and not really part of the test suite. However,
it is actually implemented to be run by `pytest`.

see: [Screenshot generator README](screenshot_generator/README.md)

## Interactive passphrase, LifeHash and BIP-85 preview

After installing the dependencies above, compile the translation catalogs and run:

```bash
pip install -r l10n/requirements-l10n.txt
python setup.py compile_catalog
python tools/passphrase_preview.py
```

Open `http://127.0.0.1:8765` to exercise the real passphrase Views and Screens with
emulated hardware buttons. The preview uses the public `abandon` test mnemonic,
does not persist settings, and only enables navigation relevant to this feature.
Never enter a real seed or passphrase into the preview. Use **Save screen** to
capture the current 240x240 display, or generate the sample screens with:

```bash
python tools/passphrase_preview.py --screenshots /tmp/passphrase-screenshots
```

The generated gallery also covers the seed list, finalization, the initial
passphrase review, discard confirmation, and a five-key multisig descriptor
across two pages. LifeHashes follow Blockchain Commons' C++ v2 reference.
Add/edit reviews show the wallet without a passphrase and the proposed wallet
side by side, each with its full fingerprint, and label the passphrase below.
Both review flows show 44 passphrase characters per page. Removal shows the
destination wallet. A loaded seed's header shows its current fingerprint beside
its LifeHash; when it has a passphrase, the original LifeHash and an arrow appear
before the current one.

For a loaded seed, **Continue** after the passphrase review opens **Load Wallet**:
choose **Replace current**, **Load separately**, or **Cancel**. Loading separately
keeps the original wallet available in **In-Memory Seeds**. The **Review “aaa”,
then choose how to load** demo starts at this review. The generated gallery also
shows the choice and the two wallet entries after loading separately. Removing a
passphrase retains its direct removal confirmation.

The BIP-85 demo scenarios start child derivation from the public seed, with or
without its demo passphrase. Select 12 or 24 words and a child index to review the
parent and child identities. Child-word pages keep the parent-to-child LifeHash
header, child fingerprint and index/page label visible while showing three words
at a time. After the words, choose **Verify & load** or **Load child**. The child
loads as a separate wallet while its parent stays in memory. Passphrase changes
from the child's menu apply to that child's mnemonic, using its own fingerprint
without a passphrase as the review baseline. The **Loaded BIP-85 child (parent
retained)** scenario starts at this child menu. BIP-85 is enabled only in the
preview's temporary settings, and its setting can be changed through the menus.
For a loaded child, **BIP-85 child seed** opens **Change child index** and
**Derive new child**. Changing the index uses the original parent and word count,
prefills the current index, and offers **Replace current** or **Load separately**
after reviewing and backing up the sibling. Deriving a new child uses the selected
child itself as the parent.
Use **Change child index (parent retained)** to exercise sibling replacement or
separate loading, **Derive from a loaded child** for grandchild derivation, and
**Change index with parent unloaded** for the parent-needed notice. The gallery
also covers prefilled index entry, sibling review/loading, grandchild loading,
and notices for missing parent or origin details.
The seed menu marks a known BIP-85 child in blue and an active passphrase in the
same color as the passphrase text in its confirmation screen. Arrows and checks
share these colors. Selected arrows and checks use small black backgrounds so
their colors remain visible on the selected row. Both checks appear for a child
with a passphrase.

The **In-Memory Seeds: wallet relationships** scenario shows a plain seed, a
passphrased seed, a BIP-85 child and a passphrased child together. Their rows use
20px LifeHashes connected by arrows and show only the final wallet's full
fingerprint. A passphrased child shows its deriving parent, the child without a
passphrase and the current wallet. The parent fingerprint is retained as display
metadata; no parent secret is kept inside the child.

A loaded child's seed-menu header retains its actual deriving-parent LifeHash,
connected to the child by a blue arrow. With its own passphrase, the child header
adds a yellow arrow and a third LifeHash; the final fingerprint uses 16px type so
the entire chain fits beside Back. The two additional passphrased-parent demo
scenarios exercise these headers using the actual child-loading operation.

On a device, **Settings → Advanced → BIP-39 passphrase** controls passphrase
support. **Enabled** or **Required** exposes **BIP-39 Passphrase** near the bottom
of a loaded BIP-39 seed's menu; **Disabled** hides it. Electrum custom extensions
are unchanged.


## Generate coverage manually
Run tests and generate test coverage
```bash
coverage run -m pytest
```

The screenshots can generate their own separate coverage report:
```bash
coverage run -m pytest tests/screenshot_generator/generator.py --locale es
```

Show the resulting test coverage details:
```bash
coverage report
```

Generate the interactive html report:
```bash
coverage html
```
