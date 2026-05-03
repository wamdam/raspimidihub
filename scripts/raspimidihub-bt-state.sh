#!/bin/sh
# Restore / snapshot BlueZ state under read-only root.
#
# Usage:
#   raspimidihub-bt-state restore   - mount tmpfs + extract last snapshot
#   raspimidihub-bt-state snapshot  - tar tmpfs contents back to /boot/firmware
#   raspimidihub-bt-state watch     - long-running inotify watcher; calls
#                                     snapshot whenever tmpfs contents settle
#                                     (debounced 2s). The appliance gets
#                                     yanked from power without a shutdown,
#                                     so ExecStop=snapshot isn't enough —
#                                     bonds must hit /boot/firmware as soon
#                                     as bluetoothd writes them.
#
# Snapshot location is on /boot/firmware (the only non-volatile area
# accessible to userspace on this image). /boot/firmware is normally
# RO, so we bracket the snapshot write with a remount-rw / remount-ro
# pair. The tarball is `state.tar` (uncompressed: a handful of files,
# total ≪ 64 KB; gzip overhead would dwarf the savings).

set -eu

TARGET="/var/lib/bluetooth"
SNAP_DIR="/boot/firmware/raspimidihub"
SNAP_FILE="$SNAP_DIR/bluetooth-state.tar"
BOOT_MNT="/boot/firmware"

log() { echo "[bt-state] $*"; }

remount_boot_rw() {
    if findmnt -n -o OPTIONS "$BOOT_MNT" 2>/dev/null | grep -qw ro; then
        mount -o remount,rw "$BOOT_MNT" && BOOT_RW_BY_US=1
    fi
}

remount_boot_ro() {
    if [ -n "${BOOT_RW_BY_US-}" ]; then
        sync
        mount -o remount,ro "$BOOT_MNT" 2>/dev/null || true
    fi
}

do_snapshot() {
    if ! findmnt -n -o FSTYPE "$TARGET" 2>/dev/null | grep -qw tmpfs; then
        log "$TARGET is not a tmpfs — refusing to snapshot"
        return 0
    fi
    # Hard guard: NEVER write a snapshot to disk unless /boot/firmware
    # is mounted. If something goes wrong with the mount and we'd
    # otherwise blindly create a file under what's actually the root
    # FS's `/boot/firmware` directory, AND clobber a good snapshot if
    # that path is later remounted, we'd lose bonds. Skipping when
    # unmounted is always safe — the next change will trigger another
    # snapshot once the mount is back.
    if ! findmnt -n "$BOOT_MNT" >/dev/null 2>&1; then
        log "$BOOT_MNT not mounted — skipping snapshot"
        return 0
    fi
    mkdir -p "$SNAP_DIR" 2>/dev/null || true
    local tmpfile="$SNAP_DIR/.bluetooth-state.tar.tmp"
    BOOT_RW_BY_US=
    remount_boot_rw
    if (cd "$TARGET" && tar -cf "$tmpfile" .) 2>/dev/null; then
        mv -f "$tmpfile" "$SNAP_FILE"
        sync
        log "snapshot saved to $SNAP_FILE"
    else
        log "snapshot tar failed"
        rm -f "$tmpfile" 2>/dev/null
    fi
    remount_boot_ro
}

case "${1-}" in
    restore)
        # Idempotent: only mount if not already a tmpfs
        if ! findmnt -n -o FSTYPE "$TARGET" 2>/dev/null | grep -qw tmpfs; then
            mkdir -p "$TARGET"
            mount -t tmpfs -o size=8m,mode=0700 tmpfs "$TARGET"
            log "tmpfs mounted on $TARGET"
        fi
        # Refuse to restore if /boot/firmware isn't mounted yet —
        # otherwise we'd start with empty state and the watcher would
        # later snapshot that empty state on top of a still-good
        # tarball. Failing here causes the unit to retry once the
        # mount lands (Requires=boot-firmware.mount).
        if ! findmnt -n "$BOOT_MNT" >/dev/null 2>&1; then
            log "$BOOT_MNT not mounted — aborting restore"
            exit 1
        fi
        if [ -f "$SNAP_FILE" ]; then
            tar -xf "$SNAP_FILE" -C "$TARGET" 2>/dev/null \
                && log "restored from $SNAP_FILE" \
                || log "failed to restore (corrupt snapshot?) — starting fresh"
        else
            log "no snapshot at $SNAP_FILE — starting fresh"
        fi
        ;;
    snapshot)
        do_snapshot
        ;;
    watch)
        if ! command -v inotifywait >/dev/null 2>&1; then
            log "inotifywait missing — cannot watch (install inotify-tools)"
            exit 1
        fi
        if ! findmnt -n -o FSTYPE "$TARGET" 2>/dev/null | grep -qw tmpfs; then
            log "watch: $TARGET is not a tmpfs — aborting"
            exit 1
        fi
        log "watching $TARGET for BlueZ writes"
        # Loop: block on first event, then drain trailing events for 2s
        # of quiet (BlueZ tends to write info + cache + attributes in a
        # quick burst when bonding). Snapshot once per quiet period.
        EVENTS="modify,create,delete,move,attrib"
        while true; do
            if ! inotifywait -r -e "$EVENTS" --quiet "$TARGET" >/dev/null 2>&1; then
                log "inotifywait exited; bailing"
                exit 1
            fi
            # Drain follow-ups; exits 1 on 2s timeout (no events).
            while inotifywait -r -t 2 -e "$EVENTS" --quiet "$TARGET" \
                    >/dev/null 2>&1; do
                :
            done
            do_snapshot
        done
        ;;
    *)
        echo "Usage: $0 {restore|snapshot|watch}" >&2
        exit 2
        ;;
esac
