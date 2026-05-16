# Plugins and Virtual Instruments

Plugins are virtual MIDI devices that appear as rows and columns in
the routing matrix alongside USB and Bluetooth devices. They consume
MIDI from connected sources, transform it, and emit MIDI to connected
destinations. This chapter covers the plugin model -- what is true of
every plugin. The per-plugin parameter reference is in **Appendix A**.

## The Plugin Model

Each plugin instance is, internally, a virtual ALSA MIDI client with
its own input and output ports. It looks identical to any USB MIDI
device from the routing matrix's point of view; it just happens to
be implemented in software.

That symmetry is the design goal. Anything you can do with a USB
device -- route it, filter it, map it, save it in the project state
-- you can do with a plugin. The plugin's own behaviour is set
inside its configuration panel; the routing of its inputs and
outputs lives in the matrix.

## Adding and Removing Instances

Plugins are added from the **Add** button at the bottom of the
routing matrix:

1. Tap **Add**.
2. Pick a plugin from the **Plugins** section of the overlay.
3. A new instance appears as a new row and column in the matrix.

Multiple instances of the same plugin can coexist. Each carries its
own parameter state. Adding two **Arpeggiators** with different
patterns and routing different sources to each is a normal pattern.

To remove an instance, tap its row or column header and pick
**Remove** from the menu. The instance is destroyed; its routing is
lost. (A presence in the cell clipboard is not enough to bring it
back; use the **plugin clipboard** flow if you may want to undo --
see chapter 9.6 for *Copy → Paste-as-new*.)

## Why Plugins Start Unconnected

A new plugin instance appears with **no** active connections.
Nothing routes into it and nothing routes out of it by default.
Compare this to the all-to-all default for USB devices.

The reason: a plugin's *whole point* is precise routing. The
**Arpeggiator** is meaningful only when one source feeds it notes
and one destination plays the result -- not when every connected
device sends notes into it indiscriminately. Forcing the user to
wire the inputs and outputs explicitly makes the routing visible
and intentional. (The default-routing behaviour for new *USB*
devices can be flipped to **None** in **Settings → MIDI Routing**
if you would rather have every new device behave the same way.)

## The Plugin Configuration Panel

Tap a plugin's row or column header to open the device-detail panel
for that plugin. The panel renders the plugin's parameter UI inline:
wheels, faders, radio buttons, toggles, step editors, curve editors,
scopes, meters, buttons (chapter 8). The exact layout is the
plugin's choice, declared in its `params` list.

The panel header carries three universal controls:

- **Maximize (double-arrow) icon** -- opens the plugin in its
  dedicated fullscreen tab if it has one: controllers jump to the
  **Controller** tab; the Tracker, the Arpeggiator and the
  Euclidean jump to the **Play** tab. Only shown for plugins with
  a fullscreen surface. The reverse direction -- jumping from
  the fullscreen surface back into this Plugin Config panel --
  is the **pencil** icon on the Controller / Play top bar.
- **`?` help button** -- shows the plugin's extended `HELP` text:
  a longer explanation of what the plugin does and an example or
  two.
- **`X` close button** -- standard dismiss.

The **MIDI Monitor** and **MIDI Test Sender** sections that appear
on USB-device panels are also available on plugins -- the monitor
streams every event the plugin sends or receives on its virtual
ALSA ports, and the test sender fires notes or CCs straight into
the plugin's input. Useful for verifying routing without touching
hardware. Plugins additionally get live scopes and meters (see
section 11.8) where the plugin author has wired them up.

## MIDI Clock and Sync

Plugins fall into three groups with respect to clock:

- **Clock-naive** -- ignore clock entirely (**Chord Generator**,
  **Note Splitter**, **Note Transpose**, **Panic Button**,
  **Scale Remapper**, **Velocity Curve**, **Velocity Equalizer**,
  **CC Smoother**, **Hold**, **SysEx Sender**).
- **Clock-consuming** -- listen for incoming MIDI Clock to drive
  their own timing (**Arpeggiator**, **Euclidean**, **CC LFO**,
  **MIDI Delay**, **Clock Divider** -- both consumes and produces).
- **Clock-generating** -- emit MIDI Clock (**Master Clock**,
  **Tracker** with **Send Clock + Transport** enabled,
  **Clock Divider**).

Clock-consuming plugins typically have a **Sync** toggle. When sync
is on, the plugin uses the incoming clock to schedule events; when
off, it uses its own internal BPM (settable as a parameter). If no
clock is routed in and sync is on, the plugin sits idle until
either sync flips off or a clock source appears.

The **Master Clock** plugin is the typical source -- one instance
per project, routed to every clock-consuming plugin and to
hardware that wants tempo.

## Sample-Accurate Scheduling

Some plugins know *in advance* when an event should fire (the
**Master Clock**'s next tick, a **MIDI Delay**'s scheduled echo, a
controller **drop button** fire quantised to the next bar
boundary). Those events are pre-scheduled through the ALSA kernel
queue so they leave the system at the exact target time, with
sub-millisecond jitter under heavy load.

Plugins that react to *incoming* clock ticks (the **Arpeggiator**,
the **Euclidean** and the **Tracker** all work this way) fire
their events synchronously when the clock subdivision arrives. Timing
precision then follows the incoming clock -- a rock-solid clock
source produces rock-solid output, and a jittery clock source
produces output that tracks the same jitter.

Plugins with no timing requirements (the **Scale Remapper**,
**Note Splitter**, anything purely event-driven) run straight
through the asyncio loop on the reserved CPU 3, with typical
latency under one millisecond.

## CC Automation

Every plugin control that's part of its performance surface
(Pattern, Rate, Gate, Steps, … -- the knobs you actually reach
for on a play surface) can be bound to an incoming MIDI CC.
**Long-press** the control on touch -- or **right-click** with a
mouse -- and the binding popup opens.

The popup shows:

- **Current binding** -- the (channel, CC) the control currently
  listens on. Channel can be "Any" (the wire channel doesn't
  matter) or a specific 1..16; CC is 0..127. Cleared = no
  binding; the control no longer responds to any CC.
- **Plugin author's factory default** -- the (channel, CC) the
  plugin was shipped with. "Reset to factory" snaps the popup
  back to it.
- **MIDI Learn** -- arms a 30-second listen for the next
  incoming CC on any routed source. Twist a hardware knob; the
  popup fills in (channel, CC). Cancel anytime.
- **Save / Cancel** -- edits stay local until Save commits them
  to the plugin's `cc_map` and broadcasts the change.

The CC value is scaled to the parameter's full range and the
on-screen control animates in real time as the hardware CC
arrives. Touching the on-screen control while a CC is also
moving the parameter produces a single resolved value, with no
flicker between sources.

Bindings are per *instance*: two Arpeggiators can carry the same
factory default and be re-bound to different CCs without
affecting each other. They persist in the saved config.

**Discoverability** -- there is no longer a per-plugin "Arp = CC
74" list in the device-detail panel or the plugin HELP. The
popup itself is the discovery surface; if you want a global view,
see **Settings → Plugin Control Mappings** for a flat table of
every binding across every instance (chapter 16). Appendix A
still lists each plugin's factory default CC for reference.

For incoming CCs that the plugin doesn't have a binding for, a
**CC → CC** mapping at the routing level can rewrite the CC
number on the wire -- useful when the hardware controller can't
send the CC you want and you'd rather not rebind every plugin.

## Live Display Outputs

Plugins can declare **display outputs** that render live data in
the configuration panel:

- **Scope** -- a rolling waveform over a fixed time window. Used
  by **CC LFO** (showing the LFO output) and **CC Smoother**
  (showing input and output side by side).
- **Meter** -- a segmented level / beat indicator. Used by
  **Master Clock** (showing the bar position) and any plugin that
  wants a "current value" gauge.

Displays are driven server-side; the browser-side rendering loops
at the client's natural frame rate. Closing the configuration
panel stops the SSE stream for that display.

## Per-Instance State

A plugin instance's parameter values are part of the project
state. **Save Config** persists them with the rest of the routing.
**Export Config** captures them in the JSON snapshot (chapter 15);
**Import Config** restores them. Loading the boot config (via
**Load Config** or by reboot) re-instantiates plugins with their
saved parameters.

The parameter state survives the plugin instance being moved in
the matrix (renamed, re-routed). It does *not* survive the
instance being removed -- removing and re-adding the same plugin
gives a fresh instance with default parameters. Use the
**Copy → Paste-as-new** flow on the plugin header instead if you
want a duplicate with cloned state.

## The Built-In Plugins

One-line summaries. The detailed reference for each lives in
**Appendix A** with parameter tables, ranges, and defaults.

| Plugin | Function |
|--------|----------|
| **CC LFO** | CC waveforms (sine/triangle/square/saw/sample-and-hold); free or clock-sync up to 8 bars; live scope |
| **CC Smoother** | Removes jitter from noisy CC inputs with configurable smoothing; dual scopes (in / out) |
| **Chord Generator** | Input note triggers a chord (major / minor / 7th / custom intervals) with inversions |
| **Clock Divider** | Emit one MIDI Clock for every N received (2..32) |
| **Euclidean** | Held notes voiced through a Bjorklund-distributed step pattern; per-step manual overrides on top; chord mode; internal Scale + Root; Jitter, Tune Spread, Fade In / Out. *Play-surface plugin* — added from **Add → Play** |
| **Hold** | Latch notes without a sustain pedal; chord-latch or per-note toggle; MIDI-Learn the release note |
| **Master Clock** | Internal BPM clock with start/stop/continue, beat meter, bar counter |
| **MIDI Delay** | Pre-scheduled echoes with feedback repeats and velocity decay; sync rate or free ms |
| **Note Splitter** | Splits keyboard at a configurable note into two channels with per-zone transpose |
| **Note Transpose** | Shifts all notes up or down by semitones |
| **Panic Button** | All Notes Off; second tap upgrades to All Sound Off |
| **Pitch CC** | Each Note On emits a pitch CC (base value ± semitones from a base note) then the Note On itself — chromatic playback for samplers like the Volca Sample that pitch via CC |
| **Scale Remapper** | Quantizes notes to a scale (major / minor / pentatonic / blues / ...) with labelled root selector |
| **SysEx Sender** | Upload a `.syx` file in the panel; bytes stream to the destination (256-byte chunks, ~5 ms gap; nothing saved) |
| **Velocity Curve** | Drawable 128-point velocity response curve with shape presets |
| **Velocity Equalizer** | Normalise velocity to a fixed value or compress the range |

The **Tracker**, the **Arpeggiator** and the **Euclidean** are
*play-surface* plugins -- they live in the routing matrix like
every other plugin but additionally render a fullscreen play
surface on the **Play** tab in the bottom navigation. Find them
under **Add → Play**. All three share a dedicated chapter
(chapter 13, "Play Surfaces") for their surface-and-workflow
reference; their parameter tables live in **Appendix A**.

## User-Supplied Plugins

The same framework that hosts the built-in plugins can host
plugins you write yourself. User-supplied plugins appear in the
**Add** overlay alongside the built-ins and are subject to the
same instance / save / clipboard semantics. The plugin developer
guide in the project repository covers the API and the sandbox
restrictions; this manual is not the place for that material.

