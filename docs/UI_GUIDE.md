# RaspiMIDIHub — UI Guide

This guide walks through every screen of the RaspiMIDIHub web interface.

---

## Routing Page

The main screen shows the **connection matrix** — a grid where rows are MIDI sources (FROM) and columns are destinations (TO). Tap a cell to connect or disconnect two devices. Purple cells indicate connections with active filters or mappings.

At the bottom: **Save Config** persists the current routing to disk (survives reboots), **Load Config** reloads the last saved state.

![Routing Page](screenshots/01-routing.png)

---

## Filter & Mapping Panel

Long-press (or right-click) a connected cell to open the connection panel. Here you can:

- **MIDI Channels:** Toggle individual channels on/off. Traffic light indicators (red = blocked, green = passing) are colorblind-friendly. Tap the "MIDI Channels" heading to toggle all.
- **Message Types:** Enable/disable notes, CCs, program changes, pitch bend, aftertouch, SysEx, and clock/realtime. Changes apply instantly.
- **Mappings:** View active mappings with Edit/Delete buttons. Tap **+ Add Mapping** to create a new one.

Dismiss the panel by swiping down, tapping X, pressing ESC, or tapping the dark overlay.

![Filter & Mapping Panel](screenshots/02-filter-panel.png)

---

## Add / Edit Mapping

The mapping form opens as a sub-overlay. Mapping types:

| Type | Description |
|------|-------------|
| **Note -> CC** | Note on/off sends configurable CC values |
| **Note -> CC (toggle)** | Each note press alternates between two CC values (e.g., mute toggle) |
| **CC -> CC** | Remap CC numbers with input/output range scaling |
| **Channel Remap** | Route all events to a different MIDI channel |

- **Src Ch / Dst Ch:** Filter by source channel and remap to destination channel
- **MIDI Learn:** Press the button, then play a note or move a knob — the source is auto-filled
- **Pass through original event:** When checked, the original note/CC is forwarded alongside the mapped output

![Add Mapping](screenshots/03-add-mapping.png)

---

## Presets Page

Save the current routing as a named preset and recall it later. Useful for switching between different setups at a gig.

- **Save:** Enter a name and tap Save to snapshot the current routing
- **Load:** Activate a saved preset instantly
- **Export/Import:** Share presets as JSON files between devices
- **Delete:** Remove presets you no longer need

Note: After loading a preset, tap **Save Config** on the Routing page to make it the boot default.

![Presets Page](screenshots/04-presets.png)

---

## Status Page

System overview and device list.

- **System info:** Hostname, version, CPU temperature, uptime, RAM, IP addresses
- **Connected Devices:** Tap a device to open its detail panel

![Status Page](screenshots/05-status.png)

---

## Device Detail Panel

Tap a device on the Status page to open the detail panel (slides up). Features:

- **Device info:** ALSA client ID, USB VID:PID, port types
- **Rename:** Assign a custom name that persists across reboots (stored by USB topology)
- **MIDI Monitor:** Live display of incoming MIDI events with note names (e.g., "Note On ch1 C3 vel=100")
- **MIDI Test Sender:** Piano keyboard (one octave, adjustable with +/- octave buttons) and CC slider for testing connections without physical MIDI input

![Device Detail Panel](screenshots/06-device-detail.png)

---

## Settings Page

WiFi configuration and system controls.

- **WiFi Status:** Current mode (AP or client), SSID, IP address
- **Access Point Mode:** Change the AP password, switch back to AP mode
- **Client Mode:** Select a WiFi network from the scanned dropdown, enter password, connect. The Pi is reachable at `http://raspimidihub.local` via mDNS
- **Display:** Toggle the persistent MIDI activity bar at the bottom of the screen
- **System:** Reboot the Pi remotely

**Safety net:** If the WiFi connection is lost in client mode, the Pi automatically falls back to AP mode within ~90 seconds.

![Settings Page](screenshots/07-settings.png)

---

## MIDI Activity Bar

A persistent bar above the bottom navigation showing the last MIDI event received (e.g., "Note On ch1 C3 vel=100"). Toggleable in Settings > Display. Useful for quick visual feedback during live performance.

---

## LED Status

| Green ACT LED | Red PWR LED | Meaning |
|---------------|-------------|---------|
| Steady on | Off | Running normally |
| Flickering | Off | MIDI activity |
| Fast blink | On | Config fallback (error) |
| Off | Default | Service stopped |
