/**
 * Shared constants and tiny pure helpers used across the app.
 */

export const MSG_TYPES = ['note', 'cc', 'pc', 'pitchbend', 'aftertouch', 'sysex', 'clock'];
export const MSG_LABELS = { note: 'Notes', cc: 'CC', pc: 'Program', pitchbend: 'Pitch Bend', aftertouch: 'Aftertouch', sysex: 'SysEx', clock: 'Clock/RT' };

export const MAPPING_TYPES = [
    { value: 'note_to_cc', label: 'Note \u2192 CC' },
    { value: 'note_to_cc_toggle', label: 'Note \u2192 CC (toggle)' },
    { value: 'cc_to_cc', label: 'CC \u2192 CC' },
    { value: 'channel_map', label: 'Channel Remap' },
];

export const NOTE_NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
export const noteName = (n) => NOTE_NAMES[n % 12] + (Math.floor(n / 12) - 2);

export const UPDATE_LABELS = { downloading: 'Downloading...', installing: 'Installing...', done: 'Updated! Restarting...' };
