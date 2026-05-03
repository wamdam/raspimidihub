#!/bin/bash
# Install a previously-downloaded deb from /var/lib/raspimidihub/updates/.
#
# Uses `apt-get install` (not `dpkg -i`) so any new transitive deps the
# deb introduced (e.g. python3-dbus-next when BLE-MIDI was added) are
# pulled automatically when the Pi is online. Apt also handles the
# offline case correctly: if every dep is already satisfied locally it
# never touches the network — that's how we keep offline downgrades
# working.
#
# The orchestrator (api.py /api/system/install) decides whether a
# transient WiFi switch is needed by inspecting the deb's Depends
# against currently-installed packages BEFORE calling us. So by the
# time we run, either deps are satisfied (apt finishes offline) or the
# Pi is on a real upstream (apt fetches and installs).
#
# Usage: raspimidihub-install-deb.sh <deb_path> [--reinstall]
#
#   --reinstall  Force apt to re-process the package even when the
#                same version is already installed. Used by the
#                "Reinstall to fetch optional packages" UI button —
#                same version, but Recommends now get pulled in.

set -e

DEB_PATH="$1"
REINSTALL_FLAG=""
if [ "${2-}" = "--reinstall" ]; then
    REINSTALL_FLAG="--reinstall"
fi
STATUS_FILE="/run/raspimidihub/update-status"

if [ -z "$DEB_PATH" ] || [ ! -f "$DEB_PATH" ]; then
    echo "Usage: $0 <deb_path> [--reinstall] (file must exist)" >&2
    exit 1
fi

mkdir -p /run/raspimidihub

write_status() {
    printf '%s\n' "$1" > "$STATUS_FILE.tmp"
    mv "$STATUS_FILE.tmp" "$STATUS_FILE"
}

VER=$(basename "$DEB_PATH" | sed -E 's/^raspimidihub_([0-9]+\.[0-9]+\.[0-9]+[a-z0-9]*)-[0-9]+_all\.deb$/\1/')

write_status "{\"step\":\"installing\",\"version\":\"$VER\"}"
mount -o remount,rw / || true

LOG=/tmp/raspimidihub-install-deb.log
# `apt update` is best-effort: if it fails (offline, mirror down) we
# still try the install — apt will use the cached indexes and may well
# succeed for an offline downgrade where every dep is already there.
apt-get update -q >"$LOG" 2>&1 || true

# DEBIAN_FRONTEND=noninteractive so dpkg never tries to prompt.
# Recommends ARE pulled — that's how Bluetooth's python3-dbus-next
# arrives on a Pi that was bootstrapped via the old dpkg-i path.
# A user who explicitly doesn't want optional packages can apt-get
# remove them after install; the cost of pulling extras once is
# smaller than the cost of silently disabled features.
if DEBIAN_FRONTEND=noninteractive apt-get install -y \
        $REINSTALL_FLAG -o Dpkg::Options::="--force-confnew" \
        "$DEB_PATH" >>"$LOG" 2>&1; then
    mount -o remount,ro / || true
    write_status "{\"step\":\"done\",\"version\":\"$VER\"}"
    exit 0
else
    mount -o remount,ro / || true
    # Last 600 chars of the log = the actual error (apt is chattier
    # than dpkg, the headline failure is at the bottom).
    ERR=$(tail -c 600 "$LOG" | tr '\n' ' ' | sed 's/"/\\"/g')
    write_status "{\"step\":\"error-install\",\"version\":\"$VER\",\"message\":\"apt failed: $ERR\"}"
    exit 1
fi
