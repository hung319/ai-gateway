# Giai đoạn 1: Build env
FROM python:3.11-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Thiết lập biến môi trường cho uv
ENV UV_COMPILE_BYTECODE=1 
ENV UV_LINK_MODE=copy

WORKDIR /app

# Copy file cấu hình
COPY pyproject.toml uv.lock* ./

# Cài đặt dependencies
# SỬA Ở ĐÂY: Bỏ "--frozen" đi
# --no-install-project: Chỉ cài thư viện, chưa copy code
RUN uv sync --no-install-project

# Giai đoạn 2: Runtime (Image cuối cùng)
FROM python:3.11-slim-bookworm

WORKDIR /app

# Copy môi trường ảo từ builder sang
COPY --from=builder /app/.venv /app/.venv

# Thêm venv vào PATH
ENV PATH="/app/.venv/bin:$PATH"

# Copy source code vào
COPY app ./app

# Tạo volume folder cho DB
VOLUME /data
ENV DB_PATH=/data/gateway.db

# Expose port
EXPOSE 8000

# Chạy app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
