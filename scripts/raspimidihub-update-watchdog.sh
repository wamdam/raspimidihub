#!/bin/bash
# Watchdog for the transient WiFi update flow.
#
# Scheduled by update_flow.UpdateFetcher via systemd-run --on-active=180s
# right before any WiFi switch. If the orchestrator hasn't returned to AP
# mode after 180s — because of a hang, crash, or just an unusually slow
# DHCP lease — this script forces the Pi back to AP so the user can
# always reach it from their phone again.
#
# Two-step failsafe:
#   1) write a status breadcrumb so the UI surfaces a precise reason.
#   2) restart raspimidihub.service. The service's async_main calls
#      wifi.start_ap() unconditionally on boot, which puts the Pi back
#      on AP regardless of what mode it was stuck in.
#
# Usage: raspimidihub-update-watchdog.sh <reason>

REASON="${1:-unknown}"
STATUS_FILE="/run/raspimidihub/update-status"

mkdir -p /run/raspimidihub
printf '{"step":"error-watchdog","message":"Update flow hung in WiFi mode for 180s — forced back to AP. Reason: %s"}\n' "$REASON" \
    > "$STATUS_FILE.tmp"
mv "$STATUS_FILE.tmp" "$STATUS_FILE"

logger -t raspimidihub-update-watchdog "watchdog firing — reason: $REASON"

# A clean restart re-runs WiFiManager.start_ap on boot, which is the
# safest and most-tested AP-restoration path the codebase has.
systemctl restart raspimidihub.service || true
