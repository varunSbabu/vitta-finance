// Runtime API base for the Vitta frontend.
//
// Local dev (localhost): leave empty, so app.html falls back to
// http://localhost:8001.
// Production: use this site's own origin. vercel.json proxies /api/* to
// the Render backend, which keeps the session cookie first-party.
(function () {
  var h = window.location.hostname;
  var isLocal = h === "localhost" || h === "127.0.0.1" || window.location.protocol === "file:";
  window.VITTA_API_BASE = window.VITTA_API_BASE || (isLocal ? "" : window.location.origin);
})();
