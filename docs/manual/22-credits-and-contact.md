# Credits and Contact

The project, the third-party software it builds on, and the channels
where bugs and ideas land.

## Project

**RaspiMIDIHub** is an open-source software appliance for the
Raspberry Pi, hosted on GitHub:

`https://github.com/wamdam/raspimidihub`

The default branch is `main`. Releases are tagged `vX.Y.Z` and
published as GitHub releases with the matching `.deb` files.

## Licence

The application is licensed under the **GNU General Public License
(GPL)**. See the `LICENSE` file in the repository for the full text.

## Bundled Third-Party Software

| Component | Licence | Role |
|-----------|---------|------|
| **Preact** | MIT | UI framework for the web SPA |
| **HTM** | Apache 2.0 | Tagged-template HTML for Preact, no build step |

Both are bundled so the appliance runs fully offline. The Linux
kernel, BlueZ, ALSA, Python, and the rest of the operating system
have their own licences (mostly GPL family); the appliance composes
them unmodified.

## Issue Tracker

Bug reports, feature requests, and questions:

`https://github.com/wamdam/raspimidihub/issues`

When filing a bug, include:

- The RaspiMIDIHub version (header badge or **Settings → Software
  Versions**).
- The Pi model.
- The MIDI device(s) involved.
- The steps to reproduce.
- The relevant section of `journalctl -u raspimidihub -e` if the
  issue is service-side.

## Other Documents

This manual is the canonical user-facing reference. The repository
carries the material for contributors and plugin authors -- the
changelog, the roadmap, the build-from-source notes, and the plugin
developer guide.

## Acknowledgements

RaspiMIDIHub stands on the shoulders of:

- The **Raspberry Pi Foundation** for the affordable hardware
  platform.
- The **ALSA** maintainers for the Linux sequencer behind
  near-zero-latency MIDI routing.
- The **BlueZ** team for the Bluetooth stack the BLE-MIDI bridge is
  built on.
- The **Preact** team for a framework small and fast enough to serve
  as a no-build-step embedded SPA.
- Every contributor and user who has filed an issue, sent a patch,
  or sent feedback.

## Contact

The GitHub repository is the project's primary contact surface. For
matters that do not fit a public issue, the repository's README
points to alternative channels.
