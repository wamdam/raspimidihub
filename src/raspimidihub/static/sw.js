// Minimal service worker for PWA install prompt.
// No offline caching — the app needs a live connection to the Pi.
// Chromium's install criteria require a fetch handler that actually handles
// requests (an empty listener no longer qualifies), so pass through to the
// network and fall back to a 503 when the Pi is unreachable.

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
    e.respondWith(
        fetch(e.request).catch(
            () => new Response('Offline — RaspiMIDIHub not reachable', { status: 503 })
        )
    );
});
