# REST and SSE API

The web UI is a thin client over a plain HTTP + Server-Sent Events
API. Everything the UI does goes through the same endpoints, so
anything the UI can do can be scripted.

There is **no authentication**: the API is reachable by anyone on the
hub's network (or connected to its access point). The network boundary
*is* the security boundary — treat the hub like any other appliance on
a trusted LAN.

## The API documents itself -- `/docs`

Rather than a hand-maintained endpoint list that drifts from the
software, the running hub serves its own reference:

| Address | What it is |
|---------|------------|
| `http://<hub>/docs` | Human-readable page: every route (method, path, summary) grouped by resource, plus the SSE event vocabulary. |
| `http://<hub>/api/routes.json` | The same data as JSON, for tooling and code generation. |

Both are **generated live from the running build**, so they always
match the firmware you are talking to. `<hub>` is the address from
your title bar / WiFi name, e.g. `raspimidihub-735C.local`.

The JSON shape:

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

A `"match": "prefix"` route matches any path *starting with* the
listed one — these carry an id in the URL (`DELETE
/api/connections/<id>` is listed as the prefix `/api/connections/`).

Two fields are derived live from the handler's own source, so they
never drift:

- **`params`** — a *best-effort* hint of what the handler reads:
  `body` fields (typed where obvious), path `actions`, and whether it
  takes a `path_param`. Not a contract: it unions alternative body
  shapes, does not mark required vs optional, and says nothing about
  the *response*. Absent when a handler reads nothing or delegates
  parsing.
- **`source`** — `file:line` of the handler. Look there when `params`
  isn't enough or you need the response shape.

## The event stream

Live updates arrive over one long-lived SSE connection:

1. Open `GET /api/events`. The first message is `event: connection`
   carrying a `conn_id`.
2. `POST /api/sse/subscribe` with that `conn_id` and the event types
   you want. A connection that subscribes to nothing receives
   nothing — each UI view declares its own interest, which keeps a
   backgrounded phone tab quiet.

The full event vocabulary (names + meaning) is on `/docs` and under
`sse_events` in `/api/routes.json`. Two events — `plugin-param` and
`plugin-display` — are per-instance: delivered only to clients
subscribed to that plugin instance's id.

## Quick example

```bash
# What version am I talking to, and what can it do?
curl http://raspimidihub-735C.local/api/routes.json | jq '.version, (.routes | length)'

# Current hub status
curl http://raspimidihub-735C.local/api/system

# Trigger all-notes-off panic
curl -X POST http://raspimidihub-735C.local/api/panic
```
