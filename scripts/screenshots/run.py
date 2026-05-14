"""Generate documentation screenshots via Playwright.

Connects to a running RaspiMIDIHub web UI (default http://10.1.1.2),
strips the live plugin set, recreates a curated demo set, walks a
list of scenes, and writes PNGs into docs/screenshots/.

The demo set is NEVER saved — running this script does NOT mutate
the on-disk config. After the run, the user (or a CI step) clicks
"Load Config" in Settings, or hits POST /api/config/load, to restore
their real plugin instances. The bottom-nav Routing asterisk should
be lit by the time this script ends, signalling the dirty state.

Usage:
    python scripts/screenshots/run.py                     # default target
    python scripts/screenshots/run.py --target=http://10.1.1.2
    python scripts/screenshots/run.py --headed            # see the browser
    python scripts/screenshots/run.py --filter=plugin     # only matching scenes
    python scripts/screenshots/run.py --skip-setup        # use whatever is live

Dependencies:
    pip install playwright
    playwright install chromium
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Phone-ish viewport — matches what most users will look at the
# screenshots on. 480 px wide is generous enough that controller
# panels render their full grid without cramming.
VIEWPORT = {"width": 480, "height": 960}

# Alternative viewport presets selectable via --viewport=<name>.
# 'phone' targets a typical small Android (e.g. Pixel 5 / Galaxy S
# class) at 360 CSS px wide with DPR=3 — what a user holding a
# pocket-sized device actually sees. Used for tuning small-screen
# layout, not for shipping doc screenshots.
VIEWPORT_PRESETS = {
    "desktop": {"viewport": {"width": 480, "height": 960}, "dpr": 2},
    "phone":   {"viewport": {"width": 360, "height": 640}, "dpr": 3},
}

# The curated plugin set we recreate before screenshotting. Order
# determines (alphabetical) where instances land in the matrix.
DEMO_PLUGINS = [
    ("arpeggiator", "Arpeggiator"),
    ("cc_lfo", "CC LFO"),
    ("cc_smoother", "CC Smoother"),
    ("chord_generator", "Chord Generator"),
    ("clock_divider", "Clock Divider"),
    ("hold", "Hold"),
    ("master_clock", "Master Clock"),
    ("midi_delay", "MIDI Delay"),
    ("note_splitter", "Note Splitter"),
    ("note_transpose", "Note Transpose"),
    ("panic", "Panic"),
    ("pitch_cc", "Pitch CC"),
    ("scale_remapper", "Scale Remapper"),
    ("sysex_sender", "SysEx Sender"),
    ("tracker", "Tracker"),
    ("velocity_curve", "Velocity Curve"),
    ("velocity_equalizer", "Velocity Equalizer"),
    ("controller_mixer_8", "Mixer 8"),
    ("controller_fx_6", "FX 6"),
    ("controller_performance_16", "Performance 16"),
    ("controller_xy_4", "XY 4"),
]


def api_request(target: str, method: str, path: str, body=None) -> bytes:
    url = f"{target}/api{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read()


def setup_demo_plugins(target: str) -> dict[str, dict]:
    """Strip every live plugin instance, recreate the demo set.
    Returns {plugin_type: instance_data} so scenes can resolve client_ids.
    """
    print(f"  setup: stripping live plugins on {target}")
    instances = json.loads(api_request(target, "GET", "/plugins/instances"))
    for inst in instances:
        api_request(target, "DELETE", f"/plugins/instances/{inst['id']}")
    print(f"  setup: deleted {len(instances)} instance(s)")

    print(f"  setup: creating {len(DEMO_PLUGINS)} demo plugin(s)")
    created: dict[str, dict] = {}
    for plugin_type, name in DEMO_PLUGINS:
        body = {"type": plugin_type, "name": name}
        try:
            resp = json.loads(api_request(target, "POST", "/plugins/instances", body))
            created[plugin_type] = resp
        except urllib.error.HTTPError as e:
            print(f"  setup: {plugin_type} create failed ({e}); skipping")
    # Brief settle so the matrix's connection-changed SSE finishes,
    # plugin clients show up in scan, etc. Without this, the first
    # screenshot of /routing can race the device list.
    time.sleep(1.0)
    return created


def resolve_client_id(target: str, instance: dict) -> int | None:
    """Look up an instance's ALSA client_id via /api/devices.
    Plugin devices appear with stable_id = "plugin-<instance_id>"."""
    devices = json.loads(api_request(target, "GET", "/devices"))
    sid = "plugin-" + instance["id"]
    for d in devices:
        if d.get("stable_id") == sid:
            return d["client_id"]
    return None


def find_hardware_client_id(target: str) -> int | None:
    """First non-plugin device's client_id, or None if only plugins exist."""
    devices = json.loads(api_request(target, "GET", "/devices"))
    for d in devices:
        sid = d.get("stable_id") or ""
        if sid and not sid.startswith("plugin-") and d.get("online", True):
            return d["client_id"]
    return None


def create_demo_connection(target: str, src_inst: dict, dst_inst: dict) -> None:
    """Wire src plugin's OUT (port 1) to dst plugin's IN (port 0).
    Used so the filter-panel / mapping-form scenes have a real cell
    to click."""
    src_cid = resolve_client_id(target, src_inst)
    dst_cid = resolve_client_id(target, dst_inst)
    if src_cid is None or dst_cid is None:
        print("  setup: cannot wire demo connection, plugins unresolved")
        return
    body = {"src_client": src_cid, "src_port": 1,
            "dst_client": dst_cid, "dst_port": 0}
    try:
        api_request(target, "POST", "/connections", body)
        print(f"  setup: wired {src_cid}:1 → {dst_cid}:0 for filter scenes")
    except urllib.error.HTTPError as e:
        print(f"  setup: connection create failed ({e}); skipping")


def _open_filter_panel(page) -> None:
    """Click the first lit cell in the matrix and pick 'Edit' from the
    context menu, leaving the FilterPanel overlay open."""
    page.locator(".matrix .cb.on").first.click()
    page.locator('[data-testid="menu-item-edit"]').click()
    page.wait_for_selector(".filter-panel", timeout=3000)
    time.sleep(0.4)


def _open_mapping_form_note(page) -> None:
    _open_filter_panel(page)
    # FilterPanel's mapping card has exactly one primary button: + Add Mapping.
    page.locator(".filter-panel .btn-primary").first.click()
    page.wait_for_selector(".mapping-panel", timeout=3000)
    time.sleep(0.4)


def _open_mapping_form_cc(page) -> None:
    _open_mapping_form_note(page)
    # Click the "CC → CC" radio option (uses U+2192 RIGHTWARDS ARROW).
    page.locator(".mapping-panel .radio-opt", has_text="CC → CC").click()
    time.sleep(0.3)


def build_scenes(target: str, instances: dict[str, dict]) -> list[dict]:
    """Materialise the scene list. URL paths reference the running
    Pi; client_ids are resolved per-scene from the demo instances we
    just created."""
    scenes: list[dict] = [
        {"name": "01-routing", "path": "/routing"},
        {"name": "04-settings", "path": "/settings"},
    ]
    # Controller play-surface scenes. One per controller template,
    # path resolves to the instance's id; the file name is the
    # historical short form so README / website refs still work.
    controller_play_scenes = {
        "controller_mixer_8": "controller-mixer-8",
        "controller_fx_6": "controller-fx-6",
        "controller_performance_16": "controller-performance-16",
        "controller_xy_4": "controller-xy-4",
    }
    for plugin_type, scene_name in controller_play_scenes.items():
        inst = instances.get(plugin_type)
        if inst is None:
            continue
        scenes.append({"name": scene_name,
                       "path": f"/controller/{inst['id']}"})
    # Tracker play-surface lives under /play.
    if (tracker := instances.get("tracker")) is not None:
        scenes.append({"name": "tracker", "path": f"/play/{tracker['id']}"})
    # Arpeggiator play-surface — same /play tab as the Tracker, since
    # the Arp is also SURFACE_KIND="play". Path is the instance id.
    if (arp := instances.get("arpeggiator")) is not None:
        scenes.append({"name": "arpeggiator-play", "path": f"/play/{arp['id']}"})
    # 05/07/08 need a real connection in the matrix so there is an
    # 'on' cell to click. We wire a transient one between two demo
    # plugins; setup_demo_plugins already wiped the live state and
    # this never gets saved (Save Config is not pressed).
    if "note_transpose" in instances and "velocity_curve" in instances:
        create_demo_connection(target,
                               instances["note_transpose"],
                               instances["velocity_curve"])
        time.sleep(0.5)
        scenes.append({"name": "05-filter-panel", "path": "/routing",
                       "setup": _open_filter_panel})
        scenes.append({"name": "07-mapping-note-to-cc", "path": "/routing",
                       "setup": _open_mapping_form_note})
        scenes.append({"name": "08-mapping-cc-to-cc", "path": "/routing",
                       "setup": _open_mapping_form_cc})

    # 06 needs a hardware (non-plugin) device. If the Pi has nothing
    # plugged in we silently skip — the rest of the run still works.
    hw_cid = find_hardware_client_id(target)
    if hw_cid is not None:
        scenes.append({"name": "06-device-detail",
                       "path": f"/routing/d/{hw_cid}"})
    # Per-plugin device-detail config panels. Numbering matches the
    # historical naming under docs/screenshots/.
    plugin_scene_names = {
        "arpeggiator": "09-plugin-arpeggiator",
        "cc_lfo": "10-plugin-cc-lfo",
        "cc_smoother": "11-plugin-cc-smoother",
        "chord_generator": "12-plugin-chord-generator",
        "master_clock": "13-plugin-master-clock",
        "midi_delay": "14-plugin-midi-delay",
        "note_splitter": "15-plugin-note-splitter",
        "note_transpose": "16-plugin-note-transpose",
        "panic": "17-plugin-panic",
        "pitch_cc": "29-plugin-pitch-cc",
        "scale_remapper": "18-plugin-scale-remapper",
        "velocity_curve": "19-plugin-velocity-curve",
        "velocity_equalizer": "20-plugin-velocity-equalizer",
        "clock_divider": "21-plugin-clock-divider",
        "hold": "22-plugin-hold",
        "sysex_sender": "27-plugin-sysex-sender",
        "tracker": "28-plugin-tracker-config",
        "controller_mixer_8": "23-controller-mixer-8-config",
        "controller_xy_4": "24-controller-xy-4-config",
        "controller_fx_6": "25-controller-fx-6-config",
        "controller_performance_16": "26-controller-performance-16-config",
    }
    for plugin_type, scene_name in plugin_scene_names.items():
        inst = instances.get(plugin_type)
        if inst is None:
            continue
        client_id = resolve_client_id(target, inst)
        if client_id is None:
            print(f"  scenes: no client_id for {plugin_type}, skipping")
            continue
        scenes.append({"name": scene_name,
                        "path": f"/routing/d/{client_id}"})
    return scenes


def screenshot_scenes(target: str, scenes: list[dict], out_dir: Path,
                      headless: bool, preset: str = "desktop") -> None:
    from playwright.sync_api import sync_playwright

    cfg = VIEWPORT_PRESETS[preset]
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport=cfg["viewport"],
                                  device_scale_factor=cfg["dpr"])
        # On the phone preset, pre-set the layout-density preference to
        # 'small' in localStorage so every page renders with the
        # tightened chrome from the first paint. add_init_script runs
        # before page scripts so app boot reads the flag and applies
        # the class without a flash of the default-spaced UI.
        if preset == "phone":
            ctx.add_init_script(
                "try { localStorage.setItem('raspimidihub:layoutDensity', 'small'); }"
                " catch (e) {}"
            )
        page = ctx.new_page()
        for scene in scenes:
            url = target + scene["path"]
            # `networkidle` would block forever — the app keeps an SSE
            # stream open. `load` fires after the entry script runs;
            # then we wait for .bottom-nav (proves the SPA hydrated)
            # and add a brief settle so SSE-driven content (device
            # list, plugin params) finishes painting.
            page.goto(url, wait_until="load")
            try:
                page.wait_for_selector(".bottom-nav", timeout=5000)
            except Exception:
                pass
            time.sleep(0.8)
            setup = scene.get("setup")
            if setup is not None:
                try:
                    setup(page)
                except Exception as e:
                    print(f"  ! {scene['name']}: setup failed ({e}); skipping")
                    continue
            out_path = out_dir / f"{scene['name']}.png"
            page.screenshot(path=str(out_path), full_page=False)
            print(f"  → {out_path.name}")
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://10.1.1.2",
                         help="RaspiMIDIHub web UI base URL")
    parser.add_argument("--out", default="docs/screenshots",
                         help="Output directory for PNGs")
    parser.add_argument("--headed", action="store_true",
                         help="Show the browser window (default headless)")
    parser.add_argument("--filter", default=None,
                         help="Only run scenes whose name contains this substring")
    parser.add_argument("--skip-setup", action="store_true",
                         help="Use whatever plugins are currently live (no demo set)")
    parser.add_argument("--viewport", default="desktop",
                         choices=sorted(VIEWPORT_PRESETS),
                         help="Viewport preset (default desktop = 480x960 @ DPR2; "
                              "phone = 360x640 @ DPR3, matches a typical small Android)")
    args = parser.parse_args()

    target = args.target.rstrip("/")
    out_dir = Path(args.out)

    # Connectivity sanity check.
    try:
        api_request(target, "GET", "/system")
    except (urllib.error.URLError, OSError) as e:
        print(f"error: cannot reach {target}/api/system: {e}", file=sys.stderr)
        return 2

    if args.skip_setup:
        # Resolve scenes by querying live instances.
        live = json.loads(api_request(target, "GET", "/plugins/instances"))
        instances = {i["type"]: i for i in live}
    else:
        instances = setup_demo_plugins(target)

    scenes = build_scenes(target, instances)
    if args.filter:
        scenes = [s for s in scenes if args.filter in s["name"]]
    if not scenes:
        print("error: no scenes matched", file=sys.stderr)
        return 1

    cfg = VIEWPORT_PRESETS[args.viewport]
    print(f"taking {len(scenes)} screenshot(s) → {out_dir} "
          f"({args.viewport}: {cfg['viewport']['width']}x{cfg['viewport']['height']} "
          f"@ DPR{cfg['dpr']})")
    screenshot_scenes(target, scenes, out_dir, headless=not args.headed,
                      preset=args.viewport)

    print()
    print("done. The Pi is now running the demo plugin set.")
    print("Click 'Load Config' in Settings (or POST /api/config/load) "
          "to restore your saved state.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
