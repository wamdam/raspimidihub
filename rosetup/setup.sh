#!/bin/bash
# raspimidihub-rosetup: Make a Raspberry Pi root filesystem read-only.
#
# This script is idempotent — running it multiple times produces the same result.
# Every file modified is backed up first to /var/lib/raspimidihub-rosetup/backup/.
#
# Usage:
#   raspimidihub-rosetup [--dry-run]
#
# FR-2.1 through FR-2.11 from the RaspiMIDIHub FSD.

set -euo pipefail

BACKUP_DIR="/var/lib/raspimidihub-rosetup/backup"
DRY_RUN=false
CHANGES_MADE=0

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        *) echo "Unknown argument: $arg"; exit 1 ;;
    esac
done

# --- Helpers ---

log() {
    echo "[rosetup] $*"
}

warn() {
    echo "[rosetup] WARNING: $*" >&2
}

die() {
    echo "[rosetup] ERROR: $*" >&2
    exit 1
}

backup_file() {
    local file="$1"
    if [ ! -f "$file" ]; then
        return
    fi
    local rel="${file#/}"
    local dest="$BACKUP_DIR/$rel"
    if [ -f "$dest" ]; then
        return  # already backed up
    fi
    if $DRY_RUN; then
        log "Would back up $file"
        return
    fi
    mkdir -p "$(dirname "$dest")"
    cp -a "$file" "$dest"
    log "Backed up $file"
}

# Check if a line/pattern already exists in a file
file_contains() {
    grep -qF "$1" "$2" 2>/dev/null
}

file_contains_regex() {
    grep -qE "$1" "$2" 2>/dev/null
}

# --- Precondition checks (FR-3.6) ---

log "Checking preconditions..."

if [ "$(id -u)" -ne 0 ] && ! $DRY_RUN; then
    die "Must be run as root (or use --dry-run)"
fi

if ! file_contains "raspb" /etc/os-release && ! file_contains "Raspberry" /etc/os-release; then
    die "This does not appear to be Raspberry Pi OS (/etc/os-release)"
fi

if [ ! -f /boot/firmware/cmdline.txt ]; then
    die "/boot/firmware/cmdline.txt not found — is this Raspberry Pi OS?"
fi

if [ ! -f /etc/fstab ]; then
    die "/etc/fstab not found"
fi

log "Preconditions OK"

if $DRY_RUN; then
    log "=== DRY RUN MODE — no changes will be made ==="
fi

# Create backup directory
if ! $DRY_RUN; then
    mkdir -p "$BACKUP_DIR"
fi

# ============================================================
# FR-2.2: tmpfs mounts
# ============================================================

TMPFS_MOUNTS=(
    "tmpfs /tmp tmpfs nosuid,nodev 0 0"
    "tmpfs /var/tmp tmpfs nosuid,nodev 0 0"
    "tmpfs /var/log tmpfs nosuid,nodev,size=25M 0 0"
    "tmpfs /var/spool/mail tmpfs nosuid,nodev 0 0"
    "tmpfs /var/spool/rsyslog tmpfs nosuid,nodev 0 0"
    "tmpfs /var/lib/logrotate tmpfs nosuid,nodev 0 0"
    "tmpfs /var/lib/sudo tmpfs nosuid,nodev,mode=0700 0 0"
)

log "Configuring tmpfs mounts (FR-2.2)..."
backup_file /etc/fstab

for entry in "${TMPFS_MOUNTS[@]}"; do
    mount_point=$(echo "$entry" | awk '{print $2}')

    # Ensure mount point directory exists
    if [ ! -d "$mount_point" ]; then
        if $DRY_RUN; then
            log "  Would create directory $mount_point"
        else
            mkdir -p "$mount_point"
            log "  Created directory $mount_point"
        fi
    fi

    if file_contains "$mount_point" /etc/fstab; then
        log "  $mount_point already in fstab, skipping"
    else
        if $DRY_RUN; then
            log "  Would add: $entry"
        else
            echo "$entry" >> /etc/fstab
            log "  Added: $mount_point"
        fi
        CHANGES_MADE=1
    fi
done

# ============================================================
# FR-2.1: Root filesystem read-only
# ============================================================

log "Setting root and boot to read-only in fstab (FR-2.1)..."

# Add 'ro' to root mount options if not already present
if file_contains_regex "^PARTUUID=.*\s+/\s+ext4\s+.*\bro\b" /etc/fstab; then
    log "  Root already has 'ro' in fstab, skipping"
else
    if $DRY_RUN; then
        log "  Would add 'ro' to root mount in fstab"
    else
        sed -i 's|\(PARTUUID=[^ ]*\s\+/\s\+ext4\s\+\)\([^ ]*\)|\1\2,ro|' /etc/fstab
        log "  Added 'ro' to root mount"
    fi
    CHANGES_MADE=1
fi

# Add 'ro' to boot mount options
if file_contains_regex "^PARTUUID=.*\s+/boot/firmware\s+vfat\s+.*\bro\b" /etc/fstab; then
    log "  Boot already has 'ro' in fstab, skipping"
else
    if $DRY_RUN; then
        log "  Would add 'ro' to boot mount in fstab"
    else
        sed -i 's|\(PARTUUID=[^ ]*\s\+/boot/firmware\s\+vfat\s\+\)\([^ ]*\)|\1\2,ro|' /etc/fstab
        log "  Added 'ro' to boot mount"
    fi
    CHANGES_MADE=1
fi

# ============================================================
# FR-2.3: fsck.mode=skip + disable swap
# ============================================================

log "Configuring kernel command line (FR-2.3)..."
backup_file /boot/firmware/cmdline.txt

# Also create explicit .bak (FR-3.8)
if ! $DRY_RUN && [ ! -f /boot/firmware/cmdline.txt.bak ]; then
    cp -a /boot/firmware/cmdline.txt /boot/firmware/cmdline.txt.bak
    log "  Created cmdline.txt.bak"
fi

if file_contains "fsck.mode=skip" /boot/firmware/cmdline.txt; then
    log "  fsck.mode=skip already present, skipping"
else
    if $DRY_RUN; then
        log "  Would append fsck.mode=skip to cmdline.txt"
    else
        sed -i 's/$/ fsck.mode=skip/' /boot/firmware/cmdline.txt
        log "  Appended fsck.mode=skip"
    fi
    CHANGES_MADE=1
fi

# Append 'ro' to cmdline.txt for early ro mount
if file_contains_regex '\bro\b' /boot/firmware/cmdline.txt; then
    # Check it's actually 'ro' and not part of 'root=' etc.
    if grep -qP '(?<!\w)ro(?!\w)' /boot/firmware/cmdline.txt 2>/dev/null || \
       grep -q ' ro$\| ro ' /boot/firmware/cmdline.txt; then
        log "  'ro' already in cmdline.txt, skipping"
    else
        if $DRY_RUN; then
            log "  Would append 'ro' to cmdline.txt"
        else
            sed -i 's/$/ ro/' /boot/firmware/cmdline.txt
            log "  Appended 'ro' to cmdline.txt"
        fi
        CHANGES_MADE=1
    fi
else
    if $DRY_RUN; then
        log "  Would append 'ro' to cmdline.txt"
    else
        sed -i 's/$/ ro/' /boot/firmware/cmdline.txt
        log "  Appended 'ro' to cmdline.txt"
    fi
    CHANGES_MADE=1
fi

# Disable swap
log "Disabling swap (FR-2.3)..."
if systemctl is-enabled dphys-swapfile &>/dev/null; then
    if $DRY_RUN; then
        log "  Would mask dphys-swapfile"
    else
        systemctl stop dphys-swapfile 2>/dev/null || true
        systemctl mask dphys-swapfile
        log "  Masked dphys-swapfile"
    fi
    CHANGES_MADE=1
else
    log "  dphys-swapfile not found or already masked, skipping"
fi

if ! $DRY_RUN; then
    swapoff -a 2>/dev/null || true
fi

# ============================================================
# FR-2.4: NTP with drift file on tmpfs
# ============================================================

log "Configuring NTP (FR-2.4)..."

# Disable systemd-timesyncd in favor of ntpsec
if systemctl is-enabled systemd-timesyncd &>/dev/null; then
    if $DRY_RUN; then
        log "  Would disable systemd-timesyncd"
    else
        systemctl disable systemd-timesyncd
        systemctl stop systemd-timesyncd 2>/dev/null || true
        log "  Disabled systemd-timesyncd"
    fi
    CHANGES_MADE=1
fi

# Install ntpsec if not present
if ! dpkg -l ntpsec &>/dev/null; then
    if $DRY_RUN; then
        log "  Would install ntpsec (requires internet)"
    else
        log "  Installing ntpsec..."
        apt-get install -y -qq ntpsec || warn "Failed to install ntpsec — no internet? Install manually."
    fi
fi

# Configure ntpsec drift file to tmpfs
if [ -f /etc/ntpsec/ntp.conf ]; then
    backup_file /etc/ntpsec/ntp.conf
    if file_contains "/var/tmp/ntp.drift" /etc/ntpsec/ntp.conf; then
        log "  NTP drift file already on tmpfs, skipping"
    else
        if $DRY_RUN; then
            log "  Would set NTP driftfile to /var/tmp/ntp.drift"
        else
            sed -i 's|^driftfile.*|driftfile /var/tmp/ntp.drift|' /etc/ntpsec/ntp.conf
            log "  Set NTP driftfile to /var/tmp/ntp.drift"
        fi
        CHANGES_MADE=1
    fi
fi

# Create systemd override for ntpsec to disable PrivateTmp
NTP_OVERRIDE_DIR="/etc/systemd/system/ntpsec.service.d"
NTP_OVERRIDE="$NTP_OVERRIDE_DIR/override.conf"
if [ ! -f "$NTP_OVERRIDE" ]; then
    if $DRY_RUN; then
        log "  Would create ntpsec PrivateTmp=false override"
    else
        mkdir -p "$NTP_OVERRIDE_DIR"
        cat > "$NTP_OVERRIDE" <<'NTPEOF'
[Service]
PrivateTmp=false
NTPEOF
        log "  Created ntpsec PrivateTmp=false override"
    fi
    CHANGES_MADE=1
fi

# ============================================================
# FR-2.5: NetworkManager configuration
# ============================================================

log "Configuring NetworkManager for read-only (FR-2.5)..."

NM_CONF="/etc/NetworkManager/NetworkManager.conf"
if [ -f "$NM_CONF" ]; then
    backup_file "$NM_CONF"

    if file_contains "rc-manager=file" "$NM_CONF"; then
        log "  rc-manager=file already set, skipping"
    else
        if $DRY_RUN; then
            log "  Would add rc-manager=file to NetworkManager.conf"
        else
            if file_contains "[main]" "$NM_CONF"; then
                sed -i '/^\[main\]/a rc-manager=file' "$NM_CONF"
            else
                echo -e "\n[main]\nrc-manager=file" >> "$NM_CONF"
            fi
            log "  Added rc-manager=file"
        fi
        CHANGES_MADE=1
    fi
fi

# Symlink resolv.conf to /var/run
if [ ! -L /etc/resolv.conf ] || [ "$(readlink /etc/resolv.conf)" != "/var/run/resolv.conf" ]; then
    if $DRY_RUN; then
        log "  Would symlink /etc/resolv.conf -> /var/run/resolv.conf"
    else
        backup_file /etc/resolv.conf
        rm -f /etc/resolv.conf
        ln -s /var/run/resolv.conf /etc/resolv.conf
        log "  Symlinked resolv.conf to /var/run"
    fi
    CHANGES_MADE=1
else
    log "  resolv.conf already symlinked, skipping"
fi

# Symlink NM state directories to /var/run
for nm_dir in /var/lib/NetworkManager /var/lib/dhcpcd; do
    run_dir="/var/run/$(basename "$nm_dir")"
    if [ -d "$nm_dir" ] && [ ! -L "$nm_dir" ]; then
        if $DRY_RUN; then
            log "  Would symlink $nm_dir -> $run_dir"
        else
            # Preserve contents for first boot
            mkdir -p "$run_dir" 2>/dev/null || true
            cp -a "$nm_dir"/. "$run_dir"/ 2>/dev/null || true
            rm -rf "$nm_dir"
            ln -s "$run_dir" "$nm_dir"
            log "  Symlinked $nm_dir -> $run_dir"
        fi
        CHANGES_MADE=1
    else
        log "  $nm_dir already handled, skipping"
    fi
done

# ============================================================
# FR-2.6: Random seed on tmpfs
# ============================================================

log "Moving random seed to tmpfs (FR-2.6)..."

SEED="/var/lib/systemd/random-seed"
if [ -f "$SEED" ] && [ ! -L "$SEED" ]; then
    if $DRY_RUN; then
        log "  Would symlink random-seed to /tmp/random-seed"
    else
        rm -f "$SEED"
        ln -s /tmp/random-seed "$SEED"
        log "  Symlinked random-seed to /tmp"
    fi
    CHANGES_MADE=1
elif [ -L "$SEED" ]; then
    log "  Random seed already symlinked, skipping"
fi

# Create systemd override to pre-create the file
SEED_OVERRIDE_DIR="/etc/systemd/system/systemd-random-seed.service.d"
SEED_OVERRIDE="$SEED_OVERRIDE_DIR/override.conf"
if [ ! -f "$SEED_OVERRIDE" ]; then
    if $DRY_RUN; then
        log "  Would create random-seed service override"
    else
        mkdir -p "$SEED_OVERRIDE_DIR"
        cat > "$SEED_OVERRIDE" <<'SEEDEOF'
[Service]
ExecStartPre=/bin/sh -c '[ -f /tmp/random-seed ] || dd if=/dev/urandom of=/tmp/random-seed bs=512 count=1 2>/dev/null'
SEEDEOF
        log "  Created random-seed service override"
    fi
    CHANGES_MADE=1
fi

# ============================================================
# FR-2.7: Disable unnecessary services
# ============================================================

log "Disabling unnecessary services (FR-2.7)..."

SERVICES_TO_MASK=(
    systemd-rfkill.service
    systemd-rfkill.socket
    apt-daily.timer
    apt-daily-upgrade.timer
    man-db.timer
)

for svc in "${SERVICES_TO_MASK[@]}"; do
    if systemctl is-enabled "$svc" &>/dev/null 2>&1; then
        state=$(systemctl is-enabled "$svc" 2>/dev/null || true)
        if [ "$state" = "masked" ]; then
            log "  $svc already masked, skipping"
        else
            if $DRY_RUN; then
                log "  Would mask $svc"
            else
                systemctl stop "$svc" 2>/dev/null || true
                systemctl mask "$svc"
                log "  Masked $svc"
            fi
            CHANGES_MADE=1
        fi
    else
        log "  $svc not found, skipping"
    fi
done

# ============================================================
# FR-2.8: Mask fake-hwclock
# ============================================================

log "Masking fake-hwclock (FR-2.8)..."

if systemctl is-enabled fake-hwclock &>/dev/null 2>&1; then
    state=$(systemctl is-enabled fake-hwclock 2>/dev/null || true)
    if [ "$state" = "masked" ]; then
        log "  fake-hwclock already masked, skipping"
    else
        if $DRY_RUN; then
            log "  Would mask fake-hwclock"
        else
            systemctl stop fake-hwclock 2>/dev/null || true
            systemctl mask fake-hwclock
            log "  Masked fake-hwclock"
        fi
        CHANGES_MADE=1
    fi
else
    log "  fake-hwclock not found, skipping"
fi

# ============================================================
# FR-2.11: Limit journald size
# ============================================================

log "Configuring journald (FR-2.11)..."

JOURNALD_CONF="/etc/systemd/journald.conf"
backup_file "$JOURNALD_CONF"

if file_contains "SystemMaxUse=25M" "$JOURNALD_CONF"; then
    log "  journald SystemMaxUse already set, skipping"
else
    if $DRY_RUN; then
        log "  Would set SystemMaxUse=25M in journald.conf"
    else
        if file_contains_regex "^#?SystemMaxUse=" "$JOURNALD_CONF"; then
            sed -i 's|^#\?SystemMaxUse=.*|SystemMaxUse=25M|' "$JOURNALD_CONF"
        else
            sed -i '/^\[Journal\]/a SystemMaxUse=25M' "$JOURNALD_CONF"
        fi
        log "  Set SystemMaxUse=25M"
    fi
    CHANGES_MADE=1
fi

# ============================================================
# FR-2.9: Shell aliases rw/ro with prompt indicator
# ============================================================

log "Adding shell aliases (FR-2.9)..."

BASHRC="/etc/bash.bashrc"
backup_file "$BASHRC"

RO_MARKER="# raspimidihub-rosetup"

if file_contains "$RO_MARKER" "$BASHRC"; then
    log "  Shell aliases already present, skipping"
else
    if $DRY_RUN; then
        log "  Would add rw/ro aliases and prompt to bash.bashrc"
    else
        cat >> "$BASHRC" <<'BASHEOF'

# raspimidihub-rosetup: read-only filesystem helpers
ro_prompt() {
    if mount | grep -q 'on / .*\bro\b'; then
        echo "(ro)"
    else
        echo "(rw)"
    fi
}
alias rw='sudo mount -o remount,rw / && sudo mount -o remount,rw /boot/firmware && echo "Filesystem is now read-write"'
alias ro='sudo mount -o remount,ro /boot/firmware && sudo mount -o remount,ro / && echo "Filesystem is now read-only"'
export PS1='\$(ro_prompt) \u@\h:\w\$ '
BASHEOF
        log "  Added rw/ro aliases and prompt indicator"
    fi
    CHANGES_MADE=1
fi

# ============================================================
# FR-2.10: Auto-remount ro on logout
# ============================================================

log "Adding auto-remount on logout (FR-2.10)..."

BASH_LOGOUT="/etc/bash.bash_logout"
backup_file "$BASH_LOGOUT"

if file_contains "raspimidihub-rosetup" "$BASH_LOGOUT" 2>/dev/null; then
    log "  Logout remount already present, skipping"
else
    if $DRY_RUN; then
        log "  Would add auto-remount to bash_logout"
    else
        cat >> "$BASH_LOGOUT" <<'LOGOUTEOF'

# raspimidihub-rosetup: auto-remount read-only on logout
if mount | grep -q 'on / .*\brw\b'; then
    sudo mount -o remount,ro /boot/firmware 2>/dev/null
    sudo mount -o remount,ro / 2>/dev/null
fi
LOGOUTEOF
        log "  Added auto-remount on logout"
    fi
    CHANGES_MADE=1
fi

# ============================================================
# Done
# ============================================================

if $DRY_RUN; then
    log "Dry run complete. No changes were made."
else
    if [ $CHANGES_MADE -eq 1 ]; then
        log "Setup complete. Reboot to activate read-only filesystem."
        log "Use 'rw' to temporarily remount read-write for maintenance."
        log "Use 'ro' to remount read-only when done."
    else
        log "No changes needed — already configured."
    fi
fi

exit 0
