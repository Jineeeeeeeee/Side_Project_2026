# deployments/Dockerfile
# Build context = project root (set trong docker-compose.yml)

# ── Stage 1: Builder ─────────────────────────────────────────────
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml requirements.txt ./

RUN pip install --upgrade pip && \
    pip wheel --no-cache-dir --no-deps --wheel-dir /build/wheels \
    "google-genai>=1.0" \
    "pydantic>=2.0" \
    "python-dotenv>=1.0" \
    "typer[all]>=0.12" \
    "tqdm>=4.0" \
    "pyahocorasick>=2.0" \
    "streamlit>=1.30" \
    "pandas>=2.0"


# ── Stage 2: Runtime ─────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

COPY --from=builder /build/wheels /tmp/wheels
RUN pip install --no-cache-dir /tmp/wheels/*.whl && \
    rm -rf /tmp/wheels

# Source code và scripts (từ project root)
COPY src/          ./src/
COPY scripts/      ./scripts/
COPY prompts/      ./prompts/

# Tạo sẵn thư mục data
RUN mkdir -p \
    inputs outputs logs \
    data/glossary data/characters \
    data/skills data/memory

# Non-root user
RUN useradd -m -u 1000 -s /bin/bash littrans && \
    chown -R littrans:littrans /app
USER littrans

# PYTHONPATH → Python tìm được src/littrans/
ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" \
    || exit 1

# [FIX] COPY trước khi switch sang non-root user để chmod hoạt động,
# sau đó chmod +x để đảm bảo entrypoint executable trên mọi hệ thống
# (Git không bảo toàn file permissions → container crash với Permission denied).
COPY deployments/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && \
    chown littrans:littrans /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]

# Default: Web UI via scripts/
CMD ["python", "scripts/run_ui.py", "--host", "0.0.0.0"]