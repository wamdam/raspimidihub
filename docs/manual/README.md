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
01-introduction.md                             product, pillars, how to read
02-hardware-and-connectors.md
03-interacting-with-the-web-ui.md              connection, tabs, controls
04-quick-start.md
05-routing-matrix.md
06-filters-and-mappings.md
07-plugins.md
08-controllers.md
09-play-surfaces.md
10-bluetooth-midi.md
11-saving-and-exporting-configs.md             save/load/export + backups
12-settings.md
13-connectivity-and-updates.md
14-appliance-reliability.md
15-setup-examples.md
16-troubleshooting.md
17-technical-reference.md                      architecture, schema, specs
18-credits-and-contact.md
A-appendix-plugin-reference.md
B-appendix-controller-reference.md
C-appendix-midi-mapping-reference.md
D-appendix-keyboard-shortcuts.md
E-appendix-rest-and-sse-api.md
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
