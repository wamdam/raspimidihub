# Web UI internals (contributor notes)

Implementation notes that used to live in the user manual's
architecture chapter. They matter when extending the UI, not when
operating the hub.

## Themes

Every colour is a CSS custom property in
`static/themes/_tokens.css`; each theme is one CSS file in
`static/themes/` overriding tokens in a `[data-theme="<id>"]`
block, missing tokens falling through to the dark default. The
picker reads `static/themes/manifest.json` and writes the chosen id
to `<html data-theme="…">` and local storage; canvas surfaces read
live token values via `lib/theme.js`, so they reskin too. A third
theme is one CSS file plus one manifest row.

## Spectator mirroring

The spectator feature — one browser tab or OBS Browser Source
rendering the same UI as another connected device — lives in its
own module: server side `src/raspimidihub/spectator.py` (mirror
state, watcher map, `spectator-state` fan-out filter, the
`/api/spectator/*` routes), client side `static/lib/spectator/`.

New surfaces mirror correctly via two opt-in patterns: popovers
call `useSharedUiState(key, init)` in place of `useState`, and
scrollable containers carry `data-spectator-scroll="<key>"`.
