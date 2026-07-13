# Running RaspiMIDIHub off a Pi (dev / demo)

You can run the whole hub on an ordinary Linux machine — a laptop, a
dev box, a VM — and click through the real web UI in a browser. Unlike a
Raspberry Pi you have no physical MIDI ports, so we borrow the kernel's
**`snd-virmidi`** module: it creates virtual ALSA MIDI ports that show up
in the routing matrix exactly like hardware. You can wire plugins,
trackers and play surfaces between them and route into a software synth —
real routing, real notes, real sound.

## Quick start

```sh
make demo                  # -> http://localhost:8080
make demo DEMO_PORT=8090   # if 8080 is taken
```

`make demo` loads `snd-virmidi` (via `sudo` — it may prompt for your
password), bootstraps `.venv` if needed, and launches the hub against the
real ALSA sequencer. Open the printed URL; the virtual ports appear as
devices in the matrix. Ctrl-C to stop.

Knobs:

- `DEMO_PORT` — web port (default 8080).
- `DEMO_STATE_DIR` — where Save/autosave/backups are written (default
  `~/.raspimidihub-demo`).
- `VIRMIDI_DEVS` — how many virtual port pairs to create (default 4).

## Requirements

- Python 3.9+ and `libasound2` (`sudo apt install libasound2`).
- The `snd-virmidi` kernel module (ships with standard Linux; `make demo`
  loads it). If your kernel lacks it the matrix simply comes up empty —
  everything else still works.

The app is pure Python and runs straight from the source tree; there is
no package to install.

## By hand (what `make demo` does)

```sh
sudo modprobe snd-virmidi midi_devs=4      # once per boot
RASPIMIDIHUB_STATE_DIR="$HOME/.raspimidihub-demo" \
RASPIMIDIHUB_PORT=8080 \
PYTHONPATH=src:plugins \
  python3 -m raspimidihub
```

Two environment variables make it appliance-friendly off a Pi; both are
unset on the real appliance, where behaviour is unchanged:

- `RASPIMIDIHUB_STATE_DIR` relocates persistence to a normal directory
  and skips the read-only-boot-partition remount, so Save/Load/Backup
  work. Omit it and saves fail soft (the UI still runs).
- `RASPIMIDIHUB_PORT` overrides the listen port.

Off a Pi you'll also see a few harmless startup warnings for the
hardware-only features (WiFi AP, Bluetooth, no activity LED). They are
logged and skipped; the hub runs fine.

## Notes

- Run as a normal user (not root); the hub then serves on 8080 and skips
  the root-only appliance setup (WiFi, the eth0 NetworkManager profile).
- `snd-virmidi` ports are bidirectional loopbacks — routing MIDI into one
  and reading it from its partner is a good way to see events flow. Point
  a soft synth (e.g. via `aconnect`) at a hub output port to hear it.
