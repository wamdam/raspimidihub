# Keyboard Shortcuts

Every keyboard shortcut in the UI, grouped by context. Tracker
shortcuts resolve through `event.code`, so the *physical key
position* counts -- QWERTY and QWERTZ behave identically.

## Global

| Shortcut | Action |
|----------|--------|
| `ESC` | Close the topmost overlay (cell menu, filter panel, plugin config, ...) |
| `F5` or `Cmd + R` | Reload the SPA. Prefer **Settings → Reload App** on mobile -- it busts mobile Safari's bf-cache; the keyboard shortcut may not. |

## Tracker -- transport

| Shortcut | Action |
|----------|--------|
| `Space` | Toggle Play / Stop |
| `Shift`+`Space` | Play looping just the current page (follows the page you view); Stop or plain Play returns to full-sequence playback |

## Tracker -- note entry

Physical-key positions, shown on a US-QWERTY layout:

| Key | Note | Key | Note |
|-----|------|-----|------|
| `q` | C   | `r` | F   |
| `2` | C#  | `5` | F#  |
| `w` | D   | `t` | G   |
| `3` | D#  | `6` | G#  |
| `e` | E   | `y` | A   |
|     |     | `7` | A#  |
|     |     | `u` | B   |

The octave for the next typed note comes from the focused cell's
pitch if it has one, otherwise from the sticky **OCT** wheel:

| Shortcut | Action |
|----------|--------|
| `+` (or `=`) | Octave up (clamped at 9) |
| `-` (or `_`) | Octave down (clamped at 0) |

If the focused cell holds a real pitch, its octave digit follows
the wheel -- the note jumps with it. Sentinel cells (`---` / `Off`
/ `End`) stay put. Details in chapter 13.

## Tracker -- selection and editing

| Shortcut | Action |
|----------|--------|
| Arrow keys | Move cursor by one cell |
| `Shift` + arrows | Extend the selection rectangle by one cell. Up/Down wrap within the current page while Shift is held |
| `Delete` | Cut (copy the selection to the paste buffer, clear it from the grid) |

The action row buttons (**Shift / Cut / Copy / Paste**) are the
primary editing entry point; only `Delete` has a keyboard
equivalent. With a selection active, Cut and Copy act on it,
release Shift, and move the cursor to its top-left. `Shift+Cut` /
`Shift+Copy` target the whole page only when nothing is selected.

## Routing matrix

No keyboard shortcuts; the matrix is touch-first.

## Controller surface

No keyboard shortcuts; the surface is touch-first (drag / tap /
long-press).

## Plugin and overlay panels

| Shortcut | Action |
|----------|--------|
| `ESC` | Close the topmost overlay |
| `Tab` / `Shift + Tab` | Move focus between form fields where applicable |
| `Enter` | Confirm the focused button or text field |

These are native browser form semantics, not RaspiMIDIHub-specific
shortcuts.
