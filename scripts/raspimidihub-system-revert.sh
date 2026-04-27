#!/bin/bash
# raspimidihub-system-revert: undo what raspimidihub-system-prepare did.
#
# Re-enables the disabled services, removes the kernel cmdline iso
# params, removes the systemd drop-in. Idempotent.
#
# Usage:
#   raspimidihub-system-revert [--dry-run]

set -euo pipefail

BACKUP_DIR="/var/lib/raspimidihub-prepare/backup"
DROPIN_DIR="/etc/systemd/system/raspimidihub.service.d"
DROPIN_FILE="$DROPIN_DIR/cpu-affinity.conf"
CMDLINE="/boot/firmware/cmdline.txt"
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

log() { echo "[revert] $*"; }

if [ "$EUID" -ne 0 ]; then
    echo "Must be run as root" >&2
    exit 1
fi

# Mirror of the disable list in -prepare. Keep in sync.
SERVICES_TO_REENABLE=(
    bluealsa-aplay.service bluealsa.service bluetooth.service
    ModemManager.service
    cloud-init.service cloud-config.service cloud-final.service
    cloud-init-local.service cloud-init-network.service
    udisks2.service cron.service sshswitch.service
    e2scrub_reap.service e2scrub_all.timer
    fstrim.timer dpkg-db-backup.timer logrotate.timer rpi-zram-writeback.timer
)

reenable_services() {
    log "Pass 1/2: re-enabling system services + timers"
    for unit in "${SERVICES_TO_REENABLE[@]}"; do
        if systemctl list-unit-files "$unit" 2>/dev/null | grep -q "$unit"; then
            if $DRY_RUN; then
                log "Would enable + start $unit"
            else
                systemctl enable --now "$unit" >/dev/null 2>&1 || true
                log "enabled $unit"
            fi
        fi
    done
}

revert_cmdline() {
    log "Pass 2a/2: removing isolcpus / nohz_full / rcu_nocbs from $CMDLINE"
    if [ ! -f "$CMDLINE" ]; then
        return 0
    fi
    local current
    current="$(tr -d '\n' < "$CMDLINE")"
    local stripped
    stripped="$(echo "$current" | sed -E \
        -e 's/[[:space:]]*isolcpus=[^[:space:]]*//g' \
        -e 's/[[:space:]]*nohz_full=[^[:space:]]*//g' \
        -e 's/[[:space:]]*rcu_nocbs=[^[:space:]]*//g' \
        -e 's/[[:space:]]+/ /g' \
        -e 's/^[[:space:]]+//' -e 's/[[:space:]]+$//')"
    if [ "$current" = "$stripped" ]; then
        log "no iso params found in cmdline — leaving alone"
        return 0
    fi
    if $DRY_RUN; then
        log "Would rewrite cmdline (-iso params)"
        return 0
    fi
    local mountpoint="/boot/firmware"
    local was_ro=false
    if findmnt -n -o OPTIONS "$mountpoint" 2>/dev/null | grep -qw ro; then
        was_ro=true
        mount -o remount,rw "$mountpoint" || {
            log "could not remount $mountpoint rw — skipping cmdline revert"
            return 0
        }
    fi
    printf '%s\n' "$stripped" > "$CMDLINE" || true
    if $was_ro; then
        sync
        mount -o remount,ro "$mountpoint" || true
    fi
    log "removed iso params — reboot required to take effect"
}

revert_dropin() {
    log "Pass 2b/2: removing systemd drop-in"
    if [ -f "$DROPIN_FILE" ]; then
        if $DRY_RUN; then
            log "Would remove $DROPIN_FILE"
        else
            rm -f "$DROPIN_FILE"
            rmdir "$DROPIN_DIR" 2>/dev/null || true
            systemctl daemon-reload
            log "removed $DROPIN_FILE"
        fi
    fi
}

reenable_services
revert_cmdline
revert_dropin

log ""
log "Done. CPU pin lifted on next service restart; kernel iso lifted on next REBOOT."
