# Screenshots

These screenshots are used in [../UI_GUIDE.md](../UI_GUIDE.md).

## Regenerating

Screenshots are captured using Playwright MCP via Claude Code. To update them:

1. Ensure the Pi is running and reachable at `http://10.1.1.2` (or update the URL)
2. Connect at least 2 MIDI devices for a representative view
3. Ask Claude Code to regenerate screenshots:

```
Regenerate the UI screenshots in docs/screenshots/ by navigating through 
all screens of the app at http://10.1.1.2 with a 390x844 mobile viewport.
Capture: routing page, filter panel (right-click a connection), add mapping 
overlay, presets page, status page, device detail panel, settings page (full page).
```

## File naming convention

| File | Screen |
|------|--------|
| `01-routing.png` | Routing page with connection matrix |
| `02-filter-panel.png` | Filter & mapping panel (long-press a connection) |
| `03-add-mapping.png` | Add mapping sub-overlay |
| `04-presets.png` | Presets page |
| `05-status.png` | Status page with system info and device list |
| `06-device-detail.png` | Device detail panel (tap a device) |
| `07-settings.png` | Settings page (full page) |

Add new screenshots with incrementing numbers. Update `UI_GUIDE.md` when adding/removing.
