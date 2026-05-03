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

# BUILD_TAG is the literal version this install.sh was packaged for.
# The placeholder "@@VERSION@@" means it's running from source (no
# release substitution); fall back to GitHub's /releases/latest in
# that case so `bash scripts/install.sh` from a source checkout still
# works for testing.
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
sudo apt install -y $PACKAGES

rm -rf "$TMPDIR"

echo ""
echo "=== Installation complete ==="
echo "Reboot now to activate read-only filesystem:"
echo "  sudo reboot"
echo ""
echo "After reboot, connect to WiFi AP 'RaspiMIDIHub-XXXX' (password: midihub1)"
echo "Then open http://192.168.4.1 in your browser."
