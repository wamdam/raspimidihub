#!/usr/bin/env python3
"""RaspiMIDIHub timing/jitter perf harness.

Reads the hub's /api/stats timing distributions (clock-tick jitter, loop
lag, …) and runs two kinds of measurement:

  passive  — start a MIDI scene, let it run, sample distributions over
             time; report percentiles/histograms. Good for multi-hour
             stability soaks.
  ops      — an OPERATIONS-DISTURBANCE sweep: with MIDI playing, perform
             each disruptive operation (add plugin, remove plugin, add
             cable, change filter, save, load) one at a time and attribute
             the jitter/loop-lag it injects to that operation. This is the
             latency-regression detector — run it after a change and watch
             for any operation's impact growing.

Hub-stats-only: jitter/drift are measured on the Pi's stable monotonic
clock, which is honest for *relative* timing. Absolute input→wire latency
needs external capture and is intentionally out of scope.

Examples:
  perf.py --target http://10.1.1.2 --mode ops
  perf.py --target http://10.1.1.2 --mode passive --duration 3600
  perf.py --target http://10.1.1.2 --mode both --out runs/

NEVER point --mode ops at a live performance rig: it creates/deletes
plugins and Saves/Loads config on the target.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

WATCHED = ("loop_lag", "clock_tick_jitter", "plugin_note_jitter", "net_midi_rx")


# --- HTTP ---------------------------------------------------------------

def _req(method, url, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


class Hub:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def get(self, path):
        return _req("GET", self.base + path)

    def post(self, path, body=None):
        return _req("POST", self.base + path, body if body is not None else {})

    def delete(self, path):
        return _req("DELETE", self.base + path)

    # --- perf stats ---
    def reset_stats(self):
        self.post("/api/stats/reset")

    def stats(self):
        return self.get("/api/stats")

    # --- scene control ---
    def create_plugin(self, ptype, name):
        return self.post("/api/plugins/instances", {"type": ptype, "name": name})

    def delete_plugin(self, pid):
        return self.delete("/api/plugins/instances/" + pid)

    def instances(self):
        return self.get("/api/plugins/instances")

    def patch_params(self, pid, params):
        return _req("PATCH", self.base + "/api/plugins/instances/" + pid,
                    {"params": params})

    def connect(self, sc, sp, dc, dp):
        return self.post("/api/connections",
                         {"src_client": sc, "src_port": sp,
                          "dst_client": dc, "dst_port": dp})

    def disconnect(self, conn_id):
        return self.delete("/api/connections/" + conn_id)

    def add_mapping(self, conn_id):
        return self.post("/api/mappings/" + conn_id,
                         {"type": "channel_map", "src_channel": 1, "dst_channel": 2})

    def save(self):
        return self.post("/api/config/save")

    def load(self):
        return self.post("/api/config/load")

    # --- network MIDI (two-Pi) ---
    def enable_netmidi(self, on=True):
        return self.post("/api/network-midi/enable", {"enabled": on})

    def export_device(self, stable_id, on=True):
        return self.post("/api/network-midi/export",
                         {"stable_id": stable_id, "exported": on})

    def add_peer(self, host):
        return self.post("/api/network-midi/peers", {"host": host})

    def netmidi(self):
        return self.get("/api/network-midi")

    def device_stable_id(self, instance_id):
        devs = self.get("/api/devices")
        devs = devs if isinstance(devs, list) else devs.get("devices", [])
        return next((d.get("stable_id") for d in devs
                     if d.get("plugin_instance_id") == instance_id), None)


# --- reporting helpers --------------------------------------------------

def _fmt_metric(snap):
    if not snap or snap.get("count", 0) == 0:
        return "no samples"
    return (f"n={snap['count']:<5} p50={snap['p50']:.3f} p95={snap['p95']:.3f} "
            f"p99={snap['p99']:.3f} max={snap['max']:.3f} ms")


def _watched(metrics):
    return {k: metrics.get(k) for k in WATCHED if metrics.get(k)}


# --- scene orchestration ------------------------------------------------

def build_scene(hub, bpm):
    """Create a small MIDI-producing scene: a running Tracker as clock
    master + an Arpeggiator wired to it (clock + notes flowing). Returns
    the created instance ids for teardown. Best-effort."""
    created = []
    try:
        trk = hub.create_plugin("tracker", "perf-clock")
        created.append(trk["id"])
        hub.patch_params(trk["id"], {"bpm": bpm, "send_clock": True, "running": True})
        arp = hub.create_plugin("arpeggiator", "perf-arp")
        created.append(arp["id"])
        # Wire tracker out -> arp in so clock reaches the bus.
        hub.connect(trk["client_id"], trk["out_port"], arp["client_id"], arp["in_port"])
        time.sleep(1.0)
    except Exception as e:
        print(f"  (scene setup partial: {e})")
    return created


def teardown_scene(hub, ids):
    for pid in ids:
        try:
            hub.delete_plugin(pid)
        except Exception:
            pass


# --- modes --------------------------------------------------------------

def run_passive(hub, duration, poll, out):
    print(f"== passive: {duration}s, poll {poll}s ==")
    hub.reset_stats()
    timeline = []
    t_end = time.monotonic() + duration
    while time.monotonic() < t_end:
        time.sleep(poll)
        s = hub.stats()
        row = {"t": round(time.monotonic(), 2), "metrics": _watched(s.get("metrics", {})),
               "ctx": s.get("context", {})}
        timeline.append(row)
        m = row["metrics"]
        cpu = s.get("context", {}).get("cpu_cores", [])
        cpu_s = " ".join(f"c{c['core']}={c['pct']:.0f}" for c in cpu)
        print(f"  t+{row['t']:.0f}s  " +
              "  ".join(f"{k}:{_fmt_metric(v)}" for k, v in m.items()) +
              (f"   [{cpu_s}]" if cpu_s else ""))
    final = hub.stats().get("metrics", {})
    print("\n-- final distributions --")
    for k in WATCHED:
        if final.get(k):
            print(f"  {k:20s} {_fmt_metric(final[k])}")
    if out:
        _write(out + "-passive.json", {"final": final, "timeline": timeline})
    return final


OPS = ["add_plugin", "add_cable", "change_filter", "save", "load",
       "remove_plugin"]


def run_ops(hub, settle, out, ops=None):
    ops = ops or OPS
    print(f"== operations-disturbance sweep (settle {settle}s each) ==")
    results = []
    # Keep the full create-response dicts (they carry client_id + ports;
    # the GET list does not), so we can cable between known plugins.
    created = [hub.create_plugin("scale_remapper", "perf-anchor")]
    last_conn = [None]

    def do(op):
        if op == "add_plugin":
            created.append(hub.create_plugin("note_splitter", "perf-tmp"))
        elif op == "remove_plugin":
            if len(created) > 1:
                hub.delete_plugin(created.pop()["id"])
        elif op == "add_cable":
            if len(created) >= 2:
                a, b = created[0], created[1]
                hub.connect(a["client_id"], a["out_port"], b["client_id"], b["in_port"])
                last_conn[0] = (f"{a['client_id']}:{a['out_port']}-"
                                f"{b['client_id']}:{b['in_port']}")
        elif op == "change_filter":
            if last_conn[0]:
                hub.add_mapping(last_conn[0])
        elif op == "save":
            hub.save()
        elif op == "load":
            hub.load()

    for op in ops:
        hub.reset_stats()
        time.sleep(0.3)                       # baseline gap
        t0 = time.monotonic()
        try:
            do(op)
        except Exception as e:
            print(f"  {op:14s} ERROR {e}")
            continue
        wall = (time.monotonic() - t0) * 1000
        time.sleep(settle)                    # let the spike land + settle
        s = hub.stats().get("metrics", {})
        # The op_* metric is the operation's OWN synchronous loop-blocking
        # time (self-measured on the hub) — accurate for real hardware
        # ops, unlike inferring from loop_lag with synthetic plugins.
        op_self = next((s[k] for k in s if k.startswith("op_") and s[k].get("count")), None)
        row = {"op": op, "wall_ms": round(wall, 1), "self": op_self,
               "loop_lag": s.get("loop_lag"), "clock_tick_jitter": s.get("clock_tick_jitter")}
        results.append(row)
        ll = s.get("loop_lag") or {}
        cj = s.get("clock_tick_jitter") or {}
        self_max = (op_self or {}).get("max", "-")
        print(f"  {op:14s} wall={wall:6.0f}ms  self-block={self_max}  "
              f"loop_lag max={ll.get('max','-')}  clock_jitter max={cj.get('max','-')}")
    teardown_scene(hub, [p["id"] for p in created])
    print("\n-- per-operation impact: loop-lag / clock-tick delay (max ms) --")
    for r in results:
        ll = (r.get("loop_lag") or {}).get("max")
        cj = (r.get("clock_tick_jitter") or {}).get("max")
        worst = max(ll or 0, cj or 0)
        flag = " <== DELAYS TICKS" if worst > 10 else ""
        print(f"  {r['op']:14s} loop_lag={ll}  clock_tick_delay={cj}{flag}")
    if out:
        _write(out + "-ops.json", results)
    return results


# Live-performance UI actions (don't tear down the mirror — Load/Save are
# excluded here; Load would drop the mirror mid-test).
CROSS_OPS = ["add_plugin", "add_cable", "change_filter", "remove_plugin"]


def run_cross(hubB, peer_url, peer_ip, settle, out, bpm):
    """Two-Pi RECEIVED-CLOCK punctuality test. Pi A (peer) is the master:
    it exports a running clock tracker over Network MIDI. Pi B (target)
    mirrors it, so B's clock comes entirely from A. We then perform UI
    actions on B and measure how much each DELAYS THE RECEIVED TICKS
    (clock_tick_jitter on B) — i.e. does adding a cable / changing a
    filter / a plugin churn make B stutter the master clock. Restores
    both via Load."""
    hubA = Hub(peer_url)
    print(f"== cross-Pi received-clock test: master={peer_url}  mirror={hubB.base} ==")
    try:
        hubA.enable_netmidi(True)
        trk = hubA.create_plugin("tracker", "perf-netclock")
        hubA.patch_params(trk["id"], {"bpm": bpm, "send_clock": True, "running": True})
        time.sleep(1)
        hubA.export_device(hubA.device_stable_id(trk["id"]), True)
        hubB.enable_netmidi(True)
        hubB.add_peer(peer_ip)
        print("  waiting for mirror to connect…")
        for _ in range(20):
            time.sleep(1)
            sess = _first_session(hubB.netmidi())
            if sess and sess.get("state") == "connected":
                break
        sess = _first_session(hubB.netmidi())
        if not sess or sess.get("state") != "connected":
            print("  MIRROR DID NOT CONNECT (link-local discovery — see task 6). aborting.")
            return
        # Confirm B is actually receiving the master clock before disturbing it.
        hubB.reset_stats()
        time.sleep(4)
        base = hubB.stats().get("metrics", {})
        cj = base.get("clock_tick_jitter") or {}
        rx = base.get("net_midi_rx") or {}
        print(f"  mirrored '{sess.get('name')}' from {sess.get('addr')}")
        print(f"  BASELINE received clock: tick_jitter p99={cj.get('p99','-')} "
              f"max={cj.get('max','-')} ms (n={cj.get('count','-')}); "
              f"rx p99={rx.get('p99','-')} ms")
        if not cj.get("count"):
            print("  (no clock ticks reaching the bus — check the master is running)")
        # Now disturb B with UI actions and watch the received-tick delay.
        run_ops(hubB, settle, out, ops=CROSS_OPS)
    finally:
        print("  teardown: load both to restore")
        hubB.load()
        hubA.load()


def _first_session(nm):
    for hub in (nm or {}).get("hubs", []):
        for s in hub.get("sessions", []):
            return s
    return None


def _write(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
    print(f"  wrote {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, help="hub base URL, e.g. http://10.1.1.2")
    ap.add_argument("--mode", choices=("passive", "ops", "both", "cross"), default="ops")
    ap.add_argument("--peer", default="", help="cross mode: master hub base URL (exports the clock)")
    ap.add_argument("--peer-ip", default="", help="cross mode: master IP the mirror dials (default: host from --peer)")
    ap.add_argument("--duration", type=int, default=120, help="passive seconds")
    ap.add_argument("--poll", type=float, default=5.0, help="passive poll seconds")
    ap.add_argument("--settle", type=float, default=1.5, help="ops settle seconds")
    ap.add_argument("--bpm", type=int, default=140)
    ap.add_argument("--no-scene", action="store_true", help="don't create a MIDI scene")
    ap.add_argument("--out", default="", help="write JSON reports with this prefix")
    args = ap.parse_args()

    hub = Hub(args.target)
    try:
        info = hub.get("/api/system")
        print(f"target {args.target}  version={info.get('version')}  "
              f"host={info.get('hostname')}")
    except urllib.error.URLError as e:
        print(f"cannot reach {args.target}: {e}", file=sys.stderr)
        return 2

    if args.mode == "cross":
        if not args.peer:
            print("--peer <master hub URL> is required for cross mode", file=sys.stderr)
            return 2
        peer_ip = args.peer_ip or urllib.parse.urlparse(args.peer).hostname
        run_cross(hub, args.peer, peer_ip, args.settle, args.out, args.bpm)
        return 0

    scene = []
    if not args.no_scene:
        print("building MIDI scene…")
        scene = build_scene(hub, args.bpm)
    try:
        if args.mode in ("ops", "both"):
            run_ops(hub, args.settle, args.out)
        if args.mode in ("passive", "both"):
            run_passive(hub, args.duration, args.poll, args.out)
    finally:
        teardown_scene(hub, scene)
    return 0


if __name__ == "__main__":
    sys.exit(main())
