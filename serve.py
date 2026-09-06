import http.server, socketserver
class H(http.server.SimpleHTTPRequestHandler):
    def guess_type(self, path):
        mime = super().guess_type(path)
        if isinstance(mime, str) and mime.startswith('text/'):
            return mime + '; charset=utf-8'
        return mime
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        super().end_headers()
PORT = 5757
with socketserver.TCPServer(("", PORT), H) as httpd:
    print(f"Serving http://localhost:{PORT}/ with UTF-8")
    httpd.serve_forever()
