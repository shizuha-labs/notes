FROM python:3.10-slim

ARG APT_HTTP_PROXY=""
ARG UV_INDEX_URL=""
ARG UV_INSECURE_HOST=""

# Keep the pinned uv binary on the Docker Hub path so Origin's Kaniko
# --registry-mirror applies on both architectures. Direct GHCR pulls can enter
# a token redirect loop on the ARM64 builder (ORIG-98).
COPY --from=docker.io/astral/uv:0.11.26 /uv /uvx /bin/

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV UV_PYTHON_DOWNLOADS=0
ENV UV_LINK_MODE=copy
ENV UV_INDEX_URL=${UV_INDEX_URL}
ENV UV_INSECURE_HOST=${UV_INSECURE_HOST}
ENV PATH="/app/.venv/bin:$PATH"

# Set work directory
WORKDIR /app

# Install system dependencies. Origin supplies the in-cluster apt-cacher-ng
# endpoint; local builds remain valid when APT_HTTP_PROXY is unset.
RUN if [ -n "${APT_HTTP_PROXY}" ]; then \
      printf 'Acquire::http::Proxy "%s";\nAcquire::https::Proxy "DIRECT";\nAcquire::Retries "3";\n' "${APT_HTTP_PROXY}" \
        > /etc/apt/apt.conf.d/00shizuha-apt-cache; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client \
        jq \
        build-essential \
        libpq-dev \
        netcat-traditional \
        supervisor \
        vim \
        curl \
        wget \
        libmagic1 \
        libjpeg-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies, including the shared storage package, from the
# committed uv lockfile.
COPY pyproject.toml uv.lock /app/
COPY packages/shizuha-storage /app/packages/shizuha-storage
# Keep the portable public-PyPI uv.lock immutable, export its exact pins and
# hashes without re-resolving, then install them through the internal mirror.
RUN uv venv .venv \
    && uv export --frozen --no-dev --no-emit-project --no-emit-local --quiet \
        --format requirements-txt \
        --output-file /tmp/requirements.lock \
    && uv pip sync --python .venv/bin/python --compile-bytecode --require-hashes /tmp/requirements.lock \
    && uv pip install --python .venv/bin/python --compile-bytecode --no-deps ./packages/shizuha-storage \
    && rm -f /tmp/requirements.lock

# Copy project
COPY . /app/

# Workers cannot write bytecode at runtime. Compile once in the image instead
# of recompiling the same dependencies and application in every startup process.
RUN python -m compileall -q notes notesmanager mcp-server \
    && python scripts/verify-image-bytecode.py --prove-negative-control

# Create directories for logs and media
RUN mkdir -p /var/log/django /var/log/supervisor /app/media /app/staticfiles

# Static collection needs Django settings, but no reusable runtime key.
# The disposable process-local value is neither an image ENV nor a build ARG.
RUN SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" POSTGRES_PASSWORD=build-static-only python manage.py collectstatic --noinput

# Create entrypoint script
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# Copy supervisord configuration
COPY supervisord.conf /app/

# Expose port
EXPOSE 8012 18104

# Use entrypoint script
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]
