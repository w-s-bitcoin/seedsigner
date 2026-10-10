# LifeHash fingerprint icons

SeedSigner renders LifeHash v2 beside the public BIP-32 master fingerprint
(XFP). The compatibility target is **Blockchain Commons' C++ reference at
commit `0444dbed5615fbc9a98163608c6499c025b7873b`**, including its floating-point
rounding behavior. Other LifeHash implementations differ at some boundaries,
so a single image cannot always match every port. Sparrow and EntropyLab are
comparison implementations, not alternative rendering targets.

## Input and rendering contract

The input is exactly eight hexadecimal digits, decoded into four bytes in
displayed order. For example, `73c5da0a` becomes `73 c5 da 0a`, with no byte
reversal. It is not the eight-character UTF-8 string and does not include a
seed, private key, or passphrase. Uppercase and lowercase inputs are equivalent;
leading zero bytes are retained.

This matches Sparrow's [`LifeHashIcon.setHex`](https://github.com/sparrowwallet/sparrow/blob/0340cdbe86b2b773a9a11c030378b3c44cbd00cb/src/main/java/com/sparrowwallet/sparrow/control/LifeHashIcon.java#L67-L69)
and its call to [`makeFromData(data, VERSION2, 1, false)`](https://github.com/sparrowwallet/sparrow/blob/0340cdbe86b2b773a9a11c030378b3c44cbd00cb/src/main/java/com/sparrowwallet/sparrow/control/LifeHashIcon.java#L35-L38).
`makeFromData` hashes the bytes with SHA-256. LifeHash v2 hashes that digest
again to initialize its 16×16 Game of Life grid; palette and symmetry selection
use the first digest. The resulting base image is 32×32 RGB without alpha.

The helper uses nearest-neighbor scaling for other display sizes. Compatibility
checks compare the original 32×32 RGB pixels, before display resizing, borders,
or rounded corners. Sparrow itself subsequently resizes its icon to 24×24.

Passphrase review places two identities horizontally with a right-pointing
arrow: first the mnemonic's wallet **without a passphrase**, then the candidate
wallet. Each identity has a 20px LifeHash beside its 16px hexadecimal fingerprint.
The first identity remains the unpassphrased baseline when editing an already
passphrased loaded wallet; it does not represent that wallet's current
passphrase. The baseline is derived from a separate seed object with the same
mnemonic and wordlist, without mutating the loaded source or candidate. The
shared helper preserves the seed type, including Electrum derivation rules in
initial finalization/review; loaded-passphrase editing remains BIP-39 only.
Model tests cover source identity preservation on mainnet, testnet, and regtest.

An explicit **Passphrase** label appears above the highlighted passphrase text.
Both initial and loaded-wallet review show up to two 22-character lines per
page (44 characters total). Initial loading offers **Done** only on the final
page; loaded-wallet review offers **Continue** only on the final page.
In loaded-wallet review, **Continue** (or **Next** on earlier pages) is the
first and default action, followed by **Edit passphrase** and **Cancel**.

For a nonempty passphrase, Continue opens **Load Wallet** with **Replace
current** selected by default, **Load separately**, and **Cancel**. Replacement
changes the selected stored wallet. Separate loading preserves that wallet
and selects an additional passphrase variant, or its existing canonical
full-seed-bytes match. Both paths retain any unrelated pending seed and, when
editing a child wallet, its BIP-85 parent. Committing a different wallet clears
prior signing/address state and navigation history. **Back** from Load Wallet
returns to the previous review page with the same candidate and passphrase
intact; **Cancel** discards the draft and returns to the original seed menu.
Neither action changes the stored original. Removal retains
its direct, Cancel-first confirmation and shows only the destination without
a passphrase. These display identities do not participate in storage
replacement or duplicate detection.

Each relationship display contains at most two LifeHashes: the immediate
source and destination for the relationship being shown. The loaded seed's
main menu prioritizes the current passphrase relationship. Any seed with a
passphrase, including a BIP-85 child, shows its own wallet without a passphrase
→ current wallet with a yellow arrow. Otherwise, a known BIP-85 child shows
its actual deriving parent's snapshot → child with a blue arrow. A plain seed
or a child without a known parent snapshot shows only its current LifeHash.

The parent snapshot includes any passphrase used for derivation. It remains
stored when a child has its own passphrase, even though the header displays
only the child's passphrase relationship. Removing that passphrase restores
the parent → child display. An absent snapshot never invents a parent step.

Only the current hexadecimal fingerprint is written. All header LifeHashes
and fixed-width XFP text remain 20px, with the full eight digits fitting beside
Back on the 240px display. This header does not change seed metadata,
derivation, or selection.

The menu uses checks to show the selected seed's state. **BIP-85 child seed**
has a blue check when this seed is a known derived child; **BIP-39 Passphrase**
uses the shared passphrase yellow (`#FFE20E`, `PASSPHRASE_COLOR`) when
this seed currently has a passphrase. A parent is not marked
as a child merely because it has derived one. The existing settings still
control whether each menu action is shown.

The **In-Memory Seeds** list uses the same limit and passphrase priority as
the loaded-seed header. Each row shows one LifeHash or one source → destination
pair. Only the current fingerprint is written as hexadecimal text:

| Loaded seed | LifeHash sequence |
| --- | --- |
| Ordinary seed | Current wallet |
| Ordinary seed with a passphrase | Without passphrase → current wallet |
| Known BIP-85 child | Deriving parent → current child |
| Known BIP-85 child with a passphrase | Child without passphrase → current child |

Arrows use the same semantic colors as the menu checks: the shared
passphrase yellow (`#FFE20E`) marks a passphrase step, while blue marks
a BIP-85 parent-to-child derivation. A passphrased-child row has one yellow
arrow. The convention also applies to passphrase review, the loaded-seed
header, BIP-85 review, and the persistent child-word header. BIP-85 review and
child-word pages always show the actual deriving parent → child, including
when that parent is itself a passphrased child. Labels, sequence positions, and hexadecimal
fingerprints remain available; LifeHash pixels are unchanged. Unrelated
success and verification checks retain their existing green color.
Selected rows keep these exact colors. Compact black backings behind the
arrows and semantic checkmarks keep them visible against the orange selection
background without recoloring the symbols or LifeHash images.

The initial and loaded-passphrase review text uses the same `#FFE20E` yellow.
Those two fields opt into `TextArea.preserve_font_color`: their glyph coverage
is resized and sharpened in grayscale before compositing the chosen text
color. Sharpening RGB glyphs directly had shifted the visible text color away
from the configured arrow color. The coverage-mask path preserves the shared
color while retaining antialiased edges; other text rendering is unchanged.

Rows use 20px LifeHashes, 20px fixed-width fingerprint text, and 10px gaps
on each side of an arrow. Both roles in a source → destination pair remain
visible even if their 32-bit fingerprints happen to be equal; matching XFPs
do not prove matching wallets.

The parent image uses its fingerprint at child creation, including any
passphrase used for derivation. Discarding or later editing the loaded parent
does not change the child's recorded origin. If no parent fingerprint is
known, a child without its own passphrase shows only its current LifeHash.
Choosing any row opens its current wallet.

Back from a loaded seed's menu returns to **In-Memory Seeds**, including when
only one seed is loaded. Back from that list returns to the main menu. Leaving
a wallet clears its workflow state and history while preserving loaded seeds
and unrelated pending seed entry.

Discarding a loaded seed returns to **In-Memory Seeds** with that entry removed.
If no loaded seeds remain, it returns to the main menu. This applies equally to
ordinary seeds, passphrased wallets, and BIP-85 children. Discard clears prior
wallet and navigation state while preserving the other loaded seeds and any
unrelated pending seed.

The bounded cache contains only public fingerprint bytes and derived RGB bytes.
Each call returns a fresh image. The icon is a visual representation of the
same 32-bit fingerprint, not an additional independent identifier.

## BIP-85 parent and child identities

After selecting a child index, a review screen shows **Parent → Child** with
both LifeHashes and hexadecimal fingerprints, plus the index and word count.
The parent is the actual loaded wallet, including its current passphrase.
Unlike passphrase review, this first identity is not the unpassphrased baseline.

BIP-85 derives fresh entropy from the selected BIP-32 root using a fully
hardened path. For the English BIP-39 application the path is
`m/83696968'/39'/0'/{words}'/{index}'`; the application converts the resulting
entropy into the child's mnemonic. See the [BIP-85 specification](https://github.com/bitcoin/bips/blob/master/bip-0085.mediawiki#specification)
and its [BIP-39 application](https://github.com/bitcoin/bips/blob/master/bip-0085.mediawiki#bip39).

The displayed child identity is computed by restoring that mnemonic as a new
BIP-39 seed **with an empty passphrase**, then calculating its own BIP-32 master
fingerprint. It does not inherit the parent's passphrase and is not the
fingerprint of the intermediate hardened derivation node. This follows
[BIP-39's mnemonic-to-seed conversion](https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki#from-mnemonic-to-seed)
and [BIP-32's key-identifier definition](https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki#key-identifiers).

Choosing **View seed words** continues through the existing private-word
warning and backup workflow. Every child-word page retains the parent LifeHash
→ child LifeHash header, the child's hexadecimal fingerprint, and a child-index
and page label. Child words appear three per page: four pages for 12 words or
eight pages for 24 words. Ordinary seed-word pages keep four words per page.

After the last word page, **Verify & load** starts the backup-word check;
**Load child** continues directly. Successful verification also ends
with an explicit **Load child** action. Loading adds the derived child as a
separate seed with an empty passphrase, or selects its canonical stored
instance if the full derived seed bytes already match a loaded wallet. The
parent remains loaded and unchanged, and any unrelated pending seed is
preserved. The child becomes the selected seed. Prior signing, address,
resume-flow, and navigation state is cleared before its menu opens.

A known child's **BIP-85 child seed** action opens a submenu with **Change
child index** and **Derive new child**. Changing the index keeps the original
word count and prefills the recorded index. It resolves the original parent
from the currently loaded seeds, then derives a sibling from that parent's
wallet, including the passphrase originally used for derivation. Selecting the
unchanged index returns to the existing child unchanged, preserving its own
passphrase.

A different index produces a new sibling with no passphrase of its own. The
original child remains loaded during identity review, word review, and backup
verification. After **Load child**, **Replace current** is selected by default;
**Load separately** keeps both siblings, and **Cancel** returns to the original
child without loading the candidate. **Back** returns to the preceding backup
prompt or success page. Both commit options recheck the loaded source child,
verified parent, and complete candidate derivation immediately before storage
changes; duplicate selection still uses full derived seed bytes.

**Derive new child** instead uses the selected child's current wallet,
including its own passphrase, as the parent of a new generation. It offers the
ordinary word-count and index choices and loads the resulting grandchild
separately. It does not require the selected child's original parent to remain
loaded.

The child's **BIP-39 Passphrase** action uses the ordinary loaded-seed editor.
Its candidate uses only the child mnemonic and does not edit the parent or
change the child's BIP-85 derivation. Its review shows the child mnemonic
without a passphrase → the child with the proposed passphrase. **Replace
current** replaces the selected child wallet; **Load separately** retains the
original child and loads the variant alongside it. Cancelling leaves both
child and parent unchanged. The existing passphrase setting
continues to control whether this menu action is available.

Session metadata records whether the seed is a known child and an optional
origin tuple: `bip85_parent_fingerprint`, `bip85_child_index`, and
`bip85_num_words`. The fingerprint snapshots the deriving parent's public
identity, including its passphrase; a parent snapshot implies child status.
Loading a derived child sets all three fields, and child passphrase changes
preserve them. The metadata contains no parent Seed object, mnemonic,
passphrase, or private key, so the parent can be discarded independently.
An ordinary mnemonic import alone cannot infer BIP-85 provenance.

When a full-seed-bytes match reuses a canonical loaded wallet, its existing
complete origin takes precedence. Partial metadata can be filled only from a
complete, compatible tuple; fields from unrelated origins are never combined.
For a passphrase change, the original mnemonic's origin takes precedence over
the candidate's. A replacement sibling has a different mnemonic and keeps its
own new index, without inheriting the old child's origin. The row records one
observed derivation route; it is not proof of a unique parent. Neither metadata
nor a 32-bit fingerprint participates in wallet equality or duplicate detection.

An index change requires complete supported origin metadata and exactly one
verified, currently loaded parent. The fingerprint only narrows the candidates:
each candidate must reproduce the child's complete mnemonic at the recorded
index and word count, ignoring the child's own passphrase. Missing, changed,
or ambiguous parents cannot authorize an index change. **Parent Needed** asks
for the original parent with its original passphrase; **Origin Unavailable**
explains when derivation metadata is missing. Both return to the original
child's menu and clear stale derivation history. **Derive new child** remains
available through the submenu. No parent reference is cached in the child.

Navigation arguments carry the parent seed object, child index, and word
count while deriving and reviewing; they do not include child mnemonic
strings or private bytes. After loading, wallet actions receive the stored
child object. The live preview runs these same application views for both
unpassphrased and passphrased public demonstration parents.

## Pinned reference sources

| Implementation | Revision | Role |
| --- | --- | --- |
| [Sparrow Wallet](https://github.com/sparrowwallet/sparrow/tree/0340cdbe86b2b773a9a11c030378b3c44cbd00cb) | `0340cdbe86b2b773a9a11c030378b3c44cbd00cb` | Fingerprint input and UI conventions |
| [Toucan 0.9.0](https://github.com/sparrowwallet/toucan/tree/0ab8d422c584e5bbf731b0408c194394b38c082f) | `0ab8d422c584e5bbf731b0408c194394b38c082f` | Independent Sparrow RGB comparison |
| [Toucan reference fixes](https://github.com/w-s-bitcoin/toucan/tree/ea3958dabb00ac203a025fe9fb1fbf4b9ba0c78f) | `ea3958dabb00ac203a025fe9fb1fbf4b9ba0c78f` | Corrected-port comparison and independent C++ numeric fixtures |
| [EntropyLab](https://github.com/OogaBoogaX/entropylab/blob/775aa087727e86c345c26deb4d63e28d510fafd8/src/js/lifehash.js) | `775aa087727e86c345c26deb4d63e28d510fafd8` | Independent JavaScript comparison |
| [Blockchain Commons C++ reference](https://github.com/BlockchainCommons/bc-lifehash/tree/0444dbed5615fbc9a98163608c6499c025b7873b) | `0444dbed5615fbc9a98163608c6499c025b7873b` | Algorithm source, exact numerical behavior, and independent RGB oracle |

The implementation retains the C++ reference's BSD-2-Clause-Patent license
in `src/seedsigner/resources/licenses/`. Sparrow/Toucan and EntropyLab were
executed as independent comparison implementations. EntropyLab's source was
not copied into SeedSigner.

## Why implementations sometimes disagree

The historical comparison below uses Toucan 0.9.0 bundled with Sparrow 2.5.4
and the pinned EntropyLab revision. It does not describe every later release
or port. All compared implementations use the same public input and LifeHash
version. The observed discrepancies occur during color interpolation, after
hashing and Game of Life processing.

**Gradient boundaries.** Toucan 0.9.0 uses a direct double-precision
[`dividend % divisor`](https://github.com/sparrowwallet/toucan/blob/0ab8d422c584e5bbf731b0408c194394b38c082f/src/main/java/com/sparrowwallet/toucan/impl/Utils.java#L29-L31).
EntropyLab uses
[`((a % b) + b) % b`](https://github.com/OogaBoogaX/entropylab/blob/775aa087727e86c345c26deb4d63e28d510fafd8/src/js/lifehash.js#L191).
The C++ reference uses the same two-remainder construction with
[`fmodf`, which rounds its arguments to single precision](https://github.com/BlockchainCommons/bc-lifehash/blob/0444dbed5615fbc9a98163608c6499c025b7873b/src/numeric.hpp#L34-L36).

For example, a normalized value of `0.49999999999999994` in a three-color
gradient yields segment `0` and a segment position of `0.9999999999999999`.
Sparrow preserves a fraction almost equal to `1`, selecting a color almost
equal to the middle color. In EntropyLab, adding `1` rounds that value to
exactly `2`; the second remainder then becomes `0`, selecting the first color
instead. C++ can also round the fraction to `0` through `fmodf`. The segment
index was already selected before this rounding, creating a discontinuity.
See the segment selection in [Toucan](https://github.com/sparrowwallet/toucan/blob/0ab8d422c584e5bbf731b0408c194394b38c082f/src/main/java/com/sparrowwallet/toucan/impl/ColorFunc.java#L44-L50),
[EntropyLab](https://github.com/OogaBoogaX/entropylab/blob/775aa087727e86c345c26deb4d63e28d510fafd8/src/js/lifehash.js#L215-L219),
and [C++](https://github.com/BlockchainCommons/bc-lifehash/blob/0444dbed5615fbc9a98163608c6499c025b7873b/src/color-func.cpp#L34-L40).

**Palette precision.** Toucan 0.9.0 first divides its integer RGB palette channels
by 255 using [single-precision `float`](https://github.com/sparrowwallet/toucan/blob/0ab8d422c584e5bbf731b0408c194394b38c082f/src/main/java/com/sparrowwallet/toucan/impl/Color.java#L16-L18),
then performs interpolation in double precision. EntropyLab uses
[double precision throughout this step](https://github.com/OogaBoogaX/entropylab/blob/775aa087727e86c345c26deb4d63e28d510fafd8/src/js/lifehash.js#L202-L205).
This can change a final 8-bit channel by one level. In a controlled comparison
for `e3aa047b`, changing only EntropyLab's palette construction to single
precision reproduced Sparrow's output; changing only its modulo did not.

These are rendering differences. They do not change the fingerprint, seed,
derived keys, or addresses.

## What the reference comparison establishes

Neither historical port is universally byte-identical to the pinned C++
reference. For the 14 fingerprints where Sparrow and EntropyLab differed in the
sample below, the C++ reference agreed with EntropyLab in the 13 gradient-boundary
cases and with Sparrow in the one single-level color case. Additional cases
showed the C++ reference differing from both ports; the two rows below are
examples, not an exhaustive list. Full-sample totals are recorded below.

| Fingerprint(s) | Observed difference | C++ reference agrees with |
| --- | --- | --- |
| `106eb272` | 8 of 1,024 pixels differ between Sparrow and EntropyLab | EntropyLab |
| `2e5cfa4f` | 24 pixels differ | EntropyLab |
| `e7f7c744`, `f8bff277`, `0319808f`, `ffa2f9de`, `9671946e`, `41acd1f3`, `243ef557`, `0bbfab27`, `de9c04d7`, `0107118e`, `aee2215e` | Other gradient-boundary cases | EntropyLab |
| `e3aa047b` | 12 pixels differ by one channel level | Sparrow |
| `a68bbd2f`, `a5f29c5c` | Sparrow and EntropyLab agree; C++ differs in 4 pixels for each | Neither port |

At the demonstrated gradient boundary, Sparrow's remainder preserves the
mathematically expected continuous interpolation, while the reference has a
rounding artifact. That does not make Sparrow reference-conformant. SeedSigner
intentionally reproduces the pinned C++ reference, including that artifact;
substituting a smoother interpolation would change its output. The helper
therefore emulates the reference's single-precision `fmodf`, `powf`, and `sqrtf`
operations and its double-precision palette construction. See
[C++ palette and luminance arithmetic](https://github.com/BlockchainCommons/bc-lifehash/blob/0444dbed5615fbc9a98163608c6499c025b7873b/src/color.cpp#L26-L46).

The numerical target uses separate floating-point operations, reproduced in
C++ with `-ffp-contract=off` and without fast-math. Fused multiply-add (FMA)
contraction can change intermediate results: white luminance is
`0x1.564cdep-1` with separate rounding but can become `0x1.564cdcp-1` with
contraction. The compared image outputs were unchanged; this does not establish
bitwise parity for every input or compiler configuration. See the
[pinned numeric fixture and build notes](https://github.com/w-s-bitcoin/toucan/blob/ea3958dabb00ac203a025fe9fb1fbf4b9ba0c78f/tools/lifehash-reference/README.md#c-build).

The reviewed [Toucan PR](https://github.com/w-s-bitcoin/toucan/pull/1) adopts
the same double-precision palette and float32 modulo/luminance behavior at the
pinned revision above. SeedSigner matched all 4,112 applicable committed C++
image fixtures. It also matched all 300 earlier differing fingerprints against
both archived C++ and corrected Toucan output. The PR's VERSION1 hue-sector fix
does not apply to this v2-only helper. These results do not imply that an
installed Sparrow release already contains the PR.

## Validation and limits

The independent oracle executed the original compiled Toucan module bundled
with Sparrow 2.5.4 in an isolated headless JVM. A separate run evaluated the
pinned EntropyLab JavaScript source under Node.js with WebCrypto. The C++
reference was compiled on macOS arm64 with Apple Clang 21 and the upstream
`tasks.sh` flags (`-O3 -std=c++17 -stdlib=libc++
-fdiagnostics-absolute-paths`). A second build with `-O2 -ffp-contract=off`
produced identical RGB bytes for all 4,111 inputs. SeedSigner code did not
generate the expected RGB values.

The comparison set contained 15 named and boundary fingerprints, including
`73c5da0a`, `a63dbf9c`, `9a6087a6`, all-zero/all-one bytes, and leading zeros,
plus 4,096 deterministic samples. Sample `i` was the first four bytes of
`SHA256(UTF8("SeedSigner LifeHash public test fingerprint " + str(i)))`, for
`i = 0..4095`.

SeedSigner's final helper matched the compiled C++ reference byte-for-byte for
all **4,111** inputs. The historical external implementations compared as follows:

| Sample outcome | Fingerprints |
| --- | ---: |
| All three agree | 4,057 |
| Reference and EntropyLab agree; Sparrow differs | 13 |
| Reference and Sparrow agree; EntropyLab differs | 1 |
| Sparrow and EntropyLab agree; reference differs | 40 |

Thus Sparrow and EntropyLab agreed on 4,097 inputs, the reference and EntropyLab
on 4,070, and the reference and Sparrow on 4,058. `a68bbd2f` and `a5f29c5c` are
two examples from the 40-case final row. These counts describe this particular
sample, not a measured rate for all possible fingerprints or a proof covering all 2^32 inputs.

`tests/test_lifehash.py` pins 33 independently generated C++ reference RGB
SHA-256 values covering all four gradient families, both symmetry patterns,
leading zeros, and known numerical edge cases. Seven additional exact-bit
numeric cases pin three luminance results and four modulo boundaries from the
independent C++ fixtures. The 64 helper tests also cover input validation,
scaling, independent returned images, and bounded public-data caching.

The BIP-85 index-change flow tests cover both word
counts, unchanged-index preservation, sibling replacement/separate loading,
grandchild derivation with the child's passphrase, backup navigation, stale
parent/source rejection, and duplicate selection.

For the current two-LifeHash presentation, all 584 non-screenshot tests passed
and the preview generated 50 native gallery PNGs. The regression tests cover
passphrase priority in headers and in-memory rows, the two-role limit even for
longer input sequences, equal-fingerprint roles, arrow colors, and the full 20px
XFP fitting beside Back.

Before the two-LifeHash display limit was introduced, the complete
non-screenshot suite and all 22 screenshot locales were validated. Screenshot
generation produced 3,520 PNGs, with 198 supplemental captures and 50 native
gallery captures. That earlier revision's native captures and live browser
verified the passphrased parent and child relationships, full current XFP
visibility, and **Continue** first and selected by default. Back from **Load Wallet**
restored **Change Wallet** with the demonstration passphrase `aaa` intact and
Continue selected; storage still contained only the original `73c5da0a` wallet. The live preview confirmed
matching yellow passphrase text and symbols, then **Continue → Load Wallet**
with **Replace current** selected by default. Choosing **Load separately** for
the demonstration passphrase `aaa` retained `73c5da0a` and loaded `382af2cb`;
both appeared in **In-Memory Seeds** with the yellow relationship arrow.
Normal and selected relationship rows and the child menu were also checked
in that revision, with in-memory rows checked across all 22 locales. These
historical checks describe the earlier layout; the current two-LifeHash
presentation has not been rerun across all 22 locales.

Cross-implementation comparisons must use the same four input bytes, v2,
module size 1, no alpha, and unscaled row-major RGB data.
