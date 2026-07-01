# Agent instructions

This project's agent/coding instructions live in **`CLAUDE.md`** at the
repository root. Read that file — everything there applies regardless of
which agent or tool you are.

## Talking to a running hub — discover the API, don't grep for it

A running RaspiMIDIHub serves its own live API reference. To learn what
endpoints exist, **fetch the manifest from the device** rather than
reading `src/raspimidihub/api.py`:

- `http://<hub>/api/routes.json` — every route as JSON: `method`, `path`,
  `match` (exact vs prefix), `summary`, and (for handlers that read one)
  `params` (`body` fields with inferred types, path `actions`,
  `path_param`) and `source` (`raspimidihub/<file>.py:<line>`). Plus the
  SSE event vocabulary. Generated live from the running build, so it
  always matches the firmware you're actually talking to.
- `http://<hub>/docs` — the same data as a human-readable page.

There is no authentication (LAN/AP is the security boundary), so a bare
`curl http://<hub>/api/routes.json` works. `<hub>` is e.g.
`raspimidihub-735C.local` or an IP.

**Two-tier workflow — read the manifest first, code second.** The
manifest answers the common case (which endpoint, what to send). The
`params` are **best-effort** (parsed from handler source): they union
alternative body shapes, don't mark required-vs-optional, say nothing
about the *response* shape, and are empty for handlers that delegate.
When they're not enough — or you need the response — open the route's
`source` `file:line` directly instead of grepping. Don't re-derive the
endpoint list by reading `api.py`; that's what the manifest is for.

**Keeping it in sync (applies to every future coding session).** The
manifest is built by `WebServer.api_manifest()` in
`src/raspimidihub/web.py`. `params` and `source` are derived
automatically from the live code (`_extract_params` / `_source_ref`) —
**no maintenance**. Only two things need a human touch, in the same
commit as the change:
- Add a `@server.route(...)` → give it a `summary="…"`.
- Add a `send_sse("…")` → add its name to the `SSE_EVENTS` registry in
  `web.py` (an undeclared event is warn-logged at emit time).
Both surface on `/docs` automatically once added.
