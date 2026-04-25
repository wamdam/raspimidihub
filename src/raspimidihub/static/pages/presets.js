/**
 * Presets page: save / load / overwrite / export / import / delete preset.
 */

import { useState, useEffect } from '../lib/hooks.module.js';
import { html, api } from '../ui/common.js';

export function PresetsPage({ refresh, showToast }) {
    const [presets, setPresets] = useState([]);
    const [newName, setNewName] = useState('');

    const loadPresets = async () => {
        const data = await api('/presets');
        setPresets(data);
    };
    useEffect(() => { loadPresets(); }, []);

    const save = async () => {
        if (!newName.trim()) return;
        await api('/presets', { method: 'POST', body: JSON.stringify({ name: newName.trim() }) });
        setNewName('');
        loadPresets();
        showToast('Preset saved');
    };
    const activate = async (name) => {
        await api(`/presets/${encodeURIComponent(name)}/activate`, { method: 'POST' });
        refresh();
        showToast(`Preset "${name}" activated`);
    };
    const overwrite = async (name) => {
        if (!confirm(`Overwrite preset "${name}" with current routing?`)) return;
        await api('/presets', { method: 'POST', body: JSON.stringify({ name }) });
        showToast(`Preset "${name}" updated`);
    };
    const del = async (name) => {
        if (!confirm(`Delete preset "${name}"?`)) return;
        await api(`/presets/${encodeURIComponent(name)}`, { method: 'DELETE' });
        loadPresets();
        showToast('Preset deleted');
    };
    const exportPreset = async (name) => {
        const data = await api(`/presets/${encodeURIComponent(name)}/export`);
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `${name}.json`;
        a.click();
    };
    const importPreset = () => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        input.onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const text = await file.text();
            const data = JSON.parse(text);
            await api('/presets/import', { method: 'POST', body: JSON.stringify(data) });
            loadPresets();
            showToast('Preset imported');
        };
        input.click();
    };

    return html`
        <div class="card">
            <h3>Save Current Routing and Instrument Settings</h3>
            <div style="display:flex;gap:8px">
                <input class="form-group" style="flex:1;margin:0;min-height:48px;padding:10px 12px;background:var(--bg);border:1px solid var(--surface2);border-radius:6px;color:var(--text);font-size:14px"
                    placeholder="Preset name" value=${newName} onInput=${e => setNewName(e.target.value)}
                    onKeyDown=${e => e.key === 'Enter' && save()} />
                <button class="btn btn-primary" onclick=${save}>Save</button>
            </div>
        </div>
        <div class="card">
            <h3>Presets</h3>
            ${presets.length === 0 && html`<p style="color:var(--text-dim)">No presets saved</p>`}
            ${presets.map(name => html`
                <div style="margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid var(--surface2)">
                    <div style="font-weight:500;margin-bottom:6px">${name}</div>
                    <div style="display:flex;gap:6px">
                        <button class="btn btn-success" onclick=${() => activate(name)}>Load</button>
                        <button class="btn btn-primary" onclick=${() => overwrite(name)}>Save</button>
                        <button class="btn btn-secondary" onclick=${() => exportPreset(name)}>Export</button>
                        <button class="btn btn-danger" onclick=${() => del(name)}>Del</button>
                    </div>
                </div>
            `)}
        </div>
        <button class="btn btn-secondary btn-block" onclick=${importPreset}>Import Preset</button>
    `;
}
