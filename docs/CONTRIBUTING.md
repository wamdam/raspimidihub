# Contributing to RaspiMIDIHub

Thank you for your interest in contributing!

## Development Setup

1. Clone the repository
2. For MIDI engine development, you can use virtual MIDI devices:
   ```bash
   sudo modprobe snd-virmidi
   # Creates virtual MIDI ports for testing without hardware
   ```
3. For web UI development, run the server locally — no Pi needed

## Testing on Real Hardware

Flash Raspberry Pi OS Lite (Bookworm) onto a microSD card and install the `.deb` packages. Connect 2-3 USB MIDI devices and verify routing with `aconnect -l`.

## Submitting Changes

1. Fork the repo and create a feature branch
2. Make your changes
3. Test on a real Pi if possible (especially for read-only FS changes)
4. Submit a pull request with a clear description

## Code Style

- Python: follow PEP 8
- JavaScript: no build step, ES modules, Preact + htm
- Shell scripts: use `shellcheck`

## Reporting Issues

Please include:
- Raspberry Pi model
- OS version (`cat /etc/os-release`)
- USB MIDI devices connected
- Output of `aconnect -l`
- Journal logs: `journalctl -u raspimidihub -b 0`
