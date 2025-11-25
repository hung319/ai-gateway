import os

# Database & Security
DB_PATH = os.getenv("DB_PATH", "gateway.db")
MASTER_KEY = os.getenv("MASTER_KEY", "sk-master-secret-123") 
MASTER_TRACKER_ID = "MASTER_ADMIN_TRACKER"

# Redis & Caching
REDIS_URL = os.getenv("REDIS_URL", "") 
CACHE_TTL = 300 
ENABLE_CACHE = os.getenv("ENABLE_CACHE", "true").lower() == "true"

# Observability (Langfuse)
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

# Timeout
MODEL_FETCH_TIMEOUT = 10.0
