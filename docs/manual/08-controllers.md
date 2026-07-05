# Controllers

Controllers are fullscreen tap-to-play surfaces that send CCs over
MIDI. The **Controller** tab appears in the bottom navigation once a
controller instance exists. Layouts are in **Appendix B**.

## The Four Templates

Each is added from **Add → Controller** in the matrix overlay.

| Controller | Layout | Default CC range |
|------------|--------|------------------|
| **Mixer 8** | 24 knobs / 8 faders / 16 buttons | CC 16--63 ch 1 |
| **FX 6** | 18 knobs / 6 faders / 6 buttons | CC 16--45 ch 1 |
| **Performance 16** | 16 macro knobs + 4 scene buttons | CC 16--35 ch 1 |
| **XY 4** | 2 XY pads + 8 knobs + 4 buttons | CC 16--31 ch 1 |

Multiple instances of one template can coexist; switch with the
top-bar selector (swipe, arrows, dropdown). The last-viewed instance
survives reloads.

![Mixer 8 -- 24 knobs, 8 faders, 16 buttons.](../screenshots/controller-mixer-8.png){width=42%}

![FX 6 -- 18 knobs, 6 faders, 6 buttons.](../screenshots/controller-fx-6.png){width=42%}

![Performance 16 -- 16 macro knobs and 4 scene buttons.](../screenshots/controller-performance-16.png){width=42%}

![XY 4 -- 2 XY pads, 8 knobs, 4 buttons.](../screenshots/controller-xy-4.png){width=42%}

## The Play Surface

Universal across templates:

- **Every cell sends one CC** on one channel with an **On** and an
  **Off** value: knobs and faders send the dragged value, buttons
  toggle On / Off, XY pads send two CCs, one per axis.
- **Symmetric in / out** -- an incoming CC with the same (channel,
  CC) silently mirrors the cell: touch emits, hardware mirrors.
- **Long-press rebinds a cell** -- set channel + CC manually,
  MIDI-Learn from a hardware twist, or **Reset to factory**. Same
  popup as the plugin-control popup (chapter 7.7), but symmetric.
- **XY pads learn per axis** -- the popup grows to two axis sections
  (X / Y), each with Channel + CC + Learn; Save commits both.

The label, button **On / Off** values, and XY-pad spring config live
in the *plugin config* panel (section 8.7); the popup is
binding-only.

![Long-press the Mixer 8 K1 knob — the cell-binding popup with Channel + CC wheels ("touch emits, hardware mirrors").](../screenshots/33-cell-bind-popup.png){width=48%}

![On the XY 4 pad the same popup grows to two axis sections, each with Channel + CC wheels and its own MIDI Learn button.](../screenshots/34-cell-bind-popup-xy.png){width=48%}

## Drop Buttons

Four **drop buttons** sit above every play surface, always visible:
each stores a snapshot of every cell and fires it back on tap.

### Capturing

Long-press about 600 ms; the button flashes once and captures every
cell's value into the slot. A learned MIDI trigger note can also
capture (see *Trigger Notes*).

### Firing

Tap the captured button:

- **Mode = Now, Sync = off** -- every cell jumps to its captured
  value immediately.
- **Mode = Bar / 2-Bar / 4-Bar / 8-Bar / 16-Bar, Sync = on** -- the
  snapshot lands exactly at the next such master-clock boundary,
  pre-scheduled with sub-millisecond accuracy.
- **Fade on fire = on** -- each cell sweeps from its current to its
  captured value across the bar (or 2/4/8/16-bar) length; **off** --
  one step at the boundary.

### The Progress Ring

A segmented arc around the button shows scheduled-fire progress:
peach-pulsing while pending, frozen if MIDI Stop arrives mid-cycle.

### Trigger Notes

A learned MIDI note, on any channel routed to the controller, fires
(or captures, depending on which Learn flow you used) the button as
if tapped.

### Dual-Slot Scheduling

One **fade** and one **hard drop** can queue side by side. Two fades
cannot overlap; the second overrides the first.

## Themes

Eight dark themes ship: Default, Navy, Forest, Wine, Plum, Teal,
Sienna, Slate -- chosen **per controller instance** in its plugin
config panel.

## XY Pad Spring

XY pads (on the **XY 4**) can spring back to a home position on
release. Per cell: **Force** 0--127 (zero disables; higher pulls the
dot back faster) and **Home** (Bottom-left or Centre). With spring
on, the return fires a CC per axis; off, the dot stays put.

## The Controller Tab

Top bar: the **instance selector** (name plus arrows / swipe /
dropdown) and the **pencil** icon, which opens the controller's
*plugin config* without leaving the tab. The MIDI activity bar
(section 3.9) shows at the bottom when enabled in Settings.

## The Configuration Panel

Open via the pencil on the controller tab or the controller's
matrix header. One card per cell, carrying everything except the
(channel, CC) binding:

- **Cell label** -- blank falls back to the template default.
- **Button On / Off values** (button cells) -- sent on press /
  release; `↔` swaps them.
- **XY pad spring** (XY pad cells) -- Force and Home, see
  section 8.5.

Bindings are set by long-pressing the cell (section 8.2);
**Settings → Plugin Control Mappings** (chapter 12) lists every
cell's binding in one table.

Each drop button gets its own card: **Sync to bars** toggle, **Fade
on fire** toggle, **Mode** radio (Now / Bar / 2-Bar / 4-Bar / 8-Bar /
16-Bar), and **Trg. Note** field + Learn button. A **Maximize**
button at the top jumps back to the fullscreen Controller tab.

## Routing a Controller

A controller sends MIDI (its row) but is also a useful destination
column. Route its row to the device it drives; route a source *into*
it for:

- **MIDI-Learn capture** -- cell Learn (chapter 6) listens on the
  controller's IN port; the source you learn from must be routed in.
- **Drop-button trigger notes** (8.3.4) -- route the keyboard or
  pad that fires them in.
- **Mirroring** -- route a hardware controller (e.g. a Launch
  Control XL) to its software twin; every cell with a matching
  (channel, CC) follows in real time, silently -- nothing is
  re-emitted, so no routing loop.

The common live recipe: hardware controller → software controller
(mirroring), software controller → destination device(s).

## Saving Controller State

Cell renames, learned CCs, themes, and captured drop-button
snapshots are project state: **Save Config** persists them, **Export
Config** snapshots them (chapter 11). Removing an instance discards
its state; **Copy → Paste-as-new** duplicates it.

*Performing* -- moving a fader / knob / XY pad, firing or cancelling
a drop button -- is not saved: no dirty asterisk (chapter 5.11), no
autosave. **Capturing** a drop *does* count -- it writes a new
snapshot into saved state -- as do renames, rebinds, theme changes,
and drop-button settings.
