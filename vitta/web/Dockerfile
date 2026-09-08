# Vitta web — nginx serving the single-file app.html SPA.
#
# The current frontend is one static file (vitta/app.html) plus a
# handful of static assets. serve.py exists for local dev without
# Docker; this image is the containerized equivalent.

FROM nginx:1.29-alpine

# Build context in docker-compose is `./vitta`, so every path below is
# relative to the vitta/ directory (not to this Dockerfile's directory).

# Drop the default nginx.conf and use ours (single-page routing +
# no-cache during development).
RUN rm -f /etc/nginx/conf.d/default.conf
COPY web/nginx.conf   /etc/nginx/conf.d/vitta.conf

COPY app.html         /usr/share/nginx/html/app.html
COPY vitta-mark.svg   /usr/share/nginx/html/vitta-mark.svg

EXPOSE 5757

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:5757/ >/dev/null || exit 1
