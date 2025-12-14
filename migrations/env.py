import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# --- 1. SETUP PATH & IMPORTS ---
# Thêm thư mục hiện tại vào sys.path để Python tìm thấy module 'app'
sys.path.append(os.getcwd())

# Import Config & Models của App
from app.config import DATABASE_URL, DB_PATH
from app.models import * # Import tất cả models để SQLModel nhận diện
from sqlmodel import SQLModel

# --- 2. CONFIG ALEMBIC ---
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- 3. SET TARGET METADATA ---
# Đây là chìa khóa để Alembic tự detect thay đổi trong code Model
target_metadata = SQLModel.metadata

# --- 4. XỬ LÝ URL DATABASE ---
# Logic: Lấy URL từ biến môi trường/Config thay vì file alembic.ini
def get_url():
    # Ưu tiên PostgreSQL
    if DATABASE_URL and DATABASE_URL.startswith("postgresql"):
        return DATABASE_URL
    # Fallback về SQLite (tuy nhiên Alembic thường dùng cho SQL Server/Postgres hơn)
    return f"sqlite:///{DB_PATH}"

# Ghi đè URL vào config của Alembic object
config.set_main_option("sqlalchemy.url", get_url())

def run_migrations_offline() -> None:
    """Chạy migration ở chế độ 'offline' (chỉ tạo file SQL, không kết nối DB)."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Chạy migration ở chế độ 'online' (kết nối trực tiếp vào DB)."""
    
    # Tạo Engine từ config đã được inject URL
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()