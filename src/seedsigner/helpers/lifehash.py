"""LifeHash v2 icons for public BIP-32 master fingerprints.

Ported from Blockchain Commons' reference C++ implementation, commit
0444dbed5615fbc9a98163608c6499c025b7873b:
https://github.com/BlockchainCommons/bc-lifehash

Copyright © 2019 Blockchain Commons, LLC
SPDX-License-Identifier: BSD-2-Clause-Patent
The upstream license is in resources/licenses/bc-lifehash.txt.

Only v2 is implemented. Input is the four fingerprint bytes in displayed hex
order, matching Sparrow's LifeHashIcon; it is not the UTF-8 hex string or a
private seed. The cache contains only these public bytes and derived RGB bytes.

Numerical behavior follows the reference, including its float32 modulo and
luminance operations. Other ports can differ at gradient boundaries; we do not
substitute their numerical conventions, even when a boundary looks unusual.
"""

from functools import lru_cache
from hashlib import sha256
from math import fmod, sqrt
import re
from struct import pack, unpack

from PIL import Image


_FINGERPRINT = re.compile(r"[0-9a-fA-F]{8}")
_BLACK = (0.0, 0.0, 0.0)
_WHITE = (1.0, 1.0, 1.0)
_NEIGHBORS = tuple(
    tuple(((y + dy) % 16) * 16 + (x + dx) % 16
          for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
    for y in range(16) for x in range(16)
)


def _float32(value):
    return unpack("f", pack("f", value))[0]


# The reference constructs its palette with double-precision division.
_SPECTRUM = tuple(tuple(channel / 255.0 for channel in color) for color in (
    (0, 168, 222), (41, 60, 130), (210, 59, 130), (217, 63, 53),
    (244, 228, 81), (0, 158, 84), (0, 168, 222),
))


def _modulo(value):
    # Match numeric.hpp's fmodf(fmodf(value, 1) + 1, 1), including float32
    # argument rounding at each call. This can produce zero just below an
    # integer boundary; preserving that quirk is necessary for reference pixels.
    return fmod(_float32(fmod(_float32(value), 1.0) + 1.0), 1.0)


def _clamped(value):
    return max(min(value, 1.0), 0.0)


def _blend(first, second, fraction):
    fraction = _clamped(fraction)
    return tuple(_clamped(a * (1.0 - fraction) + b * fraction)
                 for a, b in zip(first, second))


def _gradient_color(colors, fraction):
    if len(colors) == 2:
        return _blend(colors[0], colors[1], fraction)
    if fraction >= 1.0:
        return colors[-1]
    if fraction <= 0.0:
        return colors[0]
    position = fraction * (len(colors) - 1)
    segment = int(position)
    return _blend(colors[segment], colors[segment + 1], _modulo(position))


def _luminance(color):
    # Match the reference's powf/sqrtf arithmetic. Luminance orders the colors;
    # it is not a general-purpose color-space conversion.
    squares = [_float32(_float32(weight * channel) ** 2)
               for weight, channel in zip((0.299, 0.587, 0.114), color)]
    return _float32(sqrt(_float32(_float32(squares[0] + squares[1]) + squares[2])))


class _Bits:
    def __init__(self, data):
        self.value = int.from_bytes(data, "big")
        self.remaining = len(data) * 8

    def take(self, count=1):
        self.remaining -= count
        return (self.value >> self.remaining) & ((1 << count) - 1)

    def fraction(self):
        return self.take(16) / 65535.0


def _select_gradient(entropy):
    family = entropy.take(2)
    hue = entropy.fraction()
    color = _gradient_color(_SPECTRUM, hue)

    if family == 0:  # Monochromatic
        is_tint = entropy.take()
        is_reversed = entropy.take()
        key_advance = entropy.fraction() * 0.3 + 0.05
        neutral_advance = entropy.fraction() * 0.3 + 0.05
        neutral = _WHITE if is_tint else _BLACK
        if is_tint:
            color = _blend(color, _BLACK, 0.5)
        colors = (_blend(color, neutral, key_advance),
                  _blend(neutral, color, neutral_advance))

    elif family in (1, 2):  # Complementary / triadic
        offsets = (0.5,) if family == 1 else (1.0 / 3.0, 2.0 / 3.0)
        colors = [color] + [_gradient_color(_SPECTRUM, _modulo(hue + offset))
                            for offset in offsets]
        lighter_advance = entropy.fraction() * 0.3
        darker_advance = entropy.fraction() * 0.3
        is_reversed = entropy.take()
        colors.sort(key=_luminance)
        darker = _blend(colors[0], _BLACK, darker_advance)
        lighter = _blend(colors[-1], _WHITE, lighter_advance)
        colors = (darker, lighter) if family == 1 else (lighter, colors[1], darker)

    else:  # Analogous
        colors = [color] + [_gradient_color(_SPECTRUM, _modulo(hue + offset / 12.0))
                            for offset in (1, 2, 3)]
        advance = entropy.fraction() * 0.5 + 0.2
        is_reversed = entropy.take()
        if _luminance(colors[0]) >= _luminance(colors[-1]):
            colors.reverse()
        colors = (_blend(colors[0], _BLACK, advance),
                  _blend(colors[1], _BLACK, advance / 2.0),
                  _blend(colors[2], _WHITE, advance / 2.0),
                  _blend(colors[3], _WHITE, advance))

    return colors, is_reversed


def _life_history(digest):
    # v2 hashes the data digest once more before seeding the 16x16 toroidal grid.
    cells = bytes((byte >> shift) & 1 for byte in sha256(digest).digest()
                  for shift in range(7, -1, -1))
    seen = set()
    last_alive = [0] * 256
    while len(seen) < 150 and cells not in seen:
        seen.add(cells)
        generation = len(seen)
        next_cells = bytearray(256)
        for index, alive in enumerate(cells):
            if alive:
                last_alive[index] = generation
            count = sum(cells[neighbor] for neighbor in _NEIGHBORS[index])
            next_cells[index] = count == 3 or (alive and count == 2)
        cells = bytes(next_cells)

    # Keep both normalization steps: combining them changes floating-point
    # rounding compared to FracGrid::overlay followed by the v2 normalization.
    fractions = [generation / len(seen) for generation in last_alive]
    minimum, maximum = min(fractions), max(fractions)
    return [(minimum - value) / (minimum - maximum) for value in fractions]


@lru_cache(maxsize=16)
def _fingerprint_rgb(fingerprint_bytes):
    digest = sha256(fingerprint_bytes).digest()
    fractions = _life_history(digest)
    entropy = _Bits(digest)
    entropy.take(2)  # v2 reserves two bits before selecting its palette.
    colors, is_reversed = _select_gradient(entropy)
    snowflake = entropy.take()
    pixels = bytearray(32 * 32 * 3)
    for index, fraction in enumerate(fractions):
        if is_reversed:
            fraction = 1.0 - fraction
        color = bytes(int(_clamped(channel) * 255)
                      for channel in _gradient_color(colors, fraction))
        x, y = index % 16, index // 16
        positions = ((x, y), (31 - x, 31 - y))
        positions += ((31 - x, y), (x, 31 - y)) if snowflake else ((31 - y, x), (y, 31 - x))
        for target_x, target_y in positions:
            offset = (target_y * 32 + target_x) * 3
            pixels[offset:offset + 3] = color
    return bytes(pixels)


def fingerprint_lifehash(fingerprint: str, size: int = 32) -> Image.Image:
    """Return a fresh RGB LifeHash v2 image for exactly eight hexadecimal digits.

    Letter case is ignored, but prefixes, whitespace and abbreviated values are
    rejected. The canonical image is 32x32; other positive sizes use nearest
    neighbor scaling without antialiasing. Callers may modify the returned image
    without changing any subsequent result.
    """
    if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("A fingerprint must contain exactly eight hexadecimal digits")
    if type(size) is not int or size <= 0:
        raise ValueError("LifeHash size must be a positive integer")
    image = Image.frombytes("RGB", (32, 32), _fingerprint_rgb(bytes.fromhex(fingerprint)))
    if size != 32:
        image = image.resize((size, size), resample=Image.Resampling.NEAREST)
    return image
