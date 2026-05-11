# Pandoc templates

LaTeX include files and pandoc template overrides for the manual
PDF build.

## Files

- `header.tex` -- pulled in via `--include-in-header` by
  `make manual`. Holds page-style (fancyhdr), code-block wrapping
  (fvextra), table layout (longtable / booktabs), and chapter-
  heading spacing tweaks.

## Adding a full pandoc template

The build currently uses pandoc's default LaTeX template with the
header tweaks above. To switch to a fully custom template:

1. Extract the default with `pandoc -D latex > templates/manual.latex`.
2. Edit the resulting file.
3. Pass `--template=templates/manual.latex` from the
   `make manual` target instead of `--include-in-header=...`.

The default template is ~700 lines and changes between pandoc
versions; pinning a fork means owning the merge work on future
pandoc upgrades. Prefer the header-include approach unless the
customisation cannot be expressed that way (custom cover page,
different chapter layout, etc.).
