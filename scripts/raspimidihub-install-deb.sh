#!/bin/bash
# Install a previously-downloaded deb from /var/lib/raspimidihub/updates/.
#
# This is the second half of the Phase 5.5 update flow — fetching is
# done by the Python orchestrator (transient WiFi → download → back
# to AP). Once the user clicks "Install version X" in the UI we run
# this script as a detached subprocess; dpkg restarts the service,
# which is fine because the orchestrator is no longer running.
#
# Usage: raspimidihub-install-deb.sh <deb_path>

set -e

DEB_PATH="$1"
STATUS_FILE="/run/raspimidihub/update-status"

if [ -z "$DEB_PATH" ] || [ ! -f "$DEB_PATH" ]; then
    echo "Usage: $0 <deb_path> (file must exist)" >&2
    exit 1
fi

mkdir -p /run/raspimidihub

write_status() {
    printf '%s\n' "$1" > "$STATUS_FILE.tmp"
    mv "$STATUS_FILE.tmp" "$STATUS_FILE"
}

VER=$(basename "$DEB_PATH" | sed -E 's/^raspimidihub_([0-9]+\.[0-9]+\.[0-9]+)-[0-9]+_all\.deb$/\1/')

write_status "{\"step\":\"installing\",\"version\":\"$VER\"}"
mount -o remount,rw / || true

# Capture dpkg output for a precise error message — without it the UI
# can only show "install failed" with no clue what dpkg actually
# complained about (dependency mismatch, postinst exit, etc.).
LOG=/tmp/raspimidihub-install-deb.log
if dpkg -i "$DEB_PATH" >"$LOG" 2>&1; then
    mount -o remount,ro / || true
    write_status "{\"step\":\"done\",\"version\":\"$VER\"}"
    exit 0
else
    mount -o remount,ro / || true
    # First 400 chars of the log = enough to point at the real cause
    # without bloating the status JSON beyond what the UI can render.
    ERR=$(head -c 400 "$LOG" | tr '\n' ' ' | sed 's/"/\\"/g')
    write_status "{\"step\":\"error-install\",\"version\":\"$VER\",\"message\":\"dpkg failed: $ERR\"}"
    exit 1
fi
