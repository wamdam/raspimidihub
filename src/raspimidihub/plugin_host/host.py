"""PluginHost — discovers plugin classes, manages instances, exposes the
API used by the engine and the web layer.
"""

import importlib
import importlib.util
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from ..plugin_api import (
    PluginBase,
    get_all_params,
    get_default_cc_map,
    get_defaults,
    params_to_dicts,
)
from ..runtime.coalesce import TrailingCoalescer
from .alsa_client import PluginAlsaClient
from .clock_bus import ClockBus
from .instance import PluginInstance

log = logging.getLogger(__name__)


def _diff_cc_map(live: dict, default: dict) -> dict:
    """Return the subset of `live` that differs from `default`. Used
    by serialize_instances to keep saved configs tidy — a plugin
    instance the user never rebinds writes no `cc_map` field at all.
    A cleared binding (cc=None) always counts as a diff: the user's
    intent ("don't accept any CC for this param") must survive a
    restart, otherwise the seed would re-add the default."""
    diff: dict = {}
    for name, binding in live.items():
        seed = default.get(name)
        if seed is None or seed != binding:
            diff[name] = {"ch": binding.get("ch"), "cc": binding.get("cc")}
    return diff


# ---------------------------------------------------------------------------
# PluginHost — main entry point
# ---------------------------------------------------------------------------

class PluginHost:
    """Discovers plugins, manages instances, provides API for engine/web."""

    def __init__(self, plugins_dir: str | Path | None = None):
        if plugins_dir is None:
            # We live in raspimidihub/plugin_host/host.py, so:
            #   __file__.parent             = .../raspimidihub/plugin_host/
            #   __file__.parent.parent      = .../raspimidihub/        (installed: deb)
            #   __file__.parent.parent.parent       = .../site-packages or src/
            #   __file__.parent.parent.parent.parent = repo root        (dev checkout)
            pkg_dir = Path(__file__).parent
            candidates = [
                pkg_dir.parent / "plugins",                # installed: .../raspimidihub/plugins/
                pkg_dir.parent.parent.parent / "plugins",  # dev: repo_root/plugins/
            ]
            plugins_dir = next((p for p in candidates if p.is_dir()), candidates[0])
        self._plugins_dir = Path(plugins_dir)
        self._plugin_types: dict[str, type[PluginBase]] = {}  # type_name -> class
        self._instances: dict[str, PluginInstance] = {}  # id -> instance
        self._next_id: int = 1
        self._lock = threading.Lock()
        self.clock_bus = ClockBus()
        self._on_display_callback = None  # (instance_id, name, value) -> None
        self._on_param_change_callback = None  # (instance_id, name, value) -> None
        self._latency_cb = None  # set by __main__ to server.record_latency
        # Set by __main__ to engine.mark_dirty. Called on plugin instance
        # add/remove/rename and on every param change so the bottom-nav
        # asterisk lights up when in-memory state diverges from disk.
        self._on_dirty_cb = None
        # True while restore_instances() is replaying the saved config —
        # the param-change notifications it triggers are loading state
        # FROM disk, so they shouldn't dirty the flag.
        self._loading = False
        # Cached plugin-client-id set; rebuilt lazily by
        # get_plugin_client_ids() and invalidated on any add/remove.
        self._plugin_client_ids_cache: frozenset[int] | None = None
        # Trailing-edge coalescer for plugin param + display updates.
        # See runtime.coalesce.TrailingCoalescer — plugin threads
        # submit() the latest value; flush_pending_*() runs on the
        # asyncio loop at 20 Hz / 10 Hz and drains it. Caps SSE
        # plugin-param / plugin-display traffic per cell to its flusher
        # rate while guaranteeing the trailing value reaches the UI
        # within one flush interval of input ceasing.
        self._param_coalescer = TrailingCoalescer()
        self._display_coalescer = TrailingCoalescer()

    # --- Discovery ---

    def discover_plugins(self) -> dict[str, dict]:
        """Scan plugins/ directory and import plugin classes.

        Returns dict of type_name -> {name, description, author, version}.
        """
        self._plugin_types.clear()

        if not self._plugins_dir.is_dir():
            log.info("Plugins directory not found: %s", self._plugins_dir)
            return {}

        for entry in sorted(self._plugins_dir.iterdir()):
            if not entry.is_dir():
                continue
            init_file = entry / "__init__.py"
            if not init_file.is_file():
                continue

            type_name = entry.name
            try:
                plugin_class = self._load_plugin_class(type_name, init_file)
                if plugin_class and issubclass(plugin_class, PluginBase):
                    self._plugin_types[type_name] = plugin_class
                    log.info("Discovered plugin: %s (%s)", plugin_class.NAME, type_name)
            except Exception as e:
                log.warning("Failed to load plugin %s: %s", type_name, e)

        return self.list_types()

    def _load_plugin_class(self, type_name: str, init_file: Path) -> type[PluginBase] | None:
        """Import a plugin module and find the PluginBase subclass.

        Plugins are first-party code shipped in our deb — no import
        allowlist or other "sandbox" check, since real Python sandboxing
        isn't possible from within Python and this is a single-user
        trusted-environment appliance. Anything stronger (process
        isolation, RestrictedPython) would be a much bigger architectural
        change and isn't justified by the threat model. SyntaxError /
        ImportError raised below propagate to discover_plugins which
        catches them and logs "Failed to load plugin X".
        """
        module_name = f"raspimidihub_plugin_{type_name}"
        # `submodule_search_locations` makes Python treat the plugin
        # dir as a package, so a plugin's `__init__.py` can do e.g.
        # `from .tracker_base import TrackerBase` and pick up sibling
        # files from its own directory. Without this, plugins are
        # forced into a single-file shape no matter how large they
        # grow — the Tracker is the first plugin big enough to split
        # itself into multiple files.
        spec = importlib.util.spec_from_file_location(
            module_name, init_file,
            submodule_search_locations=[str(init_file.parent)],
        )
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Find the PluginBase subclass — restrict to classes actually
        # defined in this plugin's __init__.py, otherwise an imported
        # base class (e.g. raspimidihub.controller_base.ControllerBase)
        # would be picked up as the plugin instead of its subclass.
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (isinstance(obj, type) and issubclass(obj, PluginBase)
                    and obj is not PluginBase
                    and obj.__module__ == module.__name__):
                return obj

        return None

    def list_types(self) -> dict[str, dict]:
        """List available plugin types with metadata."""
        result = {}
        for type_name, cls in self._plugin_types.items():
            result[type_name] = {
                "name": cls.NAME,
                "description": cls.DESCRIPTION,
                "author": cls.AUTHOR,
                "version": cls.VERSION,
                # Surface kind drives the Add Device panel grouping:
                # "plugin" = routing-graph plugin, "controller" =
                # play-surface controller, "play" = fullscreen play
                # surface (sequencers, step-programmable arpeggiators).
                "kind": getattr(cls, "SURFACE_KIND", "plugin"),
            }
        return result

    # --- Instance lifecycle ---

    def create_instance(self, plugin_type: str, name: str = "") -> PluginInstance:
        """Create and start a new plugin instance."""
        cls = self._plugin_types.get(plugin_type)
        if cls is None:
            raise ValueError(f"Unknown plugin type: {plugin_type}")

        with self._lock:
            instance_id = f"{plugin_type}-{self._next_id}"
            self._next_id += 1

        if not name:
            # Auto-name: "Arp 1", "Arp 2", etc.
            count = sum(1 for i in self._instances.values() if i.plugin_type == plugin_type)
            name = f"{cls.NAME} {count + 1}"

        plugin = cls()
        plugin._param_values = get_defaults(cls.params)

        instance = PluginInstance(
            id=instance_id,
            plugin_type=plugin_type,
            name=name,
            plugin=plugin,
        )

        self._start_instance(instance)

        with self._lock:
            self._instances[instance_id] = instance
            self._invalidate_plugin_client_ids()

        log.info("Created plugin instance: %s (%s) -> ALSA client %d",
                 name, plugin_type,
                 instance.alsa_client.client_id if instance.alsa_client else -1)
        return instance

    def _start_instance(self, instance: PluginInstance) -> None:
        """Create ALSA client, wire send methods, start thread."""
        client_name = instance.name

        try:
            alsa_client = PluginAlsaClient(client_name)
        except Exception as e:
            log.error("Failed to create ALSA client for %s: %s", instance.name, e)
            instance.crashed = True
            instance.crash_error = str(e)
            return

        instance.alsa_client = alsa_client
        MidiEventType = sys.modules["raspimidihub.alsa_seq"].MidiEventType

        # Wire output methods
        def make_send(ev_type, **extra_fields):
            def send(**kwargs):
                kwargs.update(extra_fields)
                alsa_client.send_event(ev_type, **kwargs)
            return send

        # Wrap plugin MIDI sends so that the first send_cc following a
        # set_params on this instance records a control-in→midi-out
        # latency. The "control-in" timestamp is whatever the host last
        # stamped on instance._param_t0; window-bounded to 100 ms so a
        # later autonomous CC from the plugin doesn't get attributed to
        # the prior PATCH.
        host_self = self
        def _record_param_latency():
            t0 = getattr(instance, "_param_t0", 0.0)
            if not t0:
                return
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            instance._param_t0 = 0.0
            if elapsed_ms < 100.0 and host_self._latency_cb:
                host_self._latency_cb("control_in_midi_out", elapsed_ms)

        instance.plugin._send_note_on = lambda ch, note, vel: alsa_client.send_event(
            MidiEventType.NOTEON, channel=ch, note=note, velocity=vel)
        instance.plugin._send_note_off = lambda ch, note: alsa_client.send_event(
            MidiEventType.NOTEOFF, channel=ch, note=note, velocity=0)
        def _send_cc_with_lat(ch, cc, val):
            alsa_client.send_event(MidiEventType.CONTROLLER, channel=ch, cc=cc, value=val)
            _record_param_latency()
        instance.plugin._send_cc = _send_cc_with_lat
        instance.plugin._send_pitchbend = lambda ch, val: alsa_client.send_event(
            MidiEventType.PITCHBEND, channel=ch, value=val)
        instance.plugin._send_aftertouch = lambda ch, val: alsa_client.send_event(
            MidiEventType.CHANPRESS, channel=ch, value=val)
        instance.plugin._send_program_change = lambda ch, prog: alsa_client.send_event(
            MidiEventType.PGMCHANGE, channel=ch, value=prog)
        instance.plugin._send_clock = lambda: alsa_client.send_event(MidiEventType.CLOCK)

        # Transport: send ALSA seq event + raw MIDI bytes to hardware outputs
        # (workaround for ALSA not converting user-space transport to raw MIDI)
        from ..rawmidi import (
            MIDI_CONTINUE,
            MIDI_START,
            MIDI_STOP,
            get_subscribed_destinations,
            send_raw_transport,
        )
        def _send_transport(ev_type, raw_byte):
            alsa_client.send_event(ev_type)
            try:
                dests = get_subscribed_destinations(
                    alsa_client._handle, alsa_client.client_id, alsa_client.out_port)
                for dc, dp in dests:
                    send_raw_transport(dc, dp, raw_byte)
            except Exception:
                pass
        instance.plugin._send_start = lambda: _send_transport(MidiEventType.START, MIDI_START)
        instance.plugin._send_stop = lambda: _send_transport(MidiEventType.STOP, MIDI_STOP)
        instance.plugin._send_continue = lambda: _send_transport(MidiEventType.CONTINUE, MIDI_CONTINUE)

        # Scheduled-event variants: lands the event at an exact monotonic
        # moment via the per-client ALSA queue. Drop-button fire uses
        # this to put the snapshot CCs ahead of the bar-boundary kick;
        # other plugins migrate to it for jitter-free timing.
        instance.plugin._send_cc_at = lambda when, ch, cc, val, tag=0: \
            alsa_client.send_event_at(when, MidiEventType.CONTROLLER,
                                       tag=tag, channel=ch, cc=cc, value=val)
        instance.plugin._send_note_on_at = lambda when, ch, note, vel, tag=0: \
            alsa_client.send_event_at(when, MidiEventType.NOTEON,
                                       tag=tag, channel=ch, note=note, velocity=vel)
        instance.plugin._send_note_off_at = lambda when, ch, note, tag=0: \
            alsa_client.send_event_at(when, MidiEventType.NOTEOFF,
                                       tag=tag, channel=ch, note=note, velocity=0)
        instance.plugin._send_clock_at = lambda when, tag=0: \
            alsa_client.send_event_at(when, MidiEventType.CLOCK, tag=tag)
        instance.plugin._send_pitchbend_at = lambda when, ch, val, tag=0: \
            alsa_client.send_event_at(when, MidiEventType.PITCHBEND,
                                       tag=tag, channel=ch, value=val)
        instance.plugin._send_aftertouch_at = lambda when, ch, val, tag=0: \
            alsa_client.send_event_at(when, MidiEventType.CHANPRESS,
                                       tag=tag, channel=ch, value=val)
        instance.plugin._send_program_change_at = lambda when, ch, prog, tag=0: \
            alsa_client.send_event_at(when, MidiEventType.PGMCHANGE,
                                       tag=tag, channel=ch, value=prog)
        instance.plugin._cancel_scheduled = lambda tag: alsa_client.cancel_tag(tag)

        # Bulk SysEx output for the SysEx Sender plugin. Routed straight
        # to alsa_client.send_sysex which chunks + paces the dump.
        instance.plugin._send_sysex = alsa_client.send_sysex

        # Wire display output through the trailing-edge coalescer.
        # Plugins may call _notify_display rapidly (a sine-wave scope
        # sampling at any rate) — coalesced to 10 Hz per (instance,
        # name); the latest sample always wins, so a meter sitting at
        # 0 then jumping to 100 lands within 100 ms even if the plugin
        # emitted many intermediate samples.
        # We close over `instance` (not instance.id) so the lookup
        # honours any later id rekey — restore_instances rekeys after
        # create_instance, which used to leave the closure pointing at
        # the dead transient id and SSE events would be tagged wrong.
        host_self_d = self
        instance_d = instance
        def _on_display(name, value):
            host_self_d._display_coalescer.submit((instance_d.id, name), value)
        instance.plugin._notify_display = _on_display

        # Wire param change callback through the trailing-edge coalescer.
        # String values (radio choices, drop button action signals
        # cycling through fire/capture/idle) are state-machine
        # transitions — deliver every change immediately via emit_now().
        # Numeric / dict values (fader / knob / XY pad streams)
        # coalesce: latest value wins, drained at 20 Hz by
        # flush_pending_params() on the asyncio loop.
        # Close over `instance` (not instance.id) so the lookup honours
        # any later rekey — restore_instances rekeys to the saved id
        # AFTER create_instance, and the closure must follow.
        host_self_p = self
        instance_p = instance
        def _on_param_change(name, value, persist=True):
            # A non-transient, persisted param change is the only thing
            # that (a) marks the routing config dirty and (b) invalidates
            # this instance's autosave fragment cache. Skip both for:
            #  - transient params (live-play state on Controllers/Tracker
            #    — fader / knob / XY positions, cursor, playhead, drop
            #    fire signals): never serialized, so they can't drift.
            #  - quiet writes (persist=False — pure pattern selection /
            #    stem launches): serialized but pointer-only, so a live
            #    set paints no asterisk and forces no re-encode.
            # The value still broadcasts over SSE below regardless, so
            # the display always follows.
            saveable = (persist
                        and name not in instance_p.plugin.transient_params)
            if saveable:
                instance_p._encode_seq += 1
                if host_self_p._on_dirty_cb and not host_self_p._loading:
                    try:
                        host_self_p._on_dirty_cb()
                    except Exception:
                        pass
            key = (instance_p.id, name)
            if isinstance(value, str):
                host_self_p._param_coalescer.emit_now(
                    key, value, host_self_p._dispatch_param)
            else:
                host_self_p._param_coalescer.submit(key, value)
        instance.plugin._notify_param_change = _on_param_change

        # Every instance gets a tick/transport queue so on_transport_start/stop
        # reaches all plugins, not just those subscribed to clock ticks.
        import queue
        instance._tick_queue = queue.Queue(maxsize=64)
        instance._tick_pipe = os.pipe()
        os.set_blocking(instance._tick_pipe[0], False)
        os.set_blocking(instance._tick_pipe[1], False)
        # Hand the plugin a back-reference to the clock bus so plugins
        # that need bar/tick arithmetic (Controller drop scheduling)
        # can read it. Most plugins don't touch this attribute.
        instance.plugin._clock_bus = self.clock_bus
        self.clock_bus.subscribe(instance, instance.plugin.clock_divisions)

        # Start plugin thread
        instance.running = True
        instance.thread = threading.Thread(
            target=self._plugin_thread,
            args=(instance,),
            name=f"plugin-{instance.id}",
            daemon=True,
        )
        instance.thread.start()

    def _plugin_thread(self, instance: PluginInstance) -> None:
        """Event loop for a single plugin instance."""
        plugin = instance.plugin
        alsa_client = instance.alsa_client
        MidiEventType = sys.modules["raspimidihub.alsa_seq"].MidiEventType

        try:
            plugin.on_start()
        except Exception as e:
            log.error("Plugin %s on_start failed: %s", instance.name, e)
            instance.crashed = True
            instance.crash_error = str(e)
            instance.running = False
            return

        # Strip stranded params left over from older plugin versions
        # (e.g. the old single-pad's `pad` / `pad_snapshot` keys after
        # we switched to DropButtonRow). Runs AFTER on_start so the
        # plugin's setdefault calls have already populated whatever
        # the current schema declares.
        try:
            dropped = plugin.tidy_param_values()
            if dropped:
                log.info("Plugin %s: tidied %d stranded params: %s",
                         instance.name, len(dropped), dropped)
        except Exception:
            log.exception("tidy_param_values failed for %s", instance.name)

        fd = alsa_client.fileno()
        _logged_types = set()
        tick_queue = instance._tick_queue
        tick_pipe_r = instance._tick_pipe[0] if instance._tick_pipe else None
        watch_fds = [fd] + ([tick_pipe_r] if tick_pipe_r else [])

        import select as _select
        while instance.running:
            try:
                readable, _, _ = _select.select(watch_fds, [], [], 0.1)

                # Drain tick pipe bytes (just wake-up signals)
                if tick_pipe_r and tick_pipe_r in readable:
                    try:
                        os.read(tick_pipe_r, 64)
                    except OSError:
                        pass

                # Drain ALSA events FIRST — get latest notes before tick advances
                if fd in readable:
                    for _ in range(64):
                        ev = alsa_client.read_event()
                        if ev is None:
                            break
                        if ev.type not in _logged_types:
                            _logged_types.add(ev.type)
                            log.info("Plugin %s first event type=%d from %d:%d",
                                     instance.name, ev.type, ev.source.client, ev.source.port)
                        self._dispatch_event(instance, ev, MidiEventType)

                # Process queued clock ticks + transport events
                if tick_queue:
                    while True:
                        try:
                            msg = tick_queue.get_nowait()
                            try:
                                if msg == "_start":
                                    plugin.on_transport_start()
                                elif msg == "_stop":
                                    plugin.on_transport_stop()
                                elif msg == "_continue":
                                    plugin.on_transport_continue()
                                else:
                                    plugin.on_tick(msg)
                            except Exception as e:
                                log.warning("Plugin %s tick/transport error: %s", instance.name, e)
                        except Exception:
                            break

            except Exception as e:
                log.error("Plugin %s thread error: %s", instance.name, e)
                instance.crashed = True
                instance.crash_error = str(e)
                instance.running = False
                break

        try:
            plugin.on_stop()
        except Exception:
            pass

    _CALLBACK_TIMEOUT = 1.0  # seconds — flag plugin as crashed if callback exceeds this

    def _dispatch_event(self, instance: PluginInstance, ev, MidiEventType) -> None:
        """Dispatch an incoming ALSA event to plugin callbacks."""
        plugin = instance.plugin
        _start = time.monotonic()

        try:
            if ev.type == MidiEventType.NOTEON:
                if ev.data.note.velocity > 0:
                    plugin.on_note_on(ev.data.note.channel, ev.data.note.note, ev.data.note.velocity)
                else:
                    plugin.on_note_off(ev.data.note.channel, ev.data.note.note)
            elif ev.type == MidiEventType.NOTEOFF:
                plugin.on_note_off(ev.data.note.channel, ev.data.note.note)
            elif ev.type == MidiEventType.CONTROLLER:
                cc_num = ev.data.control.param
                cc_val = ev.data.control.value
                cc_ch = ev.data.control.channel
                # Walk the per-instance cc_map. Multiple params may bind
                # to the same CC (collisions are intentional — one CC
                # can drive several controls); each matching entry fires
                # its own param update. Cleared bindings carry cc=None
                # and are skipped.
                matched = False
                for param_name, binding in plugin.cc_map.items():
                    b_cc = binding.get("cc")
                    if b_cc is None or b_cc != cc_num:
                        continue
                    b_ch = binding.get("ch")
                    if b_ch is not None and b_ch != cc_ch:
                        continue
                    self._cc_to_param(instance, param_name, cc_val)
                    matched = True
                if not matched:
                    plugin.on_cc(cc_ch, cc_num, cc_val)
            elif ev.type == MidiEventType.PITCHBEND:
                plugin.on_pitchbend(ev.data.control.channel, ev.data.control.value)
            elif ev.type == MidiEventType.CHANPRESS:
                plugin.on_aftertouch(ev.data.control.channel, ev.data.control.value)
            elif ev.type == MidiEventType.PGMCHANGE:
                plugin.on_program_change(ev.data.control.channel, ev.data.control.value)
            elif ev.type == MidiEventType.CLOCK:
                plugin.on_clock()
            elif ev.type == MidiEventType.START:
                plugin.on_clock_start()
            elif ev.type == MidiEventType.CONTINUE:
                plugin.on_clock_continue()
            elif ev.type == MidiEventType.STOP:
                plugin.on_clock_stop()
        except Exception as e:
            log.warning("Plugin %s event handler error: %s", instance.name, e)

        # Watchdog: flag as crashed if callback took too long
        elapsed = time.monotonic() - _start
        if elapsed > self._CALLBACK_TIMEOUT:
            log.error("Plugin %s callback took %.1fs (limit %.1fs) — marking as crashed",
                      instance.name, elapsed, self._CALLBACK_TIMEOUT)
            instance.crashed = True
            instance.crash_error = f"Callback timeout ({elapsed:.1f}s)"
            instance.running = False

    def _cc_to_param(self, instance: PluginInstance, param_name: str, cc_value: int) -> None:
        """Map a CC value (0-127) to a param's range and update it."""
        all_params = get_all_params(instance.plugin.__class__.params)
        param_def = None
        for p in all_params:
            if p.name == param_name:
                param_def = p
                break

        if param_def is None:
            return

        # Map 0-127 to param range
        if hasattr(param_def, "min") and hasattr(param_def, "max"):
            pmin = param_def.min
            pmax = param_def.max
            value = pmin + (cc_value / 127) * (pmax - pmin)
            value = round(value)
        elif hasattr(param_def, "options"):
            # Radio: map to option index
            idx = round(cc_value / 127 * (len(param_def.options) - 1))
            value = param_def.options[idx]
        elif isinstance(param_def, type) and issubclass(param_def.__class__, type):
            value = cc_value
        else:
            value = cc_value

        self.set_param(instance.id, param_name, value)

    def stop_instance(self, instance_id: str) -> None:
        """Stop and remove a plugin instance."""
        with self._lock:
            instance = self._instances.pop(instance_id, None)
            self._invalidate_plugin_client_ids()

        if instance is None:
            return

        instance.running = False

        # Wake the plugin thread's select() right now so thread.join
        # returns in milliseconds instead of waiting for the next 100ms
        # poll cycle.
        if getattr(instance, "_tick_pipe", None):
            try:
                os.write(instance._tick_pipe[1], b"\x01")
            except OSError:
                pass

        # Unsubscribe from clock
        self.clock_bus.unsubscribe(instance)

        # Wait for thread
        if instance.thread and instance.thread.is_alive():
            instance.thread.join(timeout=2.0)

        # Close ALSA client
        if instance.alsa_client:
            try:
                instance.alsa_client.close()
            except Exception:
                pass

        log.info("Stopped plugin instance: %s (%s)", instance.name, instance.id)

    # --- Param management ---

    def set_param(self, instance_id: str, name: str, value: Any) -> None:
        """Update a parameter value and notify the plugin."""
        instance = self._instances.get(instance_id)
        if instance is None:
            return

        # Stamp control-in time so a downstream send_cc within 100 ms can
        # report control_in_midi_out latency (see _record_param_latency).
        instance._param_t0 = time.monotonic()

        instance.plugin._param_values[name] = value

        # Broadcast to the UI BEFORE running on_param_change. The plugin
        # may synchronously call its own set_param() inside the handler
        # (e.g. DropButtonRow's drops.action cycles fire → idle as soon
        # as the action is processed); broadcasting the incoming value
        # first keeps the order on the wire correct so the plugin's
        # correction lands second and wins.
        if instance.plugin._notify_param_change:
            try:
                instance.plugin._notify_param_change(name, value)
            except Exception:
                pass

        try:
            instance.plugin.on_param_change(name, value)
        except Exception as e:
            log.warning("Plugin %s on_param_change error: %s", instance.name, e)

    def set_params(self, instance_id: str, params: dict[str, Any]) -> None:
        """Update multiple parameters at once."""
        for name, value in params.items():
            self.set_param(instance_id, name, value)

    # --- Query ---

    def get_instance(self, instance_id: str) -> PluginInstance | None:
        return self._instances.get(instance_id)

    def _dispatch_param(self, key, value) -> None:
        """Coalescer emit callback — fan out to the registered
        plugin-param SSE handler. Key is (instance_id, name)."""
        cb = self._on_param_change_callback
        if cb:
            cb(key[0], key[1], value)

    def _dispatch_display(self, key, value) -> None:
        """Coalescer emit callback for plugin-display."""
        cb = self._on_display_callback
        if cb:
            cb(key[0], key[1], value)

    def flush_pending_params(self) -> None:
        """Drain the param coalescer. Called at 20 Hz from
        runtime.loops.pending_param_flusher. Each call broadcasts the
        latest queued value per (instance_id, name) — older queued
        values dropped (UI couldn't render them anyway), but the
        freshest value always wins, so a sweeping fader's final
        position lands within 50 ms even when 1000 intermediate
        updates were skipped."""
        self._param_coalescer.flush(self._dispatch_param)

    def flush_pending_displays(self) -> None:
        """Drain the display coalescer. Called at 10 Hz."""
        self._display_coalescer.flush(self._dispatch_display)

    def get_instances(self) -> list[PluginInstance]:
        return list(self._instances.values())

    def get_instance_data(self, instance_id: str) -> dict | None:
        """Get full instance data for API response."""
        instance = self._instances.get(instance_id)
        if instance is None:
            return None

        cls = instance.plugin.__class__
        # params_schema is built from class-level dataclasses that never
        # change at runtime — cache the serialized form on the class so
        # we don't rebuild ~300 nested dicts per controller page load /
        # PATCH response. This was a meaningful share of asyncio CPU.
        schema = getattr(cls, "_params_schema_cache", None)
        if schema is None:
            schema = params_to_dicts(cls.params)
            cls._params_schema_cache = schema
        return {
            "id": instance.id,
            "type": instance.plugin_type,
            "kind": getattr(cls, "SURFACE_KIND", "plugin"),
            "name": instance.name,
            "status": "crashed" if instance.crashed else ("running" if instance.running else "stopped"),
            "crash_error": instance.crash_error,
            "client_id": instance.alsa_client.client_id if instance.alsa_client else None,
            "in_port": instance.alsa_client.in_port if instance.alsa_client else None,
            "out_port": instance.alsa_client.out_port if instance.alsa_client else None,
            "params_schema": schema,
            "params": dict(instance.plugin._param_values),
            "cc_map": dict(instance.plugin.cc_map),
            "default_cc_map": get_default_cc_map(cls.params),
            "cc_outputs": cls.cc_outputs,
            "inputs": cls.inputs,
            "outputs": cls.outputs,
            "clock_divisions": cls.clock_divisions,
            "help": cls.HELP,
            "display_outputs": cls.display_outputs,
            "display_values": dict(instance.plugin._display_values),
        }

    def get_plugin_client_ids(self) -> frozenset[int]:
        """Return ALSA client IDs of all running plugin instances.

        Cached: the set rebuilds only when an instance is added or
        removed (invalidate_plugin_client_ids called from create /
        stop / restore paths). The hot path — engine.run_event_loop
        consults this set on every MIDI event to decide whether the
        source is a plugin — was rebuilding the set each call, which
        showed up as ~5 % of CPU under streaming-controller load."""
        if self._plugin_client_ids_cache is None:
            ids = set()
            for instance in self._instances.values():
                if instance.alsa_client:
                    ids.add(instance.alsa_client.client_id)
            self._plugin_client_ids_cache = frozenset(ids)
        return self._plugin_client_ids_cache

    def _invalidate_plugin_client_ids(self) -> None:
        """Drop the cached client-id set. Called by create_instance,
        stop_instance, and restore_instances after they mutate
        self._instances."""
        self._plugin_client_ids_cache = None

    def client_feeds_clock_bus(self, client_id: int) -> bool:
        """True if `client_id` is a plugin instance whose OUT-port clock
        should feed the global ClockBus. Only pure clock generators
        (Master Clock — `feeds_clock_bus = True`) qualify; clock
        processors and everything else default to False so their emission
        doesn't pollute the bus's tempo perception.

        External hardware clients (not plugins) also return False here;
        they're handled separately at the call site by the monitor-port
        check.
        """
        for instance in self._instances.values():
            if instance.alsa_client and instance.alsa_client.client_id == client_id:
                return bool(instance.plugin.__class__.feeds_clock_bus)
        return False

    def rename_instance(self, instance_id: str, new_name: str) -> bool:
        """Rename a plugin instance."""
        instance = self._instances.get(instance_id)
        if instance is None:
            return False
        instance.name = new_name
        return True

    # --- Serialization for config persistence ---

    def instance_encode_seqs(self) -> dict[str, int]:
        """{instance_id: encode_seq} for the autosave fragment cache.
        Read on the asyncio loop right after the snapshot so it's
        race-free against hotplug (which also runs on the loop)."""
        return {inst.id: inst._encode_seq for inst in self._instances.values()}

    def serialize_instances(self) -> list[dict]:
        """Serialize all instances for config save. Transient params
        (live-play state — playhead position, drop fire signals,
        cmd_play / cmd_stop, note_preview …) are filtered out so a
        save mid-play doesn't carry trigger-style truthy values into
        the next plugin restart, where they'd replay through
        on_param_change and re-fire whatever action they signal.

        cc_map is persisted only when it differs from the default
        seed — keeping configs tidy for plugins the user never
        rebinds. A cleared binding (cc=None) always serialises so
        the clear survives a restart."""
        result = []
        for instance in self._instances.values():
            transient = getattr(instance.plugin, "transient_params", set()) or set()
            params = {k: v for k, v in instance.plugin._param_values.items()
                      if k not in transient}
            entry = {
                "id": instance.id,
                "type": instance.plugin_type,
                "name": instance.name,
                "params": params,
            }
            cc_map = _diff_cc_map(instance.plugin.cc_map,
                                  get_default_cc_map(type(instance.plugin).params))
            if cc_map:
                entry["cc_map"] = cc_map
            result.append(entry)
        return result

    def restore_instances(self, saved: list[dict]) -> None:
        """Recreate instances from saved config data, preserving original IDs."""
        self._loading = True
        try:
            self._restore_instances(saved)
        finally:
            self._loading = False

    def _restore_instances(self, saved: list[dict]) -> None:
        for item in saved:
            plugin_type = item.get("type", "")
            name = item.get("name", "")
            saved_id = item.get("id", "")
            saved_params = item.get("params", {})
            saved_cc_map = item.get("cc_map", {})

            try:
                instance = self.create_instance(plugin_type, name)
                # Re-key with original saved ID so stable IDs match saved connections
                if saved_id and saved_id != instance.id:
                    with self._lock:
                        del self._instances[instance.id]
                        instance.id = saved_id
                        self._instances[saved_id] = instance
                    # Bump _next_id past any restored numeric suffix
                    try:
                        num = int(saved_id.rsplit("-", 1)[-1])
                        self._next_id = max(self._next_id, num + 1)
                    except ValueError:
                        pass
                    log.info("Restored plugin %s with saved ID %s", name, saved_id)
                # Overlay saved cc_map on top of the default seed
                for pname, binding in saved_cc_map.items():
                    if not isinstance(binding, dict):
                        continue
                    instance.plugin.cc_map[pname] = {
                        "ch": binding.get("ch"),
                        "cc": binding.get("cc"),
                    }
                # Apply saved params
                for pname, pvalue in saved_params.items():
                    self.set_param(instance.id, pname, pvalue)
            except Exception as e:
                log.warning("Failed to restore plugin %s (%s): %s", name, plugin_type, e)

    def stop_all(self) -> None:
        """Stop all plugin instances."""
        for instance_id in list(self._instances.keys()):
            self.stop_instance(instance_id)

    def panic_all(self) -> None:
        """Tell every live plugin to release its internal note state."""
        for instance in list(self._instances.values()):
            if not instance.running:
                continue
            try:
                instance.plugin.panic()
            except Exception:
                log.exception("Plugin %s panic() failed", instance.id)
