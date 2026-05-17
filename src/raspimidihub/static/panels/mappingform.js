/**
 * Mapping form overlay + mappingDesc helper used by FilterPanel.
 */

import { useState, useEffect } from '../lib/hooks.module.js';
import { html, animateClose, useEscapeClose, useSwipeDismiss } from '../ui/common.js';
import { MAPPING_TYPES, noteName } from '../state/constants.js';
import { PluginRadio, PluginWheel, PluginNoteSelect, PluginButton } from '../plugin-controls.js';

// "Any" when src_note is null/undefined (wildcard); the literal note name
// otherwise. Kept here rather than in noteName itself because most callers
// (drop buttons, tracker, plugin params) want a missing note to read as
// blank or "Off", not "Any".
const srcNoteLabel = (n) => (n == null ? 'Any' : noteName(n));

export function mappingDesc(m) {
    const sch = m.src_channel != null ? `CH${m.src_channel + 1} ` : '';
    const dch = m.dst_channel != null ? `CH${m.dst_channel + 1} ` : sch;
    const pt = m.pass_through ? ' +thru' : '';
    if (m.type === 'note_to_cc') {
        const vals = m.cc_value_source === 'velocity'
            ? `vel/${m.cc_off_value}`
            : `${m.cc_on_value}/${m.cc_off_value}`;
        return `${sch}${srcNoteLabel(m.src_note)} \u2192 ${dch}CC${m.dst_cc} (${vals})${pt}`;
    }
    if (m.type === 'note_to_cc_toggle') return `${sch}${srcNoteLabel(m.src_note)} \u2192 ${dch}CC${m.dst_cc} toggle (${m.cc_on_value}/${m.cc_off_value})${pt}`;
    if (m.type === 'note_to_note') return `${sch}${srcNoteLabel(m.src_note)} \u2192 ${dch}${noteName(m.dst_note)}${pt}`;
    if (m.type === 'cc_to_cc') return `${sch}CC${m.src_cc} (${m.in_range_min}-${m.in_range_max}) \u2192 ${dch}CC${m.dst_cc_num} (${m.out_range_min}-${m.out_range_max})${pt}`;
    if (m.type === 'channel_map') return `${sch || 'CH* '}\u2192 CH${m.dst_channel + 1}`;
    return m.type;
}

export function MappingFormOverlay({ onSubmit, onClose, editing, srcClientId }) {
    const panelRef = { current: null };
    const close = () => animateClose(panelRef.current, onClose);
    const [type, setType] = useState(editing ? editing.type : 'note_to_cc');
    const [srcChannel, setSrcChannel] = useState(editing && editing.src_channel != null ? String(editing.src_channel) : '');
    // src_note wheel uses -1 as the "Any" tick (mirrors the drop-button
    // "Off" convention). Persisted as null on the wire.
    const [srcNote, setSrcNote] = useState(editing
        ? (editing.src_note != null ? editing.src_note : -1)
        : 60);
    const [dstNote, setDstNote] = useState(editing ? (editing.dst_note != null ? editing.dst_note : 60) : 60);
    const [dstCc, setDstCc] = useState(editing ? (editing.dst_cc || 1) : 1);
    const [ccOnVal, setCcOnVal] = useState(editing ? (editing.cc_on_value != null ? editing.cc_on_value : 127) : 127);
    const [ccOffVal, setCcOffVal] = useState(editing ? (editing.cc_off_value != null ? editing.cc_off_value : 0) : 0);
    const [ccValueSource, setCcValueSource] = useState(editing && editing.cc_value_source === 'velocity' ? 'velocity' : 'fixed');
    const [srcCc, setSrcCc] = useState(editing ? (editing.src_cc || 1) : 1);
    const [dstCcNum, setDstCcNum] = useState(editing ? (editing.dst_cc_num || 1) : 1);
    const [inMin, setInMin] = useState(editing ? (editing.in_range_min || 0) : 0);
    const [inMax, setInMax] = useState(editing ? (editing.in_range_max != null ? editing.in_range_max : 127) : 127);
    const [outMin, setOutMin] = useState(editing ? (editing.out_range_min || 0) : 0);
    const [outMax, setOutMax] = useState(editing ? (editing.out_range_max != null ? editing.out_range_max : 127) : 127);
    const [dstChannel, setDstChannel] = useState(editing ? (editing.dst_channel != null ? editing.dst_channel : 0) : 0);
    const [passThrough, setPassThrough] = useState(editing ? !!editing.pass_through : false);
    const [learning, setLearning] = useState(false);

    // MIDI Learn — open a fresh SSE, then explicitly subscribe to
    // midi-activity once the connection event lands. The per-view
    // SSE subscription model means an unsubscribed EventSource never
    // delivers midi-activity events; without the subscribe POST
    // below, "Listening…" sits there forever and the field never
    // captures anything (regressed when per-view subscriptions were
    // introduced; the same fix is in components/noteselect.js).
    useEffect(() => {
        if (!learning) return;
        const es = new EventSource('/api/events');
        const onConn = (e) => {
            try {
                const connId = JSON.parse(e.data).conn_id;
                fetch('/api/sse/subscribe', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        conn_id: connId,
                        events: ['midi-activity'],
                        instances: [],
                    }),
                }).catch(() => {});
            } catch {}
        };
        const handler = (e) => {
            try {
                const data = JSON.parse(e.data);
                if (data.src_client === srcClientId && (data.note != null || data.cc != null)) {
                    if (data.note != null) {
                        // Stay on a note-source type if the user already picked one;
                        // otherwise default to note_to_cc.
                        if (type !== 'note_to_cc' && type !== 'note_to_cc_toggle' && type !== 'note_to_note') {
                            setType('note_to_cc');
                        }
                        setSrcNote(data.note);
                        if (data.channel != null) { setSrcChannel(String(data.channel - 1)); setDstChannel(data.channel - 1); }
                    } else if (data.cc != null) {
                        if (type !== 'cc_to_cc') setType('cc_to_cc');
                        setSrcCc(data.cc);
                        if (data.channel != null) { setSrcChannel(String(data.channel - 1)); setDstChannel(data.channel - 1); }
                    }
                    setLearning(false);
                }
            } catch {}
        };
        es.addEventListener('connection', onConn);
        es.addEventListener('midi-activity', handler);
        const timeout = setTimeout(() => setLearning(false), 10000);
        return () => { es.close(); clearTimeout(timeout); };
    }, [learning]);

    useEscapeClose(close);
    const swipe = useSwipeDismiss(close, panelRef);

    const onSrcChannelChange = (val) => {
        setSrcChannel(val);
        if (val !== '') setDstChannel(+val);
    };

    const submit = () => {
        const m = { type, dst_channel: +dstChannel, pass_through: passThrough };
        if (srcChannel !== '') m.src_channel = +srcChannel;
        // -1 on the wheel means "Any" — persist as null on the wire so
        // the dispatcher treats the rule as a wildcard.
        const srcNoteOnWire = +srcNote === -1 ? null : +srcNote;
        if (type === 'note_to_cc' || type === 'note_to_cc_toggle') {
            m.src_note = srcNoteOnWire; m.dst_cc = +dstCc;
            m.cc_on_value = +ccOnVal; m.cc_off_value = +ccOffVal;
            if (type === 'note_to_cc' && ccValueSource === 'velocity') {
                m.cc_value_source = 'velocity';
            }
        } else if (type === 'note_to_note') {
            m.src_note = srcNoteOnWire; m.dst_note = +dstNote;
        } else if (type === 'cc_to_cc') {
            m.src_cc = +srcCc; m.dst_cc_num = +dstCcNum;
            m.in_range_min = +inMin; m.in_range_max = +inMax;
            m.out_range_min = +outMin; m.out_range_max = +outMax;
        }
        onSubmit(m);
    };

    const w = (setter) => (_, v) => setter(v);

    return html`
        <div class="mapping-overlay" onclick=${(e) => e.target.className === 'mapping-overlay' && close()}>
            <div class="mapping-panel" ref=${el => panelRef.current = el} ...${swipe}>
                <div class="panel-header">
                    <div class="panel-handle"></div>
                </div>
                <div class="panel-header">
                    <h3>${editing ? 'Edit Mapping' : 'Add Mapping'}</h3>
                    <button class="panel-close" onclick=${close}>\u2715</button>
                </div>
                <${PluginRadio} name="type" label="Type"
                    options=${MAPPING_TYPES.map(t => t.label)}
                    value=${MAPPING_TYPES.find(t => t.value === type)?.label || type}
                    onChange=${(_, label) => { const t = MAPPING_TYPES.find(m => m.label === label); if (t) setType(t.value); }} />
                ${type !== 'note_to_note' && html`
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        <${PluginWheel} name="srcCh" label="Src Ch" min=${0} max=${16}
                            value=${srcChannel === '' ? 0 : +srcChannel + 1}
                            tickLabel=${(v) => v === 0 ? 'Any' : v}
                            onChange=${(_, v) => { if (v === 0) setSrcChannel(''); else setSrcChannel(String(v - 1)); }} />
                        <${PluginWheel} name="dstCh" label="Dst Ch" min=${1} max=${16}
                            value=${dstChannel + 1} onChange=${(_, v) => setDstChannel(v - 1)} />
                    </div>
                `}
                ${(type === 'note_to_cc' || type === 'note_to_cc_toggle') && html`
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        <${PluginNoteSelect} name="srcNote" label="Src Note" min=${-1}
                            formatValue=${(v) => v === -1 ? 'Any' : noteName(v)}
                            value=${srcNote} onChange=${w(setSrcNote)} />
                        <${PluginWheel} name="dstCc" label="Dst CC" min=${0} max=${127}
                            value=${dstCc} onChange=${w(setDstCc)} />
                    </div>
                    ${type === 'note_to_cc' && html`
                        <${PluginRadio} name="ccValueSource" label="Value Source"
                            options=${['Fixed', 'Velocity']}
                            value=${ccValueSource === 'velocity' ? 'Velocity' : 'Fixed'}
                            onChange=${(_, v) => setCcValueSource(v === 'Velocity' ? 'velocity' : 'fixed')} />
                    `}
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        ${!(type === 'note_to_cc' && ccValueSource === 'velocity') && html`
                            <${PluginWheel} name="onVal" label="On Val" min=${0} max=${127}
                                value=${ccOnVal} onChange=${w(setCcOnVal)} />
                        `}
                        <${PluginWheel} name="offVal"
                            label=${type === 'note_to_cc' && ccValueSource === 'velocity' ? 'Release Val' : 'Off Val'}
                            min=${0} max=${127}
                            value=${ccOffVal} onChange=${w(setCcOffVal)} />
                    </div>
                `}
                ${type === 'note_to_note' && html`
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        <${PluginWheel} name="srcCh" label="Src Ch" min=${0} max=${16}
                            value=${srcChannel === '' ? 0 : +srcChannel + 1}
                            tickLabel=${(v) => v === 0 ? 'Any' : v}
                            onChange=${(_, v) => { if (v === 0) setSrcChannel(''); else setSrcChannel(String(v - 1)); }} />
                        <${PluginNoteSelect} name="srcNote" label="Src Note" min=${-1}
                            formatValue=${(v) => v === -1 ? 'Any' : noteName(v)}
                            value=${srcNote} onChange=${w(setSrcNote)} />
                    </div>
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        <${PluginWheel} name="dstCh" label="Dst Ch" min=${1} max=${16}
                            value=${dstChannel + 1} onChange=${(_, v) => setDstChannel(v - 1)} />
                        <${PluginNoteSelect} name="dstNote" label="Dst Note"
                            value=${dstNote} onChange=${w(setDstNote)} />
                    </div>
                    ${srcNote === -1 && html`
                        <div style="font-size:12px;color:var(--text-dim);margin-top:-6px">
                            Every incoming note will be remapped to ${noteName(dstNote)}.
                        </div>
                    `}
                `}
                ${type === 'cc_to_cc' && html`
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        <${PluginWheel} name="srcCc" label="Src CC" min=${0} max=${127}
                            value=${srcCc} onChange=${w(setSrcCc)} />
                        <${PluginWheel} name="dstCcNum" label="Dst CC" min=${0} max=${127}
                            value=${dstCcNum} onChange=${w(setDstCcNum)} />
                    </div>
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        <${PluginWheel} name="inMin" label="In Min" min=${0} max=${127}
                            value=${inMin} onChange=${w(setInMin)} />
                        <${PluginWheel} name="inMax" label="In Max" min=${0} max=${127}
                            value=${inMax} onChange=${w(setInMax)} />
                    </div>
                    <div style="display:flex;gap:12px">
                        <${PluginWheel} name="outMin" label="Out Min" min=${0} max=${127}
                            value=${outMin} onChange=${w(setOutMin)} />
                        <${PluginWheel} name="outMax" label="Out Max" min=${0} max=${127}
                            value=${outMax} onChange=${w(setOutMax)} />
                    </div>
                `}
                ${type !== 'channel_map' && html`
                    <${PluginButton} name="passThrough" label="Pass through" color="green"
                        value=${passThrough} onChange=${(_, v) => setPassThrough(v)} />
                `}
                <div class="btn-group">
                    <button class="btn btn-primary" onclick=${submit}>${editing ? 'Save' : 'Add'}</button>
                    <button class="btn btn-secondary ${learning ? 'btn-held' : ''}" onclick=${() => setLearning(true)}>
                        ${learning ? 'Listening...' : 'MIDI Learn'}
                    </button>
                </div>
            </div>
        </div>
    `;
}
