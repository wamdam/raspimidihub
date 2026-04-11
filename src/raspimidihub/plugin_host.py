"""Plugin host — discovery, instance lifecycle, threads, ALSA ports, clock bus.

Each plugin instance runs in its own thread with its own ALSA sequencer client.
The host manages creation, param updates, clock distribution, and crash isolation.
"""

import ctypes
import importlib
import importlib.util
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .plugin_api import (
    PluginBase, Param, Group, StepEditor, CurveEditor,
    get_all_params, get_defaults, params_to_dicts,
)

log = logging.getLogger(__name__)

# ALSA constants (duplicated from alsa_seq to avoid circular imports)
SND_SEQ_OPEN_DUPLEX = 3
SND_SEQ_NONBLOCK = 1
SND_SEQ_PORT_CAP_READ = 1 << 0
SND_SEQ_PORT_CAP_SUBS_READ = 1 << 5
SND_SEQ_PORT_CAP_WRITE = 1 << 1
SND_SEQ_PORT_CAP_SUBS_WRITE = 1 << 6
SND_SEQ_PORT_TYPE_MIDI_GENERIC = 1 << 1
SND_SEQ_PORT_TYPE_APPLICATION = 1 << 20
SND_SEQ_QUEUE_DIRECT = 253
SND_SEQ_ADDRESS_SUBSCRIBERS = 254

# Sandbox: allowed imports for plugins
ALLOWED_IMPORTS = frozenset({
    "math", "random", "collections", "dataclasses", "enum",
    "raspimidihub.plugin_api",
})

# ---------------------------------------------------------------------------
# Plugin ALSA client — lightweight wrapper for plugin threads
# ---------------------------------------------------------------------------

class PluginAlsaClient:
    """Minimal ALSA seq client for a plugin instance.

    Creates its own handle with an IN port (writable) and OUT port (readable).
    """

    def __init__(self, client_name: str):
        from .alsa_seq import (
            SndSeqPtr, SndSeqEvent, SndSeqAddr, SndSeqEventPtr,
            snd_seq_open, snd_seq_close, snd_seq_set_client_name,
            snd_seq_client_id, snd_seq_create_simple_port,
            snd_seq_event_input, snd_seq_event_output_direct,
            snd_seq_poll_descriptors_count, snd_seq_poll_descriptors,
            check, MidiEventType,
        )
        self._alsa = sys.modules["raspimidihub.alsa_seq"]

        self._handle = SndSeqPtr()
        check(snd_seq_open(
            ctypes.byref(self._handle), b"default",
            SND_SEQ_OPEN_DUPLEX, SND_SEQ_NONBLOCK,
        ), "plugin: open seq")
        snd_seq_set_client_name(self._handle, client_name.encode())
        self._client_id = snd_seq_client_id(self._handle)

        # IN port — receives MIDI (writable by subscribers)
        self._in_port = snd_seq_create_simple_port(
            self._handle, b"IN",
            SND_SEQ_PORT_CAP_WRITE | SND_SEQ_PORT_CAP_SUBS_WRITE,
            SND_SEQ_PORT_TYPE_MIDI_GENERIC | SND_SEQ_PORT_TYPE_APPLICATION,
        )
        check(self._in_port, "plugin: create IN port")

        # OUT port — sends MIDI (readable by subscribers)
        self._out_port = snd_seq_create_simple_port(
            self._handle, b"OUT",
            SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ,
            SND_SEQ_PORT_TYPE_MIDI_GENERIC | SND_SEQ_PORT_TYPE_APPLICATION,
        )
        check(self._out_port, "plugin: create OUT port")

        # Rate limiter
        self._rate_window = []

    @property
    def client_id(self) -> int:
        return self._client_id

    @property
    def in_port(self) -> int:
        return self._in_port

    @property
    def out_port(self) -> int:
        return self._out_port

    def fileno(self) -> int:
        import struct
        count = self._alsa.snd_seq_poll_descriptors_count(self._handle, 1)
        buf = ctypes.create_string_buffer(8 * count)
        self._alsa.snd_seq_poll_descriptors(self._handle, buf, count, 1)
        return struct.unpack_from("i", buf, 0)[0]

    def read_event(self):
        ev = self._alsa.SndSeqEventPtr()
        ret = self._alsa.snd_seq_event_input(self._handle, ctypes.byref(ev))
        if ret < 0:
            return None
        return ev.contents

    def send_event(self, ev_type: int, **kwargs) -> None:
        """Build and send an ALSA event on the OUT port. Rate-limited."""
        # Drop events if rate exceeds DIN MIDI limit (1000/sec)
        now = time.monotonic()
        self._rate_window = [t for t in self._rate_window if now - t < 1.0]
        if len(self._rate_window) >= 1000:
            return
        self._rate_window.append(now)

        ev = self._alsa.SndSeqEvent()
        ev.type = ev_type
        ev.source.client = self._client_id
        ev.source.port = self._out_port
        ev.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
        ev.dest.port = 0
        ev.queue = SND_SEQ_QUEUE_DIRECT
        ev.flags = 0

        MidiEventType = self._alsa.MidiEventType

        if ev_type in (MidiEventType.NOTEON, MidiEventType.NOTEOFF, MidiEventType.KEYPRESS):
            ev.data.note.channel = kwargs.get("channel", 0)
            ev.data.note.note = kwargs.get("note", 0)
            ev.data.note.velocity = kwargs.get("velocity", 0)
        elif ev_type == MidiEventType.CONTROLLER:
            ev.data.control.channel = kwargs.get("channel", 0)
            ev.data.control.param = kwargs.get("cc", 0)
            ev.data.control.value = kwargs.get("value", 0)
        elif ev_type == MidiEventType.PITCHBEND:
            ev.data.control.channel = kwargs.get("channel", 0)
            ev.data.control.value = kwargs.get("value", 0)
        elif ev_type == MidiEventType.CHANPRESS:
            ev.data.control.channel = kwargs.get("channel", 0)
            ev.data.control.value = kwargs.get("value", 0)
        elif ev_type == MidiEventType.PGMCHANGE:
            ev.data.control.channel = kwargs.get("channel", 0)
            ev.data.control.value = kwargs.get("value", 0)

        self._alsa.snd_seq_event_output_direct(self._handle, ctypes.pointer(ev))

    def close(self) -> None:
        if self._handle:
            self._alsa.snd_seq_close(self._handle)
            self._handle = self._alsa.SndSeqPtr()


# ---------------------------------------------------------------------------
# Plugin instance — wraps a plugin object + its thread + ALSA client
# ---------------------------------------------------------------------------

@dataclass
class PluginInstance:
    id: str
    plugin_type: str  # directory name, e.g. "arpeggiator"
    name: str         # user-facing name, e.g. "Arp 1"
    plugin: PluginBase
    alsa_client: PluginAlsaClient | None = None
    thread: threading.Thread | None = None
    running: bool = False
    crashed: bool = False
    crash_error: str = ""
    _tick_queue: object = None  # queue.Queue for clock ticks from bus
    _tick_pipe: tuple = None   # (read_fd, write_fd) for waking select on tick


# ---------------------------------------------------------------------------
# Clock bus — distributes MIDI clock ticks to plugins
# ---------------------------------------------------------------------------

# Division: (numerator, denominator) expressed as ticks per division at 24 PPQ
# 24 PPQ means 24 ticks per quarter note
DIVISION_TICKS = {
    "1/1": 96,    # 4 quarter notes
    "1/2": 48,    # 2 quarter notes
    "1/4": 24,    # 1 quarter note
    "1/8": 12,
    "1/16": 6,
    "1/32": 3,
    "1/4T": 16,   # triplet: 24/1.5
    "1/8T": 8,    # triplet: 12/1.5
    "1/16T": 4,   # triplet: 6/1.5
}


class ClockBus:
    """Counts incoming MIDI clock ticks and fires on_tick() at musical divisions."""

    def __init__(self):
        self._tick_count = 0
        self._running = False  # transport running (Start received)
        self._subscribers: list[tuple[PluginInstance, set[str]]] = []
        self._lock = threading.Lock()

    def subscribe(self, instance: PluginInstance, divisions: list[str]) -> None:
        with self._lock:
            self._subscribers.append((instance, set(divisions)))

    def unsubscribe(self, instance: PluginInstance) -> None:
        with self._lock:
            self._subscribers = [(i, d) for i, d in self._subscribers if i is not instance]

    def on_clock_tick(self) -> None:
        """Called by the engine for each MIDI Clock message (24 PPQ).

        Queues tick divisions for plugin threads instead of calling
        on_tick directly — avoids blocking the asyncio event loop.
        """
        if not self._running:
            self._running = True
            self._tick_count = 0
            log.info("Clock bus: auto-started on first clock tick")
        self._tick_count += 1
        with self._lock:
            for instance, divisions in self._subscribers:
                if not instance.running:
                    continue
                for div in divisions:
                    ticks = DIVISION_TICKS.get(div, 0)
                    if ticks and self._tick_count % ticks == 0:
                        # Queue for the plugin thread via its tick queue
                        q = getattr(instance, '_tick_queue', None)
                        if q is not None:
                            try:
                                q.put_nowait(div)
                                # Wake the plugin thread's select() immediately
                                pipe = getattr(instance, '_tick_pipe', None)
                                if pipe:
                                    try:
                                        os.write(pipe[1], b'\x01')
                                    except OSError:
                                        pass
                            except Exception:
                                pass

    def on_start(self) -> None:
        """MIDI Start received. Per MIDI spec, the first clock tick
        after Start is beat 1. We reset tick_count to 0 so that the
        first on_clock_tick increments to 1, and divisions fire cleanly."""
        self._tick_count = 0
        self._running = True
        # Flush stale ticks from plugin queues before sending transport
        with self._lock:
            for instance, _ in self._subscribers:
                q = getattr(instance, '_tick_queue', None)
                if q:
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except Exception:
                            break
        self._notify_transport("_start")

    def on_continue(self) -> None:
        """MIDI Continue received."""
        self._running = True

    def on_stop(self) -> None:
        """MIDI Stop received."""
        self._running = False
        self._notify_transport("_stop")

    def _notify_transport(self, event: str) -> None:
        """Queue a transport event to all subscribed plugin threads."""
        with self._lock:
            for instance, _ in self._subscribers:
                if not instance.running:
                    continue
                q = getattr(instance, '_tick_queue', None)
                if q is not None:
                    try:
                        q.put_nowait(event)
                        pipe = getattr(instance, '_tick_pipe', None)
                        if pipe:
                            try:
                                os.write(pipe[1], b'\x01')
                            except OSError:
                                pass
                    except Exception:
                        pass


# ---------------------------------------------------------------------------
# PluginHost — main entry point
# ---------------------------------------------------------------------------

class PluginHost:
    """Discovers plugins, manages instances, provides API for engine/web."""

    def __init__(self, plugins_dir: str | Path | None = None):
        if plugins_dir is None:
            # Default: look for plugins/ inside the package first, then beside it
            pkg_dir = Path(__file__).parent
            candidates = [
                pkg_dir / "plugins",                      # installed: .../raspimidihub/plugins/
                pkg_dir.parent.parent / "plugins",        # dev: repo_root/plugins/
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
        from .rawmidi import send_raw_transport, get_subscribed_destinations, MIDI_START, MIDI_STOP, MIDI_CONTINUE
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

        # Wire param change callback for CC automation UI updates
        _last_param = {}
        def _on_param_change(inst_id, name, value):
            now = _time.monotonic()
            if now - _last_param.get(name, 0) < 0.05:
                return
            _last_param[name] = now
            if self._on_param_change_callback:
                self._on_param_change_callback(inst_id, name, value)
        instance.plugin._notify_param_change = _on_param_change

        # Subscribe to clock if requested
        if instance.plugin.clock_divisions:
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
            elif ev.type in (MidiEventType.CLOCK, MidiEventType.START,
                             MidiEventType.CONTINUE, MidiEventType.STOP):
                # Clock events are handled by the clock bus in the engine's
                # main event loop — don't double-process here.
                pass
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
                instance.plugin._notify_param_change(instance_id, name, value)
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
