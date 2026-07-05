/**
 * Shared constants and tiny pure helpers used across the app.
 */

export const MSG_TYPES = ['note', 'cc', 'pc', 'pitchbend', 'aftertouch', 'sysex', 'clock', 'midi2'];
export const MSG_LABELS = { note: 'Notes', cc: 'CC', pc: 'Program', pitchbend: 'Pitch Bend', aftertouch: 'Aftertouch', sysex: 'SysEx', clock: 'Clock/RT', midi2: 'MIDI 2.0' };

export const MAPPING_TYPES = [
    { value: 'note_to_cc', label: 'Note \u2192 CC' },
    { value: 'note_to_cc_toggle', label: 'Note \u2192 CC (toggle)' },
    { value: 'note_to_note', label: 'Note \u2192 Note' },
    { value: 'cc_to_cc', label: 'CC \u2192 CC' },
    { value: 'channel_map', label: 'Channel Remap' },
];

export const NOTE_NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
export const noteName = (n) => NOTE_NAMES[n % 12] + (Math.floor(n / 12) - 2);

// Phase 5.5 update flow steps (written by update_flow.py + the
// install / watchdog scripts). Anything missing falls through to the
// raw step name in the UI, which is fine for unfamiliar errors but
// noisy for normal-path states — so these cover every step the
// orchestrator emits.
export const UPDATE_LABELS = {
    'idle': '',
    'probing': 'Checking internet...',
    'switching-to-client': 'Joining WiFi...',
    'verifying-internet': 'Verifying internet...',
    'fetching-release-list': 'Fetching release list...',
    'downloading': 'Downloading...',
    'switching-to-ap': 'Returning to AP...',
    'installing': 'Installing...',
    'done': 'Done.',
};
