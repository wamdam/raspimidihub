#!/bin/bash
# RaspiMIDIHub installer
# Usage: curl -sL https://github.com/wamdam/raspimidihub/releases/latest/download/install.sh | bash
set -e

echo "=== RaspiMIDIHub Installer ==="
echo ""

# Get latest release tag from GitHub API
echo "Checking latest release..."
TAG=$(curl -sL -o /dev/null -w '%{url_effective}' https://github.com/wamdam/raspimidihub/releases/latest | grep -oP 'v[\d.]+$')
if [ -z "$TAG" ]; then
    echo "Error: Could not determine latest release."
    exit 1
fi
echo "Latest release: $TAG"

BASE="https://github.com/wamdam/raspimidihub/releases/download/$TAG"
TMPDIR=$(mktemp -d)

echo "Downloading packages..."
wget -q --show-progress -O "$TMPDIR/raspimidihub.deb" "$BASE/raspimidihub_${TAG#v}-1_all.deb"

PACKAGES="$TMPDIR/raspimidihub.deb"

if wget -q --show-progress -O "$TMPDIR/raspimidihub-rosetup.deb" "$BASE/raspimidihub-rosetup_1.0.0-1_all.deb" 2>/dev/null; then
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
