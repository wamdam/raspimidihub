# Keyboard Shortcuts

Every keyboard shortcut in the UI, grouped by context. The Tracker
shortcuts resolve through `event.code`, so the *physical key
position* is what counts -- QWERTY and QWERTZ keyboards behave
identically.

## Global

| Shortcut | Action |
|----------|--------|
| `ESC` | Close the topmost overlay (cell menu, filter panel, plugin config, ...) |
| `F5` or `Cmd + R` | Reload the SPA. Prefer **Settings → Reload App** on mobile -- it busts mobile Safari's bf-cache; the keyboard shortcut may not. |

## Tracker -- transport

| Shortcut | Action |
|----------|--------|
| `Space` | Toggle Play / Stop |

## Tracker -- note entry

Physical-key positions on a US-QWERTY layout. The same physical
keys produce the same notes on a German QWERTZ layout (because
the implementation reads `event.code`, not the OS keymap).

| Key | Note | Key | Note |
|-----|------|-----|------|
| `q` | C   | `r` | F   |
| `2` | C#  | `5` | F#  |
| `w` | D   | `t` | G   |
| `3` | D#  | `6` | G#  |
| `e` | E   | `y` | A   |
|     |     | `7` | A#  |
|     |     | `u` | B   |

The octave for the next typed note is taken from the focused
cell's pitch if it has one, otherwise from the sticky **OCT**
wheel. Two shortcuts adjust the sticky value without touching
the mouse:

| Shortcut | Action |
|----------|--------|
| `+` (or `=`) | Octave up (clamped at 9) |
| `-` (or `_`) | Octave down (clamped at 0) |

If the focused cell currently holds a real pitch, the cell's
octave digit is rewritten in step with the wheel — the note jumps
along with the OCT wheel. Sentinel cells (`---` / `Off` / `End`)
stay as they were; only the sticky value moves. Details in
chapter 13.

## Tracker -- selection and editing

| Shortcut | Action |
|----------|--------|
| Arrow keys | Move cursor by one cell |
| `Shift` + arrows | Extend the selection rectangle by one cell |
| `Delete` | Cut (copy the selection to the paste buffer, clear it from the grid) |

The action row buttons on the Tracker surface (**Shift / Cut /
Copy / Paste**) are the primary entry point for editing
operations and do not have direct keyboard shortcuts beyond
`Delete`. `Shift+Cut` and `Shift+Copy` target the whole current
page; both are surface-button operations.

## Routing matrix

No global keyboard shortcuts at this time. The matrix is touch-
first; all interactions are taps.

## Controller surface

No global keyboard shortcuts at this time. The surface is touch-
first; all interactions are drag / tap / long-press on cells and
drop buttons.

## Plugin and overlay panels

| Shortcut | Action |
|----------|--------|
| `ESC` | Close the topmost overlay |
| `Tab` / `Shift + Tab` | Move focus between form fields where applicable |
| `Enter` | Confirm the focused button or text field |

These are standard browser behaviours rather than RaspiMIDIHub-
specific shortcuts; they work because the UI respects native
form semantics.
