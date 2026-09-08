# Vitta API — FastAPI on uvicorn.
#
# Build from the repo root so vitta/backend/ is the build context:
#   docker build -f vitta/backend/Dockerfile -t vitta-api vitta/backend
#
# Compose does that for you (see ../../docker-compose.yml).

FROM python:3.12-slim AS base

# System deps: pdfplumber pulls in a C extension chain (pdfminer.six +
# cryptography wheels), and curl is used by the healthcheck below. Keep
# the runtime image lean — no build-essential, no dev headers.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl \
      libgl1 \
      libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# Non-root user for the process. Numeric UID 10001 matches nothing on
# Debian's base image, so a bind-mount from the host won't accidentally
# be writable by, say, the host's www-data.
RUN groupadd --system --gid 10001 vitta \
 && useradd  --system --uid 10001 --gid vitta --home /app --shell /usr/sbin/nologin vitta

WORKDIR /app

# Deps first, code second — a code-only edit reuses the pip layer.
# requirements-runtime.txt is the runtime-only subset (no ruff/mypy/
# pytest/pre-commit), regenerated from a scratch venv against just the
# [project].dependencies list — the full requirements-lock.txt includes
# dev-tool transitives (virtualenv/filelock) that conflict on Python 3.12.
COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements-runtime.txt

# Application code. .dockerignore keeps .venv, __pycache__, tests, and
# vitta.db out of the image.
COPY . ./

RUN chown -R vitta:vitta /app
USER vitta

EXPOSE 8001

# LOG_FORMAT=json for containers so aggregators can parse cleanly; a
# human running `docker logs -f` sees JSON too, which is fine.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LOG_FORMAT=json

# Liveness gate for compose's depends_on and any external monitor. Uses
# the /api/health route we added specifically for this — no auth, no DB.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8001/api/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
