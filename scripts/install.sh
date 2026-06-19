#!/bin/bash
# RaspiMIDIHub installer.
#
# Each release ships its own install.sh with `BUILD_TAG` substituted by
# the Makefile (`make release`). Running an install.sh always installs
# THE release it was downloaded from, even when newer releases exist
# upstream. Use $TAG to override.
#
# Usage:
#   curl -sL https://github.com/wamdam/raspimidihub/releases/latest/download/install.sh | bash
#   curl -sL https://github.com/wamdam/raspimidihub/releases/download/v3.0.0a2/install.sh | bash
#   TAG=v2.0.9 bash install.sh   # force a specific version
set -e

echo "=== RaspiMIDIHub Installer ==="
echo ""

# Preflight: the installer pulls the package + its dependencies from
# GitHub, so the Pi must reach the internet first. Without this check a
# fresh, offline image just aborts mid-download (wget -q is silent, then
# `set -e` exits) with no hint why — the single most common install
# failure. Fail fast with an actionable message instead. The most
# frequent cause on a freshly-flashed Pi is WiFi blocked because no WiFi
# *country* was set at flash time (Raspberry Pi OS rfkill-blocks the
# radio until a country exists), so we call that out explicitly.
if ! curl -sSf --max-time 10 -o /dev/null https://github.com 2>/dev/null; then
    echo "ERROR: No internet connection — can't reach github.com." >&2
    echo "" >&2
    echo "The installer downloads the RaspiMIDIHub package and its" >&2
    echo "dependencies from GitHub, so this Pi needs internet during install." >&2
    echo "" >&2
    echo "Common causes:" >&2
    echo "  - Ethernet on an isolated LAN with no gateway to the internet." >&2
    echo "  - WiFi radio blocked because no WiFi country was set when" >&2
    echo "    flashing (a fresh image keeps WiFi rfkill-blocked until then):" >&2
    echo "        sudo raspi-config nonint do_wifi_country DE   # your ISO code" >&2
    echo "        # or: sudo iw reg set DE && sudo nmcli radio wifi on" >&2
    echo "    then connect to your network." >&2
    echo "" >&2
    echo "Re-run this installer once the Pi can reach the internet." >&2
    exit 1
fi

# BUILD_TAG is the literal version this install.sh was packaged for.
# "unreleased" means it's running from a source checkout (the Makefile
# rewrites this line to the real tag in each release's install.sh); fall
# back to GitHub's /releases/latest in that case so `bash
# scripts/install.sh` from source still works for testing.
BUILD_TAG="unreleased"
if [ -z "${TAG:-}" ]; then
    if [ "$BUILD_TAG" = "unreleased" ]; then
        echo "Source-tree install (no baked tag) — checking GitHub for latest release..."
        TAG=$(curl -sL -o /dev/null -w '%{url_effective}' https://github.com/wamdam/raspimidihub/releases/latest | grep -oP 'v[\d.a-z]+$')
    else
        TAG="$BUILD_TAG"
    fi
fi
if [ -z "$TAG" ]; then
    echo "Error: Could not determine release tag."
    exit 1
fi
echo "Installing release: $TAG"

BASE="https://github.com/wamdam/raspimidihub/releases/download/$TAG"
TMPDIR=$(mktemp -d)

echo "Downloading packages..."
wget -q --show-progress -O "$TMPDIR/raspimidihub.deb" "$BASE/raspimidihub_${TAG#v}-1_all.deb"

PACKAGES="$TMPDIR/raspimidihub.deb"

if wget -q --show-progress -O "$TMPDIR/raspimidihub-rosetup.deb" "$BASE/raspimidihub-rosetup_1.0.2-1_all.deb" 2>/dev/null; then
    PACKAGES="$PACKAGES $TMPDIR/raspimidihub-rosetup.deb"
else
    echo "Note: Read-only filesystem package not found in release, skipping."
    echo "      You can install it separately later if needed."
fi

echo ""
echo "Installing (this will download dependencies and start the service)..."
# Refresh the apt index first. The bootstrap image ships a baked index that
# goes stale as Debian trixie rolls dependencies to new point-releases; the
# cached index then points at .deb files no longer in the pool → 404 → abort.
# An update before install makes the bootstrap robust regardless of image age.
sudo apt-get update
sudo apt install -y --fix-missing $PACKAGES

rm -rf "$TMPDIR"

echo ""
echo "=== Installation complete ==="
echo "Reboot now to activate read-only filesystem:"
echo "  sudo reboot"
echo ""
echo "After reboot, connect to WiFi AP 'RaspiMIDIHub-XXXX' (password: midihub1)"
echo "Then open http://192.168.4.1 in your browser."
