"""OS captive-portal probe endpoints.

Moved verbatim from the old api.py: the landing-page constants at
module level, the probe routes registered via register_captive().
"""

import logging
import socket

from ..web import Request, Response
from ._ctx import ApiContext

log = logging.getLogger(__name__)


# --- Captive portal landing -----------------------------------------------
# OS captive-portal probes (Android / iOS / Firefox) all hit known
# endpoints. We serve the same tiny landing for every one — pure HTML,
# no JS, no SSE. A captive webview that fetches this stays inert; the
# user taps the link to open the SPA in their normal browser, where
# SSE legitimately belongs.
#
# Microsoft endpoints (connecttest.txt / ncsi.txt) keep their original
# success responses because Windows' NCSI uses them for "do I have
# internet" without ever showing a captive browser — there's nothing
# to land on, so changing them just risks breaking Windows.

_CAPTIVE_LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RaspiMIDIHub</title>
<style>
*{box-sizing:border-box}
body{margin:0;padding:24px;min-height:100vh;
     font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
     background:#1a1a2e;color:#eaeaea;
     display:flex;flex-direction:column;align-items:center;justify-content:center;
     text-align:center}
h1{font-size:1.6rem;font-weight:600;margin:0 0 8px}
.tag{color:#9aa0aa;font-size:0.9rem;margin:0 0 24px}
.lead{font-size:1rem;margin:0 0 14px}
.addr{display:flex;align-items:center;gap:8px;margin:8px 0;
      background:#16213e;border-radius:10px;padding:10px 12px;max-width:100%}
.addr code{font-size:1rem;color:#eaeaea;word-break:break-all}
.copy{flex:none;border:0;border-radius:8px;background:#e94560;color:#fff;
      font-size:1rem;padding:8px 12px;cursor:pointer}
.copy:active{transform:scale(0.95)}
.foot{color:#6a6f78;font-size:0.78rem;margin-top:24px;line-height:1.4}
</style>
</head>
<body>
<h1>RaspiMIDIHub</h1>
<p class="tag">Connected to the access point.</p>
<p class="lead">Open one of these in your browser:</p>
<div class="addr"><code id="a1">http://192.168.4.1/</code><button class="copy" onclick="cp('a1',this)">Copy</button></div>
<div class="addr"><code id="a2">http://__MDNS__.local/</code><button class="copy" onclick="cp('a2',this)">Copy</button></div>
<p class="foot">Paste an address into your browser's address bar.<br>
The name works from any device on this network; the IP works if .local isn't supported.</p>
<script>
function cp(id,b){var el=document.getElementById(id),t=el.textContent.trim(),ok=false;
try{var r=document.createRange();r.selectNodeContents(el);var s=getSelection();
s.removeAllRanges();s.addRange(r);ok=document.execCommand('copy');s.removeAllRanges();}catch(e){}
if(!ok&&navigator.clipboard){navigator.clipboard.writeText(t);ok=true;}
b.textContent=ok?'Copied':'Copy';setTimeout(function(){b.textContent='Copy';},1200);}
</script>
</body>
</html>
"""

_CAPTIVE_LANDING_PATHS = (
    "/generate_204",                   # Android
    "/hotspot-detect.html",            # iOS / macOS
    "/library/test/success.html",      # iOS variant
    "/redirect",                        # Firefox
    "/canonical.html",                  # Firefox
)
# Microsoft NCSI: keep the original success body, no captive needed.
_CAPTIVE_PASSTHROUGH = {
    "/connecttest.txt": "Microsoft Connect Test",
    "/ncsi.txt": "Microsoft NCSI",
}




def register_captive(ctx: ApiContext) -> None:
    """Register the OS captive-portal probe routes."""
    server = ctx.server

    # Captive-portal probe access log. The phone's OS hits one of these
    # endpoints periodically to decide whether the network has internet;
    # if the response is slow or missing, the OS marks the network "no
    # internet" and after a few failures de-associates. This log makes
    # phone-disconnect post-mortem possible: grep for "captive:" and
    # the time delta + client IP correlate against hostapd's own log.
    import time as _t_cap

    def _captive_handler(path: str, body: str, status: int, content_type: str):
        async def handler(req: Request) -> Response:
            t0 = _t_cap.monotonic()
            if status == 204:
                resp = Response(status=204)
            elif content_type == "html":
                resp = Response.html(body)
            else:
                resp = Response.text(body)
            log.info("captive: %s %s %d %.1fms",
                     req.client_addr or "?", path, status,
                     (_t_cap.monotonic() - t0) * 1000.0)
            return resp
        return handler

    # OS probes that should trigger the captive flow → serve the tiny
    # landing with a link to the SPA. No JS/SSE here.
    # Substitute the hub's actual mDNS name (raspimidihub-<id>) into the
    # landing so users learn the new address on first connect.
    _captive_html = _CAPTIVE_LANDING_HTML.replace("__MDNS__", socket.gethostname())
    for p in _CAPTIVE_LANDING_PATHS:
        server.route("GET", p, summary="OS captive-portal probe: serves the "
                     "tiny landing page linking to the app.")(_captive_handler(
                         p, _captive_html, 200, "html"))
    # Windows NCSI: keep the legacy success bodies so it stays out of
    # the captive flow entirely (it has no captive UI to land on).
    for p, body in _CAPTIVE_PASSTHROUGH.items():
        server.route("GET", p, summary="Windows NCSI probe: returns the legacy "
                     "success body (stays out of the captive flow).")(
                         _captive_handler(p, body, 200, "text"))

