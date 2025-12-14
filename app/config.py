import os
from dotenv import load_dotenv

load_dotenv()

# --- Database & Security (Auto Async Convert) ---
DB_PATH = os.getenv("DB_PATH", "gateway.db")
raw_url = os.getenv("DATABASE_URL", "")

# Logic tự động chuyển đổi sang Driver Async
if raw_url:
    # 1. Xử lý PostgreSQL
    if raw_url.startswith("postgresql://"):
        if "+asyncpg" not in raw_url:
            DATABASE_URL = raw_url.replace("postgresql://", "postgresql+asyncpg://")
        else:
            DATABASE_URL = raw_url
    elif raw_url.startswith("postgres://"): # Hỗ trợ alias cũ
        DATABASE_URL = raw_url.replace("postgres://", "postgresql+asyncpg://")
    
    # 2. Xử lý SQLite
    elif raw_url.startswith("sqlite://"):
        if "+aiosqlite" not in raw_url:
            DATABASE_URL = raw_url.replace("sqlite://", "sqlite+aiosqlite://")
        else:
            DATABASE_URL = raw_url
    
    # 3. Các loại khác (MySQL, etc - giữ nguyên hoặc user tự cấu hình)
    else:
        DATABASE_URL = raw_url
else:
    # 4. Mặc định: SQLite Async local
    DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

MASTER_KEY = os.getenv("MASTER_KEY", "sk-master-secret-123")
MASTER_TRACKER_ID = "MASTER_ADMIN_TRACKER"

# --- Redis & Caching ---
REDIS_URL = os.getenv("REDIS_URL", "") 
CACHE_TTL = 300 # Cache list model trong 5 phút
ENABLE_CACHE = os.getenv("ENABLE_CACHE", "true").lower() == "true" # Cache câu trả lời AI

# --- Observability (Langfuse) ---
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_BASE_URL = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

# --- Timeouts & Sessions ---
MODEL_FETCH_TIMEOUT = 10.0
SESSION_DURATION = 7 * 24 * 60 * 60 # 7 ngày