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
Signed-By: /usr/share/keyrings/raspberrypi-archive-keyring.pgp
EOF
fi

sudo apt-get update -qq
sudo apt-get install -y -qq dpkg-dev bison flex bc libssl-dev kmod

mkdir -p "$BUILD"
cd "$BUILD"

# apt-get source would fetch the archive's NEWEST kernel source (the
# trixie Sources index lists only the current version), which won't
# modpost against the running kernel. Fetch the version-exact source
# from the pool instead — old versions linger there. curl goes through
# the reverse SOCKS tunnel (see kernel-build-notes.md).
SRCVER=$(dpkg-query -W -f='${source:Version}' "linux-image-$KVER")
SRCVER=${SRCVER#*:}                # strip epoch: 6.12.75-1+rpt1
UPSTREAM=${SRCVER%%-*}             # 6.12.75
SRCDIR=linux-$UPSTREAM
POOL=http://archive.raspberrypi.com/debian/pool/main/l/linux
CURL="curl -fsS --socks5-hostname localhost:1080"

# drop trees/tarballs from other versions (an earlier apt-get source
# run may have left the newest one here)
for d in linux-*/; do [ "$d" = "$SRCDIR/" ] || rm -rf "$d"; done 2>/dev/null || true
find . -maxdepth 1 -name 'linux_*' ! -name "linux_${SRCVER}*" ! -name "linux_${UPSTREAM}*" -delete 2>/dev/null || true

if [ ! -d "$SRCDIR" ]; then
  echo "== fetching kernel source $SRCVER from pool"
  $CURL -O "$POOL/linux_$SRCVER.dsc"
  for f in $(awk '/^Files:/{f=1;next} /^[^ ]/{f=0} f{print $3}' "linux_$SRCVER.dsc"); do
    [ -f "$f" ] || { echo "  fetching $f"; $CURL -O "$POOL/$f"; }
  done
  dpkg-source --no-check -x "linux_$SRCVER.dsc"
fi
cd "$SRCDIR"
V=$(make -s kernelversion)
[ "$V" = "$UPSTREAM" ] || { echo "source/kernel mismatch: $V vs $UPSTREAM"; exit 1; }

echo "== configuring"
cp "/boot/config-$KVER" .config
scripts/config --enable SND_SEQ_UMP
scripts/config --module SND_SEQ_UMP_CLIENT
scripts/config --enable SND_UMP_LEGACY_RAWMIDI
scripts/config --enable SND_USB_AUDIO_MIDI_V2
# The packaged kernel's release suffix (+rpt-rpi-v8) comes from the
# Debian build, not from /boot/config's CONFIG_LOCALVERSION — set it
# explicitly or vermagic mismatches and modprobe refuses the modules.
scripts/config --set-str LOCALVERSION "${KVER#"$UPSTREAM"}"
scripts/config --disable LOCALVERSION_AUTO
make olddefconfig
# Sanity: SND_UMP must have been selected as module by the above
grep -q "^CONFIG_SND_UMP=m" .config || { echo "SND_UMP not enabled?"; grep SND_UMP .config; exit 1; }

echo "== modules_prepare"
cp "$HDRS/Module.symvers" .
make -j4 modules_prepare
# Assert only AFTER modules_prepare: kernelrelease reads the generated
# include/config/auto.conf, which olddefconfig alone leaves stale.
REL=$(make -s kernelrelease)
[ "$REL" = "$KVER" ] || { echo "kernelrelease mismatch: $REL != $KVER"; exit 1; }

echo "== building sound/core + sound/usb"
make -j3 M=sound/core modules
# snd-usb-audio links against the just-built snd-ump exports; separate
# M= builds don't see each other's symbols without this. Feed modpost
# only the symbols the stock kernel does NOT already export — passing
# all of sound/core's exports collides with the root Module.symvers
# ("exported twice").
awk 'NR==FNR {seen[$2]=1; next} !($2 in seen)' \
    Module.symvers sound/core/Module.symvers > new-exports.symvers
echo "== new exports fed to sound/usb modpost:"; awk '{print "  " $2}' new-exports.symvers
make -j3 M=sound/usb KBUILD_EXTRA_SYMBOLS="$PWD/new-exports.symvers" modules

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
VMAGIC=$(/usr/sbin/modinfo "/lib/modules/$KVER/updates/snd-usb-audio.ko" | awk '/^vermagic/{print $2}')
echo "built: $VMAGIC / running: $KVER"
[ "$VMAGIC" = "$KVER" ] || { echo "VERMAGIC MISMATCH — do not reboot on this"; exit 1; }

sudo mount -o remount,ro / || true
echo "== done — reboot to load the new modules (sudo reboot)"
