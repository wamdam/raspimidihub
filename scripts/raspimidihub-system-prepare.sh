#!/bin/bash
# raspimidihub-system-prepare: trim the Pi for single-purpose MIDI duty.
#
# Two passes:
#   1) Disable services + timers that contribute nothing to MIDI but
#      compete for CPU (Bluetooth audio, ModemManager, cloud-init,
#      udisks2, periodic-disk-IO timers, etc.).
#   2) Reserve a CPU core for the asyncio loop:
#      - Kernel cmdline: isolcpus=3 nohz_full=3 rcu_nocbs=3 (one-time;
#        requires a reboot to take effect).
#      - systemd drop-in: AllowedCPUs=3 on raspimidihub.service so the
#        Python process exclusively occupies the isolated core.
#
# Idempotent — safe to run multiple times. Originals of any edited
# system file are backed up to /var/lib/raspimidihub-prepare/backup/.
#
# Usage:
#   raspimidihub-system-prepare [--dry-run]
#
# Reverse with raspimidihub-system-revert.

set -euo pipefail

BACKUP_DIR="/var/lib/raspimidihub-prepare/backup"
DROPIN_DIR="/etc/systemd/system/raspimidihub.service.d"
DROPIN_FILE="$DROPIN_DIR/cpu-affinity.conf"
CMDLINE="/boot/firmware/cmdline.txt"
ISOL_PARAMS="isolcpus=3 nohz_full=3 rcu_nocbs=3"
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

log() { echo "[prepare] $*"; }
warn() { echo "[prepare] WARNING: $*" >&2; }

if [ "$EUID" -ne 0 ]; then
    echo "Must be run as root" >&2
    exit 1
fi

backup_once() {
    local file="$1"
    [ -f "$file" ] || return
    local rel="${file#/}"
    local dest="$BACKUP_DIR/$rel"
    [ -f "$dest" ] && return  # already backed up
    if $DRY_RUN; then
        log "Would back up $file"
        return
    fi
    mkdir -p "$(dirname "$dest")"
    cp -a "$file" "$dest"
}

# Services + timers that provide zero MIDI value. Each entry is
# disable + stop; missing units (different Pi OS variants) are
# silently skipped.
SERVICES_TO_DISABLE=(
    # Bluetooth audio playback — never used on a MIDI hub. The
    # `bluetooth.service` (BlueZ daemon) and `bluealsa.service`
    # itself stay ENABLED — both are required for BLE-MIDI.
    bluealsa-aplay.service
    # Cellular modems
    ModemManager.service
    # First-boot cloud-init — useless after the appliance is configured
    cloud-init.service
    cloud-config.service
    cloud-final.service
    cloud-init-local.service
    cloud-init-network.service
    # Auto-mount removable media — ALSA seq doesn't touch block devices
    udisks2.service
    # Periodic cron jobs — none scheduled in our image
    cron.service
    # Pi-specific SSH-on-blink toggle
    sshswitch.service
    # Filesystem scrub on what is normally a read-only root
    e2scrub_reap.service
    e2scrub_all.timer
    # SSD trim (irrelevant on read-only SD card)
    fstrim.timer
    # Daily dpkg snapshot (read-only root rarely changes)
    dpkg-db-backup.timer
    # journald already rotates its own logs
    logrotate.timer
    # zram swap writeback — small Pi, swap rarely meaningful
    rpi-zram-writeback.timer
    # NTP — the Pi is offline by default (AP mode, no upstream DNS) so
    # ntpsec spins on dns_probe → "Temporary failure in name resolution"
    # every few seconds, polluting the journal. Time-of-day accuracy is
    # not relevant for MIDI routing; if the user really needs wall clock
    # alignment they can re-enable ntpsec / systemd-timesyncd manually.
    ntpsec.service
    ntpsec-rotate-stats.timer
    ntpsec-systemd-netif.path
    systemd-timesyncd.service
)

disable_services() {
    log "Pass 1/2: disabling services + timers that don't contribute to MIDI"
    local disabled=0 skipped=0
    # `--no-reload` per disable + a single trailing daemon-reload
    # below cuts dpkg-install noise dramatically: each plain
    # `disable --now` would fire the SysV compat shim and print a
    # "Synchronizing state of <unit>.service ..." block, so disabling
    # 10 services produced 10 such blocks during install. With
    # --no-reload we batch the symlink updates and reload once.
    local need_reload=false
    for unit in "${SERVICES_TO_DISABLE[@]}"; do
        # `systemctl is-enabled` returns 0 only when the unit is
        # actually enabled; missing units exit non-zero. We skip
        # silently in that case.
        local was_active=false
        if systemctl is-active --quiet "$unit" 2>/dev/null; then
            was_active=true
        fi
        if systemctl is-enabled --quiet "$unit" 2>/dev/null || $was_active; then
            if $DRY_RUN; then
                log "Would disable + stop $unit"
            else
                systemctl --no-reload disable "$unit" >/dev/null 2>&1 || true
                if $was_active; then
                    systemctl stop "$unit" >/dev/null 2>&1 || true
                fi
                need_reload=true
                log "disabled $unit"
            fi
            disabled=$((disabled + 1))
        else
            skipped=$((skipped + 1))
        fi
    done
    if $need_reload && ! $DRY_RUN; then
        systemctl daemon-reload
    fi
    log "$disabled disabled, $skipped already inactive / not installed"
}

# --- Kernel cmdline: isolate core 3 ------------------------------------
# isolcpus=3        remove from general scheduler
# nohz_full=3       suppress periodic timer interrupt on this core
# rcu_nocbs=3       offload RCU callbacks to a non-isolated core
ensure_cmdline() {
    log "Pass 2a/2: reserving CPU 3 via kernel cmdline ($CMDLINE)"
    if [ ! -f "$CMDLINE" ]; then
        warn "$CMDLINE not found — skipping kernel cmdline edit. Manual setup required."
        return 0
    fi
    local current
    current="$(cat "$CMDLINE")"
    local need_isol=false need_nohz=false need_rcu=false
    grep -q 'isolcpus=' <<<"$current" || need_isol=true
    grep -q 'nohz_full=' <<<"$current" || need_nohz=true
    grep -q 'rcu_nocbs=' <<<"$current" || need_rcu=true
    if ! $need_isol && ! $need_nohz && ! $need_rcu; then
        log "kernel cmdline already isolates a core — leaving alone"
        return 0
    fi
    local additions=""
    $need_isol && additions="$additions isolcpus=3"
    $need_nohz && additions="$additions nohz_full=3"
    $need_rcu && additions="$additions rcu_nocbs=3"
    if $DRY_RUN; then
        log "Would append:$additions to $CMDLINE"
        return 0
    fi
    backup_once "$CMDLINE"
    # /boot/firmware is its own vfat partition, often mounted read-only
    # by the rosetup appliance setup. Attempt the write directly; if it
    # fails with EROFS, remount /boot/firmware rw, retry, remount back.
    local mountpoint="/boot/firmware"
    local was_ro=false
    if findmnt -n -o OPTIONS "$mountpoint" 2>/dev/null | grep -qw ro; then
        was_ro=true
        log "remounting $mountpoint rw for cmdline edit"
        mount -o remount,rw "$mountpoint" || {
            warn "failed to remount $mountpoint rw — skipping kernel cmdline edit"
            warn "  apply manually: append$additions to /boot/firmware/cmdline.txt"
            return 0
        }
    fi
    # cmdline.txt MUST be one line — multi-line breaks the bootloader.
    if ! printf '%s%s\n' "$(tr -d '\n' < "$CMDLINE")" "$additions" > "$CMDLINE"; then
        warn "failed to write $CMDLINE"
        $was_ro && mount -o remount,ro "$mountpoint" || true
        return 0
    fi
    if $was_ro; then
        sync
        mount -o remount,ro "$mountpoint" || warn "could not restore $mountpoint to ro"
    fi
    log "appended$additions — reboot required to take effect"
}

ensure_dropin() {
    log "Pass 2b/2: pinning raspimidihub.service to CPU 3 via systemd drop-in"
    if $DRY_RUN; then
        log "Would write $DROPIN_FILE"
        return
    fi
    mkdir -p "$DROPIN_DIR"
    cat > "$DROPIN_FILE" <<'EOF'
# Auto-generated by raspimidihub-system-prepare. Do not edit by hand —
# rerun the prepare script (or its --revert sibling) instead.
[Service]
# Slight nice bump — the asyncio loop is the most latency-sensitive
# thing on the Pi.
Nice=-5
# Allow all 4 CPUs (including the kernel-isolated core 3). With
# isolcpus=3 in the kernel cmdline, system.slice defaults to
# AllowedCPUs=0-2 — services inherit that and CAN'T pin themselves
# to CPU 3 even with sched_setaffinity. Setting 0-3 here re-grants
# access. Python then pins itself to {3} in __main__.pin_to_isolated_cpu;
# subprocesses (hostapd / dnsmasq) inherit {3} from the parent but
# wifi.py wraps their spawns in `taskset -c 0-2` so they end up on
# the non-isolated cores. The asyncio loop has CPU 3 to itself and
# WiFi daemons stay on cores with normal timer ticks.
AllowedCPUs=0-3
EOF
    systemctl daemon-reload
    log "wrote $DROPIN_FILE; raspimidihub.service will pick up on next start"
}

# disable_services and ensure_dropin both write under /etc — once
# rosetup has marked / read-only, those writes fail silently (the
# `|| true` swallows EROFS). Remount rw for the duration of those
# two passes, then restore ro. ensure_cmdline handles its own
# /boot/firmware remount, no wrap needed.
ROOT_WAS_RO=false
if findmnt -n -o OPTIONS / 2>/dev/null | grep -qw ro; then
    ROOT_WAS_RO=true
    log "remounting / rw for service-disable + drop-in writes"
    if ! mount -o remount,rw /; then
        warn "failed to remount / rw — service disables and drop-in may not stick"
        ROOT_WAS_RO=false
    fi
fi

disable_services
ensure_cmdline
ensure_dropin

if $ROOT_WAS_RO; then
    sync
    mount -o remount,ro / || warn "could not restore / to ro"
fi

log ""
log "Done."
log "  - Service / timer trim is live immediately."
log "  - CPU pin (AllowedCPUs=3) takes effect on next service restart."
log "  - Kernel core isolation (isolcpus=3) takes effect on next REBOOT."
log ""
log "To restart the service: systemctl restart raspimidihub.service"
log "To reboot:              sudo reboot"
log "To revert everything:   raspimidihub-system-revert"
