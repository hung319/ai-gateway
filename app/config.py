import os
from dotenv import load_dotenv

load_dotenv()

# Database & Security
DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_PATH = os.getenv("DB_PATH", "gateway.db")
MASTER_KEY = os.getenv("MASTER_KEY", "sk-master-secret-123")
MASTER_TRACKER_ID = "MASTER_ADMIN_TRACKER"

# Redis & Caching
REDIS_URL = os.getenv("REDIS_URL", "") 
CACHE_TTL = 300 # Cache list model trong 5 phút
ENABLE_CACHE = os.getenv("ENABLE_CACHE", "true").lower() == "true" # Cache câu trả lời AI

# Observability (Langfuse)
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_BASE_URL = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

# Timeout
MODEL_FETCH_TIMEOUT = 10.0
SESSION_DURATION = 7 * 24 * 60 * 60 # 7 ngày
