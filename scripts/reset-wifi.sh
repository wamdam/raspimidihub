#!/bin/bash
# Reset RaspiMIDIHub to WiFi Access Point mode
# Run this if you can't reach the Pi after it joined a WiFi network.
# Usage: sudo reset-wifi
set -e

echo "Resetting RaspiMIDIHub to Access Point mode..."

mount -o remount,rw /

# Remove any saved WiFi client connections (keep wired)
for f in /etc/NetworkManager/system-connections/*.nmconnection; do
    [ -f "$f" ] || continue
    if grep -q "type=wifi" "$f"; then
        echo "  Removing $(basename "$f")"
        rm -f "$f"
    fi
done

# Reset config to AP mode. wifi_mode_pref is the key the service actually
# boots from (ap_only / wifi_for_updates / wifi_always); the legacy `mode`
# key is set too for older builds.
CONFIG="/boot/firmware/raspimidihub/config.json"
if [ -f "$CONFIG" ]; then
    python3 -c "
import json
with open('$CONFIG') as f:
    cfg = json.load(f)
w = cfg.setdefault('wifi', {})
w['wifi_mode_pref'] = 'ap_only'
w['mode'] = 'ap'
with open('$CONFIG', 'w') as f:
    json.dump(cfg, f, indent=2)
print('  Config set to AP mode (wifi_mode_pref=ap_only)')
"
fi

mount -o remount,ro /

echo "Restarting service..."
systemctl restart raspimidihub

echo ""
echo "Done! Connect to WiFi AP 'RaspiMIDIHub-XXXX' (password: midihub1)"
echo "Then open http://192.168.4.1"
