# Setup Examples

End-to-end walkthroughs of typical rigs. Each example assumes a
freshly-installed RaspiMIDIHub and walks through the routing, the
plugin choices, and the controller layout to recreate it. Each
example is written as a recipe -- read it, build it, modify it.

## Two-Keyboard Live Rig with Note Splitter

**The rig.** Two MIDI keyboards plus one synth. The lower keyboard
should play the bass voice on channel 2; the upper keyboard should
play the leads on channel 1.

**The build.**

1. Plug both keyboards and the synth into the Pi's USB ports. The
   matrix shows three new rows / columns.
2. Tap the cell where Lower Keyboard meets Synth. Pick **Edit**.
   Add a **Channel Remap** mapping: source channel 1 →
   destination channel 2. Tap save.
3. Tap the cell where Upper Keyboard meets Synth. No filter
   needed; the default (all channels, all message types) is
   correct since the upper keyboard already sends on channel 1.
4. Tap **Save Config**.

**Why this rig.** Many compact synths have separate channel
voices that can be triggered independently. A Note Splitter
plugin would also work (chapter 11), but a Channel Remap mapping
is simpler when each *keyboard* maps cleanly to one channel.

## Drum Machine + Sequencer with Master Clock

**The rig.** A drum machine generating MIDI clock, a sequencer-
equipped synth slaved to that clock, and a second synth that wants
clock at half the rate.

**The build.**

1. Plug the drum machine, the sequencer-equipped synth, and the
   slow second synth into the Pi.
2. Tap **Add → Plugin → Master Clock**. The Master Clock plugin
   appears in the matrix; its config panel shows the bar counter
   and beat meter.
3. Tap **Add → Plugin → Clock Divider**. Set **Divide by** to
   `2`.
4. Wire the routing:
   - Drum Machine row → Sequencer Synth column.
   - Drum Machine row → Clock Divider column.
   - Clock Divider row → Slow Synth column.
5. The Master Clock plugin in the matrix mirrors the incoming
   clock. Open its config panel during play to verify the BPM
   readout matches the drum machine.
6. Tap **Save Config**.

**Why this rig.** The Clock Divider takes one clock-source-of-
truth (the drum machine) and produces a derived clock at half the
rate without any extra hardware. The Master Clock plugin is in
the matrix as a *display* in this rig, not as a source.

## Tracker + Multi-Channel Synth

**The rig.** The Tracker as an 8-voice sequencer driving a multi-
timbral synth across eight MIDI channels.

**The build.**

1. Plug the multi-timbral synth into the Pi.
2. Tap **Add → Plugin → Tracker**. The Tracker appears in the
   matrix; a **Play** tab appears in the bottom navigation.
3. Open the Tracker's row header in the matrix; the config panel
   shows eight ChannelSelect wheels (T1..T8). Set them to
   channels 1..8 respectively (or whatever the synth expects).
4. Wire the matrix: Tracker row → Multi-timbral Synth column.
5. Switch to the **Play** tab. Enter notes on the grid; the cell
   format is described in chapter 13.2.
6. To make the Tracker the clock master for downstream gear, open
   its config and enable **Send Clock + Transport**.
7. Tap **Save Config**.

**Why this rig.** The Tracker's per-track channel mapping is what
makes it a multi-timbral driver. Each row on the grid can fire
into a different voice of the synth.

## Phone-Controlled Performance Rig

**The rig.** A hardware mixer and an FX rack, controlled live from
the phone with macro shots that recall scenes via drop buttons.

**The build.**

1. Plug the mixer (or any USB MIDI device with CC inputs) into
   the Pi.
2. Tap **Add → Controller → Mixer 8**. The new instance appears
   in the matrix; a **Controller** tab appears in the bottom nav.
3. Open the Mixer 8's row header to access its config. Use MIDI
   Learn on each fader / knob to capture the hardware's expected
   CCs.
4. Wire the matrix: Mixer 8 row → Hardware Mixer column.
5. Add a second instance: **Add → Controller → Performance 16**.
   Repeat the Learn flow for its 16 macro knobs.
6. Switch to the **Controller** tab. Long-press a drop button on
   the Mixer 8 to capture the current state of all controls.
   Set the drop button's mode (e.g. **Bar**) and **Sync to bars**
   on. Tap to fire; the snapshot lands at the next bar.
7. Repeat for additional scenes on the remaining drop buttons.
8. Tap **Save Config** to persist the layout, the learned CCs,
   and the captured drop-button snapshots.

**Why this rig.** Drop buttons turn the phone into a scene-recall
device. Long-press captures, short-tap fires; the fire is
quantised to the master clock.

## BLE + USB Hybrid

**The rig.** A wireless BLE-MIDI controller alongside USB
instruments, with **Channel Remap** keeping everything on the
right channels and the **Velocity Curve** smoothing the wireless
controller's response.

**The build.**

1. Pair the BLE-MIDI controller via **Add → Bluetooth MIDI →
   Scan → Connect** (chapter 14.2).
2. Plug the USB instruments into the Pi.
3. Tap **Add → Plugin → Velocity Curve**. Open its config panel
   and pick or draw a velocity curve that softens the BLE
   controller's hot top end.
4. Wire the matrix:
   - BLE Controller row → Velocity Curve column.
   - Velocity Curve row → USB Synth column.
   - If the BLE controller and the USB instruments send on
     different channels, add a Channel Remap mapping on the
     relevant cell to align them.
5. Tap **Save Config**. The Velocity Curve and its parameters are
   persisted; the BLE pairing lives in its own snapshot
   (chapter 14.3).

**Why this rig.** BLE-MIDI's velocity response is sometimes
quirky -- particularly on light-weight pad controllers. A
Velocity Curve in the chain makes the response match the rest
of the rig.

## Routing for a Recording Session

**The rig.** Pi between a controller keyboard and a DAW, with a
MIDI Delay plugin patched in as a creative effect. The DAW also
receives clock from the Pi via the Master Clock plugin.

**The build.**

1. Plug the controller keyboard into the Pi.
2. Plug the DAW computer into the Pi via USB. (Most computers
   show up as a USB MIDI device when connected to the Pi.)
3. Tap **Add → Plugin → Master Clock**. Set the BPM to match the
   session.
4. Tap **Add → Plugin → MIDI Delay**. Set the delay rate and
   feedback.
5. Wire the matrix:
   - Controller Keyboard row → MIDI Delay column.
   - MIDI Delay row → DAW column (the dry note + the echoes).
   - Master Clock row → DAW column (clock).
   - Master Clock row → MIDI Delay column (sync the delay to
     the master clock).
6. Tap **Save Config**.

**Why this rig.** MIDI Delay's pre-scheduled echoes are sample-
accurate (chapter 11.6). The DAW receives clock from the Pi's
Master Clock and tempo-locked notes.

## Send-Only SysEx Batch

**The rig.** A single one-shot upload of a `.syx` file to a synth
-- for example, restoring a patch bank after a factory reset.

**The build.**

1. Plug the synth into the Pi.
2. Tap **Add → Plugin → SysEx Sender**.
3. Wire the matrix: SysEx Sender row → Synth column.
4. Open the SysEx Sender's config panel. Tap the file-picker
   button and pick the `.syx` file from your phone. The plugin
   streams the file to the destination in 256-byte chunks with
   ~5 ms gaps between chunks.
5. The plugin's display shows progress. When done, the synth has
   the new state.
6. The SysEx Sender does not *save* the uploaded file -- nothing
   persists. Removing the plugin instance after the upload is
   safe.

**Why this rig.** SysEx uploads from a DAW are sometimes flaky
on USB MIDI buffers; the chunked send with explicit gaps is
deliberately conservative.

