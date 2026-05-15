"""Shared scale catalogue + nearest-in-scale lookup.

Single source of truth for the scale dictionary and the quantiser
helper. Used by the Scale Remapper plugin (which exposes the
quantiser as a routable plugin) and the Euclidean plugin (which
applies it as the final stage of its emission pipeline). Adding a
scale here makes it appear in both consumers without any other code
change.
"""

from __future__ import annotations

SCALES: dict[str, list[int]] = {
    "chromatic": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    "major":     [0, 2, 4, 5, 7, 9, 11],
    "minor":     [0, 2, 3, 5, 7, 8, 10],
    "dorian":    [0, 2, 3, 5, 7, 9, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "pentatonic": [0, 2, 4, 7, 9],
    "blues":     [0, 3, 5, 6, 7, 10],
    "harmonic m": [0, 2, 3, 5, 7, 8, 11],
    "whole tone": [0, 2, 4, 6, 8, 10],
}


def build_nearest_map(scale_name: str, root: int) -> list[int]:
    """Return a 128-entry lookup table mapping every MIDI note number
    to the nearest in-scale note. Search is symmetric outward, so a
    note equidistant from two scale degrees falls to the lower one
    (the `n - d` branch tests first).

    Unknown scale names fall back to `major` to keep the caller alive
    if a stored config references a deleted scale; callers that want
    strictness should guard with `scale_name in SCALES`.
    """
    intervals = SCALES.get(scale_name, SCALES["major"])
    root = int(root) % 12
    valid: set[int] = set()
    for octave in range(-1, 12):
        for interval in intervals:
            n = root + octave * 12 + interval
            if 0 <= n <= 127:
                valid.add(n)
    table = [0] * 128
    for n in range(128):
        if n in valid:
            table[n] = n
            continue
        for d in range(1, 128):
            if n - d >= 0 and (n - d) in valid:
                table[n] = n - d
                break
            if n + d <= 127 and (n + d) in valid:
                table[n] = n + d
                break
    return table
