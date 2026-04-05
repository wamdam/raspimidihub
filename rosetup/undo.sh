#!/bin/bash
# raspimidihub-rosetup undo: Reverse all read-only filesystem changes.
#
# Restores files from /var/lib/raspimidihub-rosetup/backup/ and unmasks services.
# Called by the package postrm on purge.

set -euo pipefail

BACKUP_DIR="/var/lib/raspimidihub-rosetup/backup"

log() {
    echo "[rosetup-undo] $*"
}

warn() {
    echo "[rosetup-undo] WARNING: $*" >&2
}

if [ "$(id -u)" -ne 0 ]; then
    echo "[rosetup-undo] ERROR: Must be run as root" >&2
    exit 1
fi

# ============================================================
# Restore backed-up files
# ============================================================

# ============================================================
# Remove symlinks first (so backup restore works cleanly)
# ============================================================

log "Removing symlinks..."

# resolv.conf: remove symlink before restoring backup
if [ -L /etc/resolv.conf ]; then
    rm -f /etc/resolv.conf
    log "  Removed /etc/resolv.conf symlink"
fi

# Random seed: remove symlink, create fresh file
SEED="/var/lib/systemd/random-seed"
if [ -L "$SEED" ]; then
    rm -f "$SEED"
    dd if=/dev/urandom of="$SEED" bs=512 count=1 2>/dev/null
    chmod 600 "$SEED"
    log "  Restored random-seed"
fi

# NetworkManager state dirs: restore if symlinked
for nm_dir in /var/lib/NetworkManager /var/lib/dhcpcd; do
    if [ -L "$nm_dir" ]; then
        target=$(readlink "$nm_dir")
        rm -f "$nm_dir"
        if [ -d "$target" ]; then
            cp -a "$target" "$nm_dir"
        else
            mkdir -p "$nm_dir"
        fi
        log "  Restored $nm_dir as directory"
    fi
done

# ============================================================
# Restore backed-up files
# ============================================================

log "Restoring backed-up files..."

if [ -d "$BACKUP_DIR" ]; then
    find "$BACKUP_DIR" -type f | while read -r backup; do
        original="/${backup#$BACKUP_DIR/}"
        if [ -f "$backup" ]; then
            cp -a "$backup" "$original"
            log "  Restored $original"
        fi
    done
else
    warn "No backup directory found at $BACKUP_DIR"
fi

# ============================================================
# Unmask services
# ============================================================

log "Unmasking services..."

SERVICES_TO_UNMASK=(
    dphys-swapfile
    fake-hwclock
    systemd-rfkill.service
    systemd-rfkill.socket
    apt-daily.timer
    apt-daily-upgrade.timer
    man-db.timer
    systemd-timesyncd
    cloud-init-main.service
    cloud-init-hotplugd.service
    cloud-init-hotplugd.socket
    rpi-resize-swap-file.service
)

for svc in "${SERVICES_TO_UNMASK[@]}"; do
    state=$(systemctl is-enabled "$svc" 2>/dev/null || true)
    if [ "$state" = "masked" ]; then
        systemctl unmask "$svc"
        log "  Unmasked $svc"
    fi
done

# Re-enable systemd-timesyncd
if systemctl is-enabled systemd-timesyncd &>/dev/null 2>&1; then
    true  # already enabled
else
    systemctl enable systemd-timesyncd 2>/dev/null || true
    log "  Re-enabled systemd-timesyncd"
fi

# ============================================================
# Remove systemd overrides we created
# ============================================================

log "Removing systemd overrides..."

for override_dir in \
    /etc/systemd/system/ntpsec.service.d \
    /etc/systemd/system/systemd-random-seed.service.d; do
    if [ -d "$override_dir" ]; then
        rm -rf "$override_dir"
        log "  Removed $override_dir"
    fi
done

# ============================================================
# Remove bash.bashrc additions
# ============================================================

log "Cleaning up bash.bashrc..."

BASHRC="/etc/bash.bashrc"
if [ -f "$BASHRC" ]; then
    # Remove everything from the rosetup marker to the end of the block
    sed -i '/^# raspimidihub-rosetup/,/^$/d' "$BASHRC"
    # Also remove any trailing ro_prompt/alias lines if marker removal missed them
    sed -i '/^ro_prompt()/,/^}/d' "$BASHRC"
    sed -i "/^alias rw='sudo mount/d" "$BASHRC"
    sed -i "/^alias ro='sudo mount/d" "$BASHRC"
    sed -i '/^export PS1=.*ro_prompt/d' "$BASHRC"
    log "  Cleaned bash.bashrc"
fi

# ============================================================
# Remove bash_logout additions
# ============================================================

log "Cleaning up bash.bash_logout..."

BASH_LOGOUT="/etc/bash.bash_logout"
if [ -f "$BASH_LOGOUT" ]; then
    sed -i '/^# raspimidihub-rosetup/,/^$/d' "$BASH_LOGOUT"
    sed -i '/remount,ro.*2>\/dev\/null/d' "$BASH_LOGOUT"
    sed -i '/on \/ .*\\brw\\b/d' "$BASH_LOGOUT"
    log "  Cleaned bash.bash_logout"
fi

# ============================================================
# Restore cmdline.txt.bak if it exists
# ============================================================

if [ -f /boot/firmware/cmdline.txt.bak ]; then
    cp -a /boot/firmware/cmdline.txt.bak /boot/firmware/cmdline.txt
    rm -f /boot/firmware/cmdline.txt.bak
    log "  Restored cmdline.txt from backup"
fi

# ============================================================
# Reload systemd
# ============================================================

systemctl daemon-reload

# ============================================================
# Cleanup
# ============================================================

log "Removing backup directory..."
rm -rf "$BACKUP_DIR"
rmdir /var/lib/raspimidihub-rosetup 2>/dev/null || true

log "Undo complete. Reboot to return to read-write filesystem."

exit 0
