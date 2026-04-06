#!/bin/bash
# External updater script — runs outside the main service so dpkg can
# restart raspimidihub without killing the update process.
#
# Usage: raspimidihub-update.sh <deb_url>

set -e

DEB_URL="$1"
DEB_PATH="/tmp/raspimidihub-update.deb"
STATUS_FILE="/run/raspimidihub/update-status"

if [ -z "$DEB_URL" ]; then
    echo "Usage: $0 <deb_url>" >&2
    exit 1
fi

write_status() {
    echo "$1" > "$STATUS_FILE"
}

mkdir -p /run/raspimidihub

write_status "downloading"
if ! wget -q -O "$DEB_PATH" "$DEB_URL"; then
    write_status "error: download failed"
    exit 1
fi

write_status "installing"
mount -o remount,rw / || true
if dpkg -i "$DEB_PATH" 2>/tmp/raspimidihub-update.log; then
    mount -o remount,ro / || true
    write_status "done"
else
    mount -o remount,ro / || true
    write_status "error: install failed"
    exit 1
fi

rm -f "$DEB_PATH"
