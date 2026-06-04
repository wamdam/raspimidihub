# RaspiMIDIHub User Manual — Source

This directory contains the source for the RaspiMIDIHub User Manual.
Each chapter lives in its own Markdown file. The whole set is meant to
be rendered to `raspimidihub-manual.pdf` with pandoc.

**Documented release:** auto-derived at build time. `make manual`
reads the Makefile's `VERSION` and the top-most date entry in
`CHANGELOG.txt`, then stamps both onto the cover page via the
generated `templates/version.tex` (gitignored). Do not hand-edit
versions in `metadata.yaml` or `templates/header.tex` — the build
overrides them.

## Layout

Files are ordered by filename prefix. Lowercase numeric prefixes mark
the body chapters; uppercase letters mark the appendices.

```
metadata.yaml                                  pandoc title block
00-frontmatter.md                              copyright, conventions
01-introduction.md
02-the-raspimidihub.md
03-hardware-and-connectors.md
04-system-architecture.md
05-configuration-and-data-structure.md
06-interacting-with-the-web-ui.md
07-quick-start.md
08-ui-controls.md
09-routing-matrix.md
10-filters-and-mappings.md
11-plugins.md
12-controllers.md
13-play-surfaces.md
14-bluetooth-midi.md
15-saving-and-exporting-configs.md
16-settings.md
17-connectivity-and-updates.md
18-appliance-reliability.md
19-setup-examples.md
20-troubleshooting.md
21-technical-information.md
22-credits-and-contact.md
A-appendix-plugin-reference.md
B-appendix-controller-reference.md
C-appendix-midi-mapping-reference.md
D-appendix-keyboard-shortcuts.md
```

Each chapter file starts with a `# N. Title` heading and is currently
a brief overview of the topics it will cover. Subsections will be
filled in chapter-by-chapter in subsequent passes.

## Building the PDF

```bash
cd docs/manual
pandoc metadata.yaml *.md \
  --pdf-engine=xelatex \
  --toc --toc-depth=3 \
  --number-sections \
  --resource-path=.:../screenshots \
  -o raspimidihub-manual.pdf
```

Screenshots referenced from the chapters live in `docs/screenshots/`
(one directory up). Reference them as `../screenshots/<file>.png` from
inside a chapter so pandoc and the GitHub web-renderer both resolve
them.

## Screenshots

The chapters re-use the existing UI screenshots under
`docs/screenshots/`. Chapters that need a screenshot the project does
not have yet flag it in a **Screenshots needed** subsection at the
bottom of the file, with the proposed filename and what the shot
should show. New screenshots are captured with `make screenshots`
(see `pyproject.toml` for the playwright dependency) and committed
into `docs/screenshots/`.

## Conventions

Conventions used throughout the manual (key/control formatting,
admonitions, etc.) live in `00-frontmatter.md` so the front matter
serves as the single source of truth for the typographic rules.
