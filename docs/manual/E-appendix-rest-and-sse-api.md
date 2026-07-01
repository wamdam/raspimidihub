# REST and SSE API

RaspiMIDIHub's web UI is a thin client over a plain HTTP + Server-Sent
Events API. Everything the UI does -- patching cables, adding plugins,
saving configs, watching MIDI activity -- goes through the same
endpoints, so anything the UI can do can be scripted.

There is **no authentication**: the API is reachable by anyone on the
hub's network (or connected to its access point). The network boundary
*is* the security boundary -- treat the hub like any other appliance on
a trusted LAN.

## The API documents itself -- `/docs`

Rather than a hand-maintained endpoint list that drifts from the
software, the running hub serves its own reference:

| Address | What it is |
|---------|------------|
| `http://<hub>/docs` | Human-readable page: every route (method, path, summary) grouped by resource, plus the SSE event vocabulary. |
| `http://<hub>/api/routes.json` | The same data as JSON, for tooling and code generation. |

Both are **generated live from the running build**, so they always
match the firmware you are actually talking to -- there is no separate
document to fall out of date. `<hub>` is the address from your title
bar / WiFi name, e.g. `raspimidihub-735C.local`.

The JSON shape is deliberately simple:

```json
{
  "version": "5.2.0",
  "routes": [
    {"method": "GET", "path": "/api/system", "match": "exact",
     "summary": "Hub status, stats, versions.",
     "source": "raspimidihub/api.py:475"},
    {"method": "PATCH", "path": "/api/connections/", "match": "prefix",
     "summary": "Update a connection's channel / message-type filter.",
     "params": {"body": ["channel_mask", "msg_types"], "path_param": true},
     "source": "raspimidihub/api.py:1194"}
  ],
  "sse_events": [
    {"event": "midi-activity", "summary": "A MIDI message passed through a monitored port."}
  ]
}
```

A `"match": "prefix"` route matches any path that *starts with* the
listed path -- these are the ones that carry an id in the URL (e.g.
`DELETE /api/connections/<id>` is listed as the prefix
`/api/connections/`).

Two fields are derived live from the handler's own source, so they
never drift:

- **`params`** -- a *best-effort* hint of what the handler reads from
  the request: `body` fields (with an inferred type where obvious),
  path `actions`, and whether it takes a `path_param`. It is not a
  contract: it unions alternative body shapes, does not distinguish
  required from optional, and says nothing about the *response*. Absent
  for endpoints that read nothing or delegate their parsing.
- **`source`** -- `file:line` of the handler. When `params` isn't
  enough, or you need the response shape, this is where to look.

## The event stream

Live updates arrive over one long-lived SSE connection:

1. Open `GET /api/events`. The first message is
   `event: connection` carrying a `conn_id`.
2. `POST /api/sse/subscribe` with that `conn_id` and the set of event
   types you care about. A connection that subscribes to nothing
   receives nothing -- every UI view declares its own interest, which
   is what keeps a backgrounded phone tab quiet.

The full event vocabulary (names + meaning) is listed on `/docs` and in
`/api/routes.json` under `sse_events`. Two events -- `plugin-param` and
`plugin-display` -- are per-instance: they are delivered only to
clients subscribed to that specific plugin instance's id.

## Quick example

```bash
# What version am I talking to, and what can it do?
curl http://raspimidihub-735C.local/api/routes.json | jq '.version, (.routes | length)'

# Current hub status
curl http://raspimidihub-735C.local/api/system

# Trigger all-notes-off panic
curl -X POST http://raspimidihub-735C.local/api/panic
```
