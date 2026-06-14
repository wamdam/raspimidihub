#!/bin/bash
# Build the RaspiMIDIHub bootstrap image from upstream Raspberry Pi OS Lite (64-bit).
#
# Output: dist/raspimidihub-bootstrap-<upstream-date>.img.xz + dist/os-list.json
#
# Required tools (host packages):
#   sudo apt install libguestfs-tools qemu-user-static xz-utils curl
#
# pishrink.sh is fetched on demand into cache/.
#
# Run from the image/ directory. Re-running only re-downloads upstream if a newer
# RPi OS Lite image exists, and only rebuilds the customized image if any input
# (upstream img or any image/* file) is newer than the last build.

set -euo pipefail
cd "$(dirname "$0")"

# --- Config ----------------------------------------------------------------

RPI_URL="https://downloads.raspberrypi.com/raspios_lite_arm64/images/"
RPI_LATEST_REDIRECT="https://downloads.raspberrypi.com/raspios_lite_arm64_latest"

CACHE_DIR="cache"
WORK_DIR="work"
DIST_DIR="../dist"

mkdir -p "$CACHE_DIR" "$WORK_DIR" "$DIST_DIR"

# --- Tool check ------------------------------------------------------------

for t in virt-customize virt-sparsify xz curl sha256sum stat; do
    command -v "$t" >/dev/null || {
        echo "ERROR: '$t' not found. Install with:" >&2
        echo "  sudo apt install libguestfs-tools qemu-user-static xz-utils curl" >&2
        exit 1
    }
done

# --- 1. Resolve upstream URL + filename ------------------------------------

echo "[build] resolving latest Raspberry Pi OS Lite (64-bit) URL..."
RESOLVED=$(curl -sLI -o /dev/null -w '%{url_effective}' "$RPI_LATEST_REDIRECT")
UPSTREAM_NAME=$(basename "$RESOLVED")
UPSTREAM_FILE="$CACHE_DIR/$UPSTREAM_NAME"
echo "[build] upstream: $UPSTREAM_NAME"

# Date stamp from filename (e.g. 2025-10-22-raspios-bookworm-arm64-lite.img.xz)
UPSTREAM_DATE=$(echo "$UPSTREAM_NAME" | grep -oE '^[0-9]{4}-[0-9]{2}-[0-9]{2}' || date +%Y-%m-%d)

# --- 2. Download only if newer than local ----------------------------------

curl -L --fail --time-cond "$UPSTREAM_FILE" -o "$UPSTREAM_FILE" "$RESOLVED" || {
    echo "ERROR: download failed" >&2
    exit 1
}

# --- 3. Decide whether to rebuild ------------------------------------------

OUT_IMG_XZ="$DIST_DIR/raspimidihub-bootstrap-$UPSTREAM_DATE.img.xz"

needs_build=0
if [ ! -f "$OUT_IMG_XZ" ]; then
    needs_build=1
else
    for f in "$UPSTREAM_FILE" firstboot-led bootstrap-run apply-wifi-country raspimidihub-bootstrap.service raspimidihub-apply-wifi-country.service build.sh; do
        if [ "$f" -nt "$OUT_IMG_XZ" ]; then
            needs_build=1
            break
        fi
    done
fi

if [ "$needs_build" = 0 ]; then
    echo "[build] $OUT_IMG_XZ already up to date — skipping image rebuild, regenerating manifest only"
else

# --- 4. Clean previous build artifacts -------------------------------------

echo "[build] cleaning previous build artifacts..."
sudo rm -rf "$WORK_DIR"/* 2>/dev/null || rm -rf "$WORK_DIR"/* 2>/dev/null || true
rm -f "$OUT_IMG_XZ"

# --- 5. Decompress upstream into work/ -------------------------------------

WORK_IMG="$WORK_DIR/raspimidihub-bootstrap.img"
echo "[build] decompressing upstream image..."
xz -dc "$UPSTREAM_FILE" > "$WORK_IMG"

# --- 5. virt-customize: drop in files + enable service ---------------------

echo "[build] customizing image (virt-customize, runs under sudo)..."
sudo virt-customize -a "$WORK_IMG" \
    --copy-in firstboot-led:/usr/local/sbin/ \
    --chmod 0755:/usr/local/sbin/firstboot-led \
    --upload bootstrap-run:/usr/local/sbin/raspimidihub-bootstrap-run \
    --chmod 0755:/usr/local/sbin/raspimidihub-bootstrap-run \
    --upload apply-wifi-country:/usr/local/sbin/raspimidihub-apply-wifi-country \
    --chmod 0755:/usr/local/sbin/raspimidihub-apply-wifi-country \
    --copy-in raspimidihub-bootstrap.service:/etc/systemd/system/ \
    --copy-in raspimidihub-apply-wifi-country.service:/etc/systemd/system/ \
    --mkdir /etc/systemd/system/multi-user.target.wants \
    --link /etc/systemd/system/raspimidihub-bootstrap.service:/etc/systemd/system/multi-user.target.wants/raspimidihub-bootstrap.service \
    --link /etc/systemd/system/raspimidihub-apply-wifi-country.service:/etc/systemd/system/multi-user.target.wants/raspimidihub-apply-wifi-country.service \
    --firstboot-command 'systemctl enable --now ssh'
    # sshd is enabled so a FAILED first-boot bootstrap is diagnosable: the user
    # can SSH in (with the key/password set in the Pi Imager wizard) and read
    # `journalctl -u raspimidihub-bootstrap`. Stock RPi OS / cloud-init does NOT
    # reliably bring sshd up on first boot, so we cannot rely on it. We use
    # --firstboot-command (not --run-command): the build host is x86_64 and the
    # guest is aarch64, so virt-customize cannot run commands in the guest
    # offline — the firstboot script runs natively on the Pi at first boot
    # instead, which also avoids any host-key generation ordering races.
    # `--now` brings sshd up in the very boot where bootstrap runs (a failed
    # bootstrap does not reboot). `enable` persists it onto the finished
    # appliance — acceptable under the trusted-environment / AP-password model.
sudo chown "$USER:$(id -gn)" "$WORK_IMG"

# --- 6. virt-sparsify: zero free blocks so xz can compress them away --------
# Replaces pishrink. Does NOT touch /var/lib/cloud/ or /var/log/, which means
# cloud-init's first-boot customization (user-data, network-config) keeps
# working as upstream RPi OS Trixie intends.

echo "[build] sparsifying free blocks (virt-sparsify, runs under sudo)..."
SPARSE_IMG="$WORK_DIR/raspimidihub-bootstrap-sparse.img"
rm -f "$SPARSE_IMG"
sudo virt-sparsify --machine-readable "$WORK_IMG" "$SPARSE_IMG"
sudo chown "$USER:$(id -gn)" "$SPARSE_IMG"
mv -f "$SPARSE_IMG" "$WORK_IMG"

# --- 7. Compress -----------------------------------------------------------

echo "[build] compressing with xz -T0 -9..."
xz -T0 -9 -f "$WORK_IMG"  # produces $WORK_IMG.xz
mv "$WORK_IMG.xz" "$OUT_IMG_XZ"

fi  # end of needs_build branch

# --- 8. Compute sizes + hashes + emit os-list.json -------------------------

DOWNLOAD_SIZE=$(stat -c%s "$OUT_IMG_XZ")
DOWNLOAD_SHA=$(sha256sum "$OUT_IMG_XZ" | awk '{print $1}')

# Extract size = uncompressed .img size. Recompute from .img.xz header.
EXTRACT_SIZE=$(xz -l --robot "$OUT_IMG_XZ" | awk '/^totals/ {print $5}')
EXTRACT_SHA=$(xz -dc "$OUT_IMG_XZ" | sha256sum | awk '{print $1}')

RELEASE_URL="${RELEASE_URL:-REPLACE_WITH_RELEASE_ASSET_URL}"

cat > "$DIST_DIR/os-list.json" <<JSON
{
  "imager": {
    "latest_version": "2.0.0",
    "url": "https://github.com/wamdam/raspimidihub"
  },
  "os_list": [
    {
      "name": "RaspiMIDIHub OS",
      "description": "Plug-and-play USB MIDI hub appliance. Auto-installs the latest RaspiMIDIHub release on first boot — requires internet (ethernet, USB tether, or WiFi configured via the Pi Imager wizard).",
      "icon": "https://raw.githubusercontent.com/wamdam/raspimidihub/main/website/screenshots/video-thumbnail.jpg",
      "url": "$RELEASE_URL",
      "release_date": "$UPSTREAM_DATE",
      "extract_size": $EXTRACT_SIZE,
      "extract_sha256": "$EXTRACT_SHA",
      "image_download_size": $DOWNLOAD_SIZE,
      "image_download_sha256": "$DOWNLOAD_SHA",
      "init_format": "cloudinit-rpi",
      "devices": ["pi3-64bit","pi4-64bit","pi5-64bit","pizero2"]
    }
  ]
}
JSON

# --- Done ------------------------------------------------------------------

echo ""
echo "[build] done."
echo "  image:    $OUT_IMG_XZ ($((DOWNLOAD_SIZE / 1024 / 1024)) MB)"
echo "  manifest: $DIST_DIR/os-list.json"
echo ""
echo "Next steps:"
echo "  1. Upload $OUT_IMG_XZ to a GitHub release"
echo "  2. RELEASE_URL=<asset-url> bash $0    # to regenerate os-list.json with the real URL"
echo "  3. cp $DIST_DIR/os-list.json image/os-list.json && git commit"
