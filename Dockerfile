# ==========================================
# Giai đoạn 1: Builder
# ==========================================
FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./

# Cài đặt dependencies
# SỬA Ở ĐÂY: Thêm "--frozen" theo yêu cầu
# --frozen: Bắt buộc cài đúng version trong uv.lock (CI/CD safe)
# --no-dev: Không cài gói dev (pytest, ruff...)
RUN uv sync --frozen --no-install-project --no-dev

# ==========================================
# Giai đoạn 2: Runtime
# ==========================================
FROM python:3.11-slim-bookworm

# Cài curl cho healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Tạo user non-root
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copy venv & thêm vào PATH
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy code & setup quyền
COPY app ./app
RUN mkdir /data && chown -R appuser:appuser /data /app

ENV DB_PATH=/data/gateway.db

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# SỬA Ở ĐÂY: Tách migration ra.
# Container này giờ chỉ chuyên trách chạy App.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]