#!/bin/bash
# Build + install UMP-enabled sound modules for the running RPi OS
# kernel. Run ON the Pi as the normal user (uses sudo inline).
# See kernel-build-notes.md. Idempotent: safe to re-run.
set -euo pipefail

KVER=$(uname -r)
BUILD=$HOME/midi2-kernel
HDRS=/usr/src/linux-headers-$KVER

echo "== UMP module build for $KVER"
[ -f "$HDRS/Module.symvers" ] || { echo "headers missing: $HDRS"; exit 1; }

sudo mount -o remount,rw /

# DNS: the hub's captive-portal dnsmasq answers every name with itself;
# /etc/resolv.conf -> /var/run/resolv.conf (tmpfs), override is
# runtime-only.
echo "nameserver 1.1.1.1" | sudo tee /var/run/resolv.conf >/dev/null

# deb-src for the raspberrypi.com kernel package
if [ ! -f /etc/apt/sources.list.d/rpt-src.sources ]; then
  sudo tee /etc/apt/sources.list.d/rpt-src.sources >/dev/null <<'EOF'
Types: deb-src
URIs: http://archive.raspberrypi.com/debian/
Suites: trixie
Components: main
Signed-By: /usr/share/keyrings/raspberrypi-archive-keyring.gpg
EOF
fi

sudo apt-get update -qq
sudo apt-get install -y -qq dpkg-dev bison flex bc libssl-dev kmod

mkdir -p "$BUILD"
cd "$BUILD"
if ! ls -d linux-*/ >/dev/null 2>&1; then
  echo "== fetching kernel source (apt source)"
  apt-get source "linux-image-$KVER"
fi
SRC=$(ls -d linux-*/ | head -1)
cd "$SRC"

echo "== configuring"
cp "/boot/config-$KVER" .config
scripts/config --enable SND_SEQ_UMP
scripts/config --module SND_SEQ_UMP_CLIENT
scripts/config --enable SND_UMP_LEGACY_RAWMIDI
scripts/config --enable SND_USB_AUDIO_MIDI_V2
make olddefconfig
# Sanity: SND_UMP must have been selected as module by the above
grep -q "^CONFIG_SND_UMP=m" .config || { echo "SND_UMP not enabled?"; grep SND_UMP .config; exit 1; }
# Vermagic must match the running kernel exactly
grep -q "^CONFIG_LOCALVERSION=\"+rpt-rpi-v8\"" .config || \
  echo "WARNING: check CONFIG_LOCALVERSION vs $KVER before installing"

echo "== modules_prepare"
cp "$HDRS/Module.symvers" .
make -j4 modules_prepare

echo "== building sound/core + sound/usb"
make -j3 M=sound/core modules
make -j3 M=sound/usb modules

echo "== built modules:"
find sound -name '*.ko' | sort

# Only install the ones we need: snd-seq (UMP-aware), snd-ump,
# snd-seq-ump-client, snd-usb-audio (+ its midi lib stays stock).
echo "== installing to /lib/modules/$KVER/updates/"
sudo mkdir -p "/lib/modules/$KVER/updates"
for m in sound/core/seq/snd-seq.ko sound/core/snd-ump.ko \
         sound/core/seq/snd-seq-ump-client.ko sound/usb/snd-usb-audio.ko; do
  [ -f "$m" ] && sudo cp "$m" "/lib/modules/$KVER/updates/" && echo "  $m"
done
sudo depmod -a

echo "== vermagic check:"
modinfo "/lib/modules/$KVER/updates/snd-usb-audio.ko" | grep -E "^vermagic"
echo "vermagic must match: $KVER"

sudo mount -o remount,ro / || true
echo "== done — reboot to load the new modules (sudo reboot)"
