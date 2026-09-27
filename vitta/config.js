// Runtime deployment config for the Vitta frontend.
//
// LOCAL DEV: this file is served by serve.py with an empty API base,
// so the frontend falls back to http://localhost:8001 (see app.html).
//
// PRODUCTION: on Cloudflare Pages, replace the empty string below
// with your Render backend URL, e.g. "https://vitta-api.onrender.com".
// The frontend reads this on load and points every fetch at it.
//
// You can also set VITTA_API_BASE at deploy time via Cloudflare Pages
// environment variable + a build step, but for a static site this
// one-line edit + commit is the simplest path.
window.VITTA_API_BASE = window.VITTA_API_BASE || "";
