/**
 * Mapping form overlay + mappingDesc helper used by FilterPanel.
 */

import { useState, useEffect } from '../lib/hooks.module.js';
import { html, animateClose, useEscapeClose, useSwipeDismiss } from '../ui/common.js';
import { MAPPING_TYPES, noteName } from '../state/constants.js';
import { PluginRadio, PluginWheel, PluginNoteSelect, PluginButton } from '../plugin-controls.js';

export function mappingDesc(m) {
    const sch = m.src_channel != null ? `CH${m.src_channel + 1} ` : '';
    const dch = m.dst_channel != null ? `CH${m.dst_channel + 1} ` : sch;
    const pt = m.pass_through ? ' +thru' : '';
    if (m.type === 'note_to_cc') return `${sch}${noteName(m.src_note)} \u2192 ${dch}CC${m.dst_cc} (${m.cc_on_value}/${m.cc_off_value})${pt}`;
    if (m.type === 'note_to_cc_toggle') return `${sch}${noteName(m.src_note)} \u2192 ${dch}CC${m.dst_cc} toggle (${m.cc_on_value}/${m.cc_off_value})${pt}`;
    if (m.type === 'cc_to_cc') return `${sch}CC${m.src_cc} (${m.in_range_min}-${m.in_range_max}) \u2192 ${dch}CC${m.dst_cc_num} (${m.out_range_min}-${m.out_range_max})${pt}`;
    if (m.type === 'channel_map') return `${sch || 'CH* '}\u2192 CH${m.dst_channel + 1}`;
    return m.type;
}

export function MappingFormOverlay({ onSubmit, onClose, editing, srcClientId }) {
    const panelRef = { current: null };
    const close = () => animateClose(panelRef.current, onClose);
    const [type, setType] = useState(editing ? editing.type : 'note_to_cc');
    const [srcChannel, setSrcChannel] = useState(editing && editing.src_channel != null ? String(editing.src_channel) : '');
    const [srcNote, setSrcNote] = useState(editing ? (editing.src_note || 60) : 60);
    const [dstCc, setDstCc] = useState(editing ? (editing.dst_cc || 1) : 1);
    const [ccOnVal, setCcOnVal] = useState(editing ? (editing.cc_on_value != null ? editing.cc_on_value : 127) : 127);
    const [ccOffVal, setCcOffVal] = useState(editing ? (editing.cc_off_value != null ? editing.cc_off_value : 0) : 0);
    const [srcCc, setSrcCc] = useState(editing ? (editing.src_cc || 1) : 1);
    const [dstCcNum, setDstCcNum] = useState(editing ? (editing.dst_cc_num || 1) : 1);
    const [inMin, setInMin] = useState(editing ? (editing.in_range_min || 0) : 0);
    const [inMax, setInMax] = useState(editing ? (editing.in_range_max != null ? editing.in_range_max : 127) : 127);
    const [outMin, setOutMin] = useState(editing ? (editing.out_range_min || 0) : 0);
    const [outMax, setOutMax] = useState(editing ? (editing.out_range_max != null ? editing.out_range_max : 127) : 127);
    const [dstChannel, setDstChannel] = useState(editing ? (editing.dst_channel != null ? editing.dst_channel : 0) : 0);
    const [passThrough, setPassThrough] = useState(editing ? !!editing.pass_through : false);
    const [learning, setLearning] = useState(false);

    // MIDI Learn
    useEffect(() => {
        if (!learning) return;
        const es = new EventSource('/api/events');
        const handler = (e) => {
            try {
                const data = JSON.parse(e.data);
                if (data.src_client === srcClientId && (data.note != null || data.cc != null)) {
                    if (data.note != null) {
                        setType('note_to_cc'); setSrcNote(data.note);
                        if (data.channel != null) { setSrcChannel(String(data.channel - 1)); setDstChannel(data.channel - 1); }
                    } else if (data.cc != null) {
                        setType('cc_to_cc'); setSrcCc(data.cc);
                        if (data.channel != null) { setSrcChannel(String(data.channel - 1)); setDstChannel(data.channel - 1); }
                    }
                    setLearning(false);
                }
            } catch {}
        };
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
        if (type === 'note_to_cc' || type === 'note_to_cc_toggle') {
            m.src_note = +srcNote; m.dst_cc = +dstCc;
            m.cc_on_value = +ccOnVal; m.cc_off_value = +ccOffVal;
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
                <div style="display:flex;gap:12px;flex-wrap:wrap">
                    <${PluginWheel} name="srcCh" label="Src Ch" min=${0} max=${16}
                        value=${srcChannel === '' ? 0 : +srcChannel + 1}
                        tickLabel=${(v) => v === 0 ? 'Any' : v}
                        onChange=${(_, v) => { if (v === 0) setSrcChannel(''); else setSrcChannel(String(v - 1)); }} />
                    <${PluginWheel} name="dstCh" label="Dst Ch" min=${1} max=${16}
                        value=${dstChannel + 1} onChange=${(_, v) => setDstChannel(v - 1)} />
                </div>
                ${(type === 'note_to_cc' || type === 'note_to_cc_toggle') && html`
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        <${PluginNoteSelect} name="srcNote" label="Src Note"
                            value=${srcNote} onChange=${w(setSrcNote)} />
                        <${PluginWheel} name="dstCc" label="Dst CC" min=${0} max=${127}
                            value=${dstCc} onChange=${w(setDstCc)} />
                    </div>
                    <div style="display:flex;gap:12px;flex-wrap:wrap">
                        <${PluginWheel} name="onVal" label="On Val" min=${0} max=${127}
                            value=${ccOnVal} onChange=${w(setCcOnVal)} />
                        <${PluginWheel} name="offVal" label="Off Val" min=${0} max=${127}
                            value=${ccOffVal} onChange=${w(setCcOffVal)} />
                    </div>
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
                    ${!editing && html`<button class="btn btn-secondary ${learning ? 'btn-held' : ''}" onclick=${() => setLearning(true)}>
                        ${learning ? 'Listening...' : 'MIDI Learn'}
                    </button>`}
                </div>
            </div>
        </div>
    `;
}
