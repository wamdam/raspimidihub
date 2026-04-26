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
    get_defaults,
    params_to_dicts,
)
from .alsa_client import PluginAlsaClient
from .clock_bus import ClockBus
from .instance import PluginInstance

log = logging.getLogger(__name__)


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

    # Imports allowed for plugins (sandbox)
    _ALLOWED_IMPORTS = frozenset({
        "math", "random", "collections", "dataclasses", "enum",
        "threading", "time", "queue",
        "raspimidihub.plugin_api",
    })

    def _load_plugin_class(self, type_name: str, init_file: Path) -> type[PluginBase] | None:
        """Import a plugin module and find the PluginBase subclass."""
        # Validate imports before loading
        source = init_file.read_text()
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                # Extract module name
                if stripped.startswith("from "):
                    mod = stripped.split()[1].split(".")[0]
                else:
                    mod = stripped.split()[1].split(".")[0].split(",")[0]
                if mod not in self._ALLOWED_IMPORTS and not mod.startswith("raspimidihub"):
                    log.warning("Plugin %s uses disallowed import: %s", type_name, mod)
                    return None

        module_name = f"raspimidihub_plugin_{type_name}"
        spec = importlib.util.spec_from_file_location(module_name, init_file)
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Find the PluginBase subclass
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (isinstance(obj, type) and issubclass(obj, PluginBase)
                    and obj is not PluginBase):
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

        instance.plugin._send_note_on = lambda ch, note, vel: alsa_client.send_event(
            MidiEventType.NOTEON, channel=ch, note=note, velocity=vel)
        instance.plugin._send_note_off = lambda ch, note: alsa_client.send_event(
            MidiEventType.NOTEOFF, channel=ch, note=note, velocity=0)
        instance.plugin._send_cc = lambda ch, cc, val: alsa_client.send_event(
            MidiEventType.CONTROLLER, channel=ch, cc=cc, value=val)
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

        # Wire display output callback (throttled — plugins may call this rapidly)
        import time as _time
        _last_display = {}
        def _on_display(name, value):
            now = _time.monotonic()
            if now - _last_display.get(name, 0) < 0.05:  # 20 Hz max per display output
                return
            _last_display[name] = now
            if self._on_display_callback:
                self._on_display_callback(instance.id, name, value)
        instance.plugin._notify_display = _on_display

        # Wire param change callback for CC automation UI updates.
        # Throttle dedupe-style: drop consecutive updates with the same
        # value within 50 ms (CC-automation flood control). A different
        # value always passes through immediately so trigger-style
        # True→False resets aren't swallowed.
        _last_param = {}
        def _on_param_change(name, value):
            now = _time.monotonic()
            last_time, last_val = _last_param.get(name, (0.0, object()))
            if value == last_val and now - last_time < 0.05:
                return
            _last_param[name] = (now, value)
            if self._on_param_change_callback:
                self._on_param_change_callback(instance.id, name, value)
        instance.plugin._notify_param_change = _on_param_change

        # Every instance gets a tick/transport queue so on_transport_start/stop
        # reaches all plugins, not just those subscribed to clock ticks.
        import queue
        instance._tick_queue = queue.Queue(maxsize=64)
        instance._tick_pipe = os.pipe()
        os.set_blocking(instance._tick_pipe[0], False)
        os.set_blocking(instance._tick_pipe[1], False)
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
                # Check if this CC is mapped to a param
                if cc_num in plugin.cc_inputs:
                    param_name = plugin.cc_inputs[cc_num]
                    self._cc_to_param(instance, param_name, cc_val)
                else:
                    plugin.on_cc(ev.data.note.channel, cc_num, cc_val)
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

        instance.plugin._param_values[name] = value

        try:
            instance.plugin.on_param_change(name, value)
        except Exception as e:
            log.warning("Plugin %s on_param_change error: %s", instance.name, e)

        # Notify UI via callback (set by API layer)
        if instance.plugin._notify_param_change:
            try:
                instance.plugin._notify_param_change(name, value)
            except Exception:
                pass

    def set_params(self, instance_id: str, params: dict[str, Any]) -> None:
        """Update multiple parameters at once."""
        for name, value in params.items():
            self.set_param(instance_id, name, value)

    # --- Query ---

    def get_instance(self, instance_id: str) -> PluginInstance | None:
        return self._instances.get(instance_id)

    def get_instances(self) -> list[PluginInstance]:
        return list(self._instances.values())

    def get_instance_data(self, instance_id: str) -> dict | None:
        """Get full instance data for API response."""
        instance = self._instances.get(instance_id)
        if instance is None:
            return None

        cls = instance.plugin.__class__
        return {
            "id": instance.id,
            "type": instance.plugin_type,
            "name": instance.name,
            "status": "crashed" if instance.crashed else ("running" if instance.running else "stopped"),
            "crash_error": instance.crash_error,
            "client_id": instance.alsa_client.client_id if instance.alsa_client else None,
            "in_port": instance.alsa_client.in_port if instance.alsa_client else None,
            "out_port": instance.alsa_client.out_port if instance.alsa_client else None,
            "params_schema": params_to_dicts(cls.params),
            "params": dict(instance.plugin._param_values),
            "cc_inputs": {str(k): v for k, v in cls.cc_inputs.items()},
            "cc_outputs": cls.cc_outputs,
            "inputs": cls.inputs,
            "outputs": cls.outputs,
            "clock_divisions": cls.clock_divisions,
            "help": cls.HELP,
            "display_outputs": cls.display_outputs,
            "display_values": dict(instance.plugin._display_values),
        }

    def get_plugin_client_ids(self) -> set[int]:
        """Return ALSA client IDs of all running plugin instances."""
        ids = set()
        for instance in self._instances.values():
            if instance.alsa_client:
                ids.add(instance.alsa_client.client_id)
        return ids

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

    def serialize_instances(self) -> list[dict]:
        """Serialize all instances for config save."""
        result = []
        for instance in self._instances.values():
            result.append({
                "id": instance.id,
                "type": instance.plugin_type,
                "name": instance.name,
                "params": dict(instance.plugin._param_values),
            })
        return result

    def restore_instances(self, saved: list[dict]) -> None:
        """Recreate instances from saved config data, preserving original IDs."""
        for item in saved:
            plugin_type = item.get("type", "")
            name = item.get("name", "")
            saved_id = item.get("id", "")
            saved_params = item.get("params", {})

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
