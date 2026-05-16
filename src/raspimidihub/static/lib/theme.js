/* Theme runtime. Two responsibilities:
 *
 * 1. `token(name)` — read a CSS custom property from :root. Lets
 *    canvas surfaces (Display scope, CurveEditor, dropbtn ring
 *    segments) pick up the same colour tokens that CSS rules use,
 *    so when the active theme changes, the canvases follow.
 *
 *    SVG inside lit-html template literals can use tokens directly
 *    via inline style (`style="fill: var(--token)"`); only canvas
 *    paint and JS-side colour constants need this helper.
 *
 *    The CSSStyleDeclaration returned by getComputedStyle() is
 *    live, so caching it once is safe — every read picks up the
 *    current value. We don't memoise the resolved string itself:
 *    if the theme switches at runtime, a stale cache would paint
 *    the wrong colour on the next canvas frame.
 *
 * 2. Theme switching — `getTheme()`, `setTheme(id)`, `listThemes()`.
 *    `setTheme` writes `<html data-theme>`, persists in localStorage,
 *    and updates the `<meta name="theme-color">` tag so the PWA
 *    status bar follows. `listThemes` returns the manifest entries
 *    (cached after first load) so the Settings page can populate a
 *    dropdown without hardcoding the list.
 *
 *    The first-paint theme is applied by an inline <script> in
 *    index.html that runs before this module imports — keeps the
 *    page from flashing the default theme before localStorage is
 *    read. See index.html for that bootstrap.
 */

const STORAGE_KEY = 'raspimidihub.theme';

let _rootStyle = null;

function rootStyle() {
    if (_rootStyle === null) {
        _rootStyle = getComputedStyle(document.documentElement);
    }
    return _rootStyle;
}

export function token(name) {
    const key = name.startsWith('--') ? name : '--' + name;
    return rootStyle().getPropertyValue(key).trim();
}


// --- Theme manifest -------------------------------------------------

let _manifestPromise = null;

export function listThemes() {
    if (_manifestPromise === null) {
        _manifestPromise = fetch('/themes/manifest.json')
            .then(r => r.json())
            .catch(() => ({
                // Fallback if the manifest fetch fails — the inline
                // bootstrap in index.html will still have applied a
                // sane default, so this is purely so the Settings
                // dropdown doesn't disappear if a static-server hiccup
                // hits at the moment Settings is first opened.
                themes: [{ id: 'dark', name: 'Dark', metaColor: '#1a1a2e' }],
                default: 'dark',
            }));
    }
    return _manifestPromise;
}


// --- Active theme ---------------------------------------------------

export function getTheme() {
    return document.documentElement.getAttribute('data-theme') || 'dark';
}

export function setTheme(id) {
    document.documentElement.setAttribute('data-theme', id);
    try {
        localStorage.setItem(STORAGE_KEY, id);
    } catch (e) {
        // localStorage can throw in private-browsing modes — fail
        // silently. The theme still applies for the current session.
    }
    // Update PWA status-bar colour to match.
    listThemes().then(m => {
        const entry = (m.themes || []).find(t => t.id === id);
        if (!entry || !entry.metaColor) return;
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.setAttribute('content', entry.metaColor);
    });
}
