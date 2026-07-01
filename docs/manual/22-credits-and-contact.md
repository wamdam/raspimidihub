# Credits and Contact

The project, the people behind it, the third-party software it
builds on, and the channels where bugs and ideas land.

## Project

**RaspiMIDIHub** is an open-source software appliance for the
Raspberry Pi. The project is hosted on GitHub at:

`https://github.com/wamdam/raspimidihub`

The default branch is `main`. Releases are tagged `vX.Y.Z` and
attached as GitHub releases with the matching `.deb` files.

## Licence

The application is licensed under the **GNU General Public
License (GPL)**. See the `LICENSE` file in the project repository
for the full text.

## Bundled Third-Party Software

| Component | Licence | Role |
|-----------|---------|------|
| **Preact** | MIT | UI framework for the web SPA |
| **HTM** | Apache 2.0 | Tagged-template HTML for Preact, no build step |

Both are bundled with the application so the appliance can run
fully offline.

The Linux kernel, BlueZ, ALSA, Python, and the rest of the
operating system underneath RaspiMIDIHub have their own licences
(mostly GPL family). The appliance does not modify any of them;
it composes them.

## Issue Tracker

Bug reports, feature requests, and questions:

`https://github.com/wamdam/raspimidihub/issues`

When filing a bug, include:

- The RaspiMIDIHub version (visible in the header version badge
  or in **Settings → Software Versions**).
- The Pi model.
- The MIDI device(s) involved.
- The steps to reproduce.
- The relevant section of `journalctl -u raspimidihub -e` if the
  issue is service-side.

## Other Documents

This manual is the canonical user-facing reference for
RaspiMIDIHub. The project repository carries additional material
for contributors and plugin authors -- the changelog, the
roadmap, the build-from-source notes, and the plugin developer
guide. Browse the repository at the URL above to find them.

## Acknowledgements

RaspiMIDIHub stands on the shoulders of:

- The **Raspberry Pi Foundation** for the affordable hardware
  platform.
- The **ALSA** maintainers for the Linux sequencer that makes
  near-zero-latency MIDI routing possible.
- The **BlueZ** team -- the Bluetooth stack, even with its
  BLE-MIDI quirks, is the foundation on which the in-tree bridge
  is built.
- The **Preact** team for a framework small and fast enough to
  serve as a no-build-step embedded SPA.
- Every contributor and user who has filed an issue, sent a
  patch, or sent feedback. The change log carries their work.

## Contact

The project's primary contact surface is the GitHub repository.
For matters that do not fit a public issue, the repository's
README points to alternative channels current at the time of
writing.

