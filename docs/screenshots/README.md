# Screenshots

These screenshots are used in [../UI_GUIDE.md](../UI_GUIDE.md) and the main README.

## Regenerating

Screenshots are captured using Playwright MCP via Claude Code at 390x844 (iPhone 14 viewport).

### Prerequisites

1. Pi running and reachable at `http://10.1.1.2` (or update the URL)
2. At least 2 USB MIDI devices connected for a representative matrix
3. One plugin instance running (e.g., Arpeggiator) for plugin screenshots

### Steps

1. **Set viewport**: 390x844 (mobile)
2. **Navigate** to `http://10.1.1.2`
3. **Main pages** (4 screenshots):
   - Routing tab: `01-routing.png`
   - Presets tab: `02-presets.png`
   - Devices tab: `03-devices.png`
   - Settings tab: `04-settings.png`
4. **Panels** (2 screenshots):
   - Right-click any active connection in the matrix: `05-filter-panel.png`
   - Click "+ Add Mapping" in the filter panel, then screenshot: `07-mapping-note-to-cc.png`
   - Switch to CC->CC type and screenshot: `08-mapping-cc-to-cc.png`
   - Close mapping form, close filter panel
   - Click any USB device in Devices tab: `06-device-detail.png`
5. **Plugin configs** (10 screenshots):
   - Create temporary instances of each plugin type via API:
     ```
     curl -X POST http://10.1.1.2/api/plugins/instances \
       -H 'Content-Type: application/json' -d '{"type": "velocity_curve"}'
     ```
   - Open each in Devices tab and screenshot: `09-plugin-arpeggiator.png` through `18-plugin-monitor.png`
   - Delete temporary instances after screenshots:
     ```
     curl -X DELETE http://10.1.1.2/api/plugins/instances/{id}
     ```
6. **Save config** to restore state after cleanup

### After adding a new plugin

Create an instance, screenshot it, add the file to this table, delete the instance.

## File naming convention

| File | Screen |
|------|--------|
| `01-routing.png` | Routing page with connection matrix |
| `02-presets.png` | Presets page with save/load/export |
| `03-devices.png` | Devices page with USB + virtual device list |
| `04-settings.png` | Settings page (system info, WiFi, network, update) |
| `05-filter-panel.png` | Filter & mapping panel (right-click a connection) |
| `06-device-detail.png` | USB device detail panel (ports, MIDI monitor, test sender) |
| `07-mapping-note-to-cc.png` | Add Mapping form: Note -> CC type with wheels |
| `08-mapping-cc-to-cc.png` | Add Mapping form: CC -> CC type with range wheels |
| `09-plugin-arpeggiator.png` | Arpeggiator plugin config (Radio, Wheel, Toggle) |
| `10-plugin-velocity-curve.png` | Velocity Curve plugin config (CurveEditor) |
| `11-plugin-note-splitter.png` | Note Splitter plugin config (NoteSelect, ChannelSelect) |
| `12-plugin-cc-lfo.png` | CC LFO plugin config (Radio, Toggle, Wheel, Fader) |
| `13-plugin-chord-generator.png` | Chord Generator plugin config (Radio, Wheel) |
| `14-plugin-midi-delay.png` | MIDI Delay plugin config (Toggle, Wheel, Fader) |
| `15-plugin-channel-router.png` | Channel Router plugin config (Radio, Wheel) |
| `16-plugin-cc-smoother.png` | CC Smoother plugin config (Wheel, Fader) |
| `17-plugin-panic.png` | Panic Button plugin config (Toggle, Wheel) |
| `18-plugin-monitor.png` | Monitor plugin (no params, MIDI monitor visible) |
