// Minimal service worker for PWA install prompt.
// No offline caching — the app needs a live connection to the Pi.
// Chromium's install criteria require a fetch handler that actually handles
// requests (an empty listener no longer qualifies), so pass through to the
// network and fall back to a 503 when the Pi is unreachable.
//
// /api/ requests (config/backup download navigations included) bypass the
// worker: re-serving a navigation response via respondWith() breaks
// Content-Disposition: attachment downloads on iOS Safari (the download
// never starts), and API traffic gains nothing from the pass-through.

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
    // (a service worker only sees same-origin requests)
    if (new URL(e.request.url).pathname.startsWith('/api/')) {
        return; // let the browser talk to the hub directly
    }
    e.respondWith(
        fetch(e.request).catch(
            () => new Response('Offline — RaspiMIDIHub not reachable', { status: 503 })
        )
    );
});
