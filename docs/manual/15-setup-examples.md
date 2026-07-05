# Setup Examples

End-to-end recipes for typical rigs, each starting from a
freshly-installed RaspiMIDIHub.

## Two-Keyboard Live Rig with Note Splitter

Two keyboards and one synth: the lower keyboard plays bass on
channel 2, the upper plays leads on channel 1.

1. Plug both keyboards and the synth into the Pi. The matrix shows
   three new rows / columns.
2. Tap the Lower Keyboard → Synth cell, pick **Edit**, add a
   **Channel Remap** mapping: source channel 1 → destination
   channel 2. Save.
3. Tap the Upper Keyboard → Synth cell. The default filter (all
   channels, all message types) is correct — the upper keyboard
   already sends on channel 1.
4. Tap **Save Config**.

A Note Splitter plugin (chapter 7) also works; a Channel Remap
mapping is simpler when each *keyboard* maps cleanly to one channel.

## Drum Machine + Sequencer with Master Clock

A drum machine generates MIDI clock; a sequencer-equipped synth
slaves to it; a second synth wants clock at half the rate.

1. Plug all three devices into the Pi.
2. Tap **Add → Plugin → Master Clock**. Its config panel shows the
   bar counter and beat meter.
3. Tap **Add → Plugin → Clock Divider**; set **Divide by** to `2`.
4. Wire the routing:
   - Drum Machine row → Sequencer Synth column.
   - Drum Machine row → Clock Divider column.
   - Clock Divider row → Slow Synth column.
5. The Master Clock mirrors the incoming clock — here it is a
   *display*, not a source. Verify its BPM readout matches the drum
   machine during play.
6. Tap **Save Config**.

## Tracker + Multi-Channel Synth

The Tracker as an 8-voice sequencer driving a multi-timbral synth
across eight MIDI channels.

1. Plug the synth into the Pi.
2. Tap **Add → Plugin → Tracker**. A **Play** tab appears in the
   bottom navigation.
3. Open the Tracker's row header; set the eight ChannelSelect
   wheels (T1..T8) to channels 1..8 (or whatever the synth expects).
4. Wire the matrix: Tracker row → Synth column.
5. On the **Play** tab, enter notes on the grid (cell format:
   chapter 9.4.2). Each track fires into a different voice of the
   synth.
6. To make the Tracker the clock master for downstream gear, enable
   **Send Clock** (and **Send Trnsp.** to also forward START / STOP /
   CONTINUE).
7. Tap **Save Config**.

## Phone-Controlled Performance Rig

A hardware mixer and an FX rack, controlled live from the phone with
drop buttons that recall scenes.

1. Plug the mixer (or any USB MIDI device with CC inputs) into the
   Pi.
2. Tap **Add → Controller → Mixer 8**. A **Controller** tab appears
   in the bottom nav.
3. In the Mixer 8's row-header config, use MIDI Learn on each
   fader / knob to capture the hardware's expected CCs.
4. Wire the matrix: Mixer 8 row → Hardware Mixer column.
5. Add a second instance, **Add → Controller → Performance 16**;
   repeat the Learn flow for its 16 macro knobs.
6. On the **Controller** tab, long-press a drop button to capture
   the current state of all controls. Set its mode (e.g. **Bar**)
   and enable **Sync to bars**. Tap to fire; the snapshot lands at
   the next bar, quantised to the master clock.
7. Repeat for additional scenes on the remaining drop buttons.
8. Tap **Save Config** — it persists the layout, the learned CCs,
   and the captured drop-button snapshots.

## BLE + USB Hybrid

A wireless BLE-MIDI controller alongside USB instruments, with
**Channel Remap** aligning channels and **Velocity Curve** smoothing
the wireless controller's response.

1. Pair the BLE controller: **Add → Bluetooth MIDI → Scan →
   Connect** (chapter 10.2).
2. Plug the USB instruments into the Pi.
3. Tap **Add → Plugin → Velocity Curve**. Pick or draw a curve that
   softens the controller's hot top end — BLE-MIDI velocity is often
   quirky on light-weight pad controllers.
4. Wire the matrix:
   - BLE Controller row → Velocity Curve column.
   - Velocity Curve row → USB Synth column.
   - If the BLE controller and the USB instruments send on
     different channels, add a Channel Remap mapping on the
     relevant cell.
5. Tap **Save Config**. The Velocity Curve and its parameters are
   persisted; the BLE pairing lives in its own snapshot
   (chapter 10.3).

## Routing for a Recording Session

The Pi between a controller keyboard and a DAW: MIDI Delay as a
creative effect, Master Clock feeding the DAW clock.

1. Plug the controller keyboard into the Pi.
2. Plug the DAW computer into the Pi via USB (most computers show
   up as a USB MIDI device).
3. Tap **Add → Plugin → Master Clock**; set the BPM to match the
   session.
4. Tap **Add → Plugin → MIDI Delay**; set the delay rate and
   feedback.
5. Wire the matrix:
   - Controller Keyboard row → MIDI Delay column.
   - MIDI Delay row → DAW column (the dry note + the echoes).
   - Master Clock row → DAW column (clock).
   - Master Clock row → MIDI Delay column (sync the delay).
6. Tap **Save Config**.

MIDI Delay's pre-scheduled echoes are sample-accurate
(chapter 7.6).

## Send-Only SysEx Batch

A one-shot upload of a `.syx` file to a synth — for example,
restoring a patch bank after a factory reset.

1. Plug the synth into the Pi.
2. Tap **Add → Plugin → SysEx Sender**.
3. Wire the matrix: SysEx Sender row → Synth column.
4. In the plugin's config panel, tap the file-picker button and
   pick the `.syx` file from your phone. The plugin streams it in
   conservatively timed chunks (appendix A, *SysEx Sender*), which
   avoids the buffer overruns that make DAW SysEx uploads flaky.
5. The display shows progress; when done, the synth has the new
   state.
6. Nothing persists — the plugin does not save the uploaded file,
   so removing the instance after the upload is safe.
