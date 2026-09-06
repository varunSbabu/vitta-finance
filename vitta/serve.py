"""Static server for app.html, with UTF-8 so ₹ / → / — render correctly.

Python's SimpleHTTPRequestHandler omits the charset in Content-Type, which
makes the browser fall back to latin-1 and mangle the rupee sign. It also
serves from the process CWD, so this anchors to the script's own directory
to stay correct regardless of where it's launched from.
"""
import http.server
import os
import socketserver

os.chdir(os.path.dirname(os.path.abspath(__file__)))


class H(http.server.SimpleHTTPRequestHandler):
    def guess_type(self, path):
        mime = super().guess_type(path)
        if isinstance(mime, str) and mime.startswith('text/'):
            return mime + '; charset=utf-8'
        return mime

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        super().end_headers()

    def do_GET(self):
        # Serve the SPA at / so the preview URL needs no /app.html suffix.
        if self.path in ('/', '/index.html'):
            self.path = '/app.html'
        return super().do_GET()


PORT = 5757
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("", PORT), H) as httpd:
    print(f"Serving http://localhost:{PORT}/ (app.html) with UTF-8")
    httpd.serve_forever()
