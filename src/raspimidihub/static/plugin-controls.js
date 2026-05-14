/**
 * Public entry point for plugin UI components.
 *
 * Each component lives under ./components/ in its own file. This shim
 * preserves the historical import path (`./plugin-controls.js`) so
 * existing imports keep working unchanged.
 */

export { tickFeedback, thudFeedback, noteName } from './components/common.js';
export { PluginWheel } from './components/wheel.js';
export { PluginKnob } from './components/knob.js';
export { PluginFader } from './components/fader.js';
export { PluginRadio } from './components/radio.js';
export { PluginButton } from './components/button.js';
export { PluginXYPad } from './components/xypad.js';
export { PluginStepEditor } from './components/stepeditor.js';
export { PluginCurveEditor } from './components/curveeditor.js';
export { PluginNoteSelect } from './components/noteselect.js';
export { PluginChannelSelect } from './components/channelselect.js';
export { PluginGroup } from './components/group.js';
export { DisplayMeter, DisplayScope } from './components/display.js';
export {
    renderParam, renderParamList, PluginConfigPanel,
} from './components/renderparam.js';
