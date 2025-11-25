import os

# Settings
DB_PATH = os.getenv("DB_PATH", "gateway.db")
MASTER_KEY = os.getenv("MASTER_KEY", "sk-master-secret-123")
REDIS_URL = os.getenv("REDIS_URL", "")
MODEL_FETCH_TIMEOUT = 10.0
MASTER_TRACKER_ID = "MASTER_ADMIN_TRACKER"
CACHE_TTL = 300
