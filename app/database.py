from sqlmodel import SQLModel, create_engine, Session
# Thêm DATABASE_URL vào import
from app.config import DB_PATH, DATABASE_URL, REDIS_URL, MASTER_KEY, MASTER_TRACKER_ID
from app.models import GatewayKey
import redis.asyncio as redis
from typing import Optional

# --- 1. SETUP DATABASE ENGINE ---
# Logic: Nếu có DATABASE_URL (Postgres) thì dùng, không thì quay về SQLite
if DATABASE_URL and DATABASE_URL.startswith("postgresql"):
    # Cấu hình cho PostgreSQL (Production)
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,  # Tự động reconnect nếu kết nối bị ngắt (quan trọng)
        pool_size=20,        # Giữ tối đa 20 kết nối sẵn sàng
        max_overflow=10      # Cho phép mở thêm 10 kết nối khi quá tải
    )
    print("✅ [Database] Using PostgreSQL")
else:
    # Cấu hình cho SQLite (Development / Standalone)
    sqlite_url = f"sqlite:///{DB_PATH}"
    engine = create_engine(
        sqlite_url, 
        connect_args={"check_same_thread": False} # Bắt buộc cho SQLite trong môi trường async
    )
    print(f"⚠️ [Database] Using SQLite at {DB_PATH}")

redis_client: Optional[redis.Redis] = None

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    # Tạo Master Tracker Record
    with Session(engine) as session:
        if not session.get(GatewayKey, MASTER_TRACKER_ID):
            session.add(GatewayKey(key=MASTER_TRACKER_ID, name="👑 ADMIN TRACKER", usage_count=0, is_hidden=True))
            session.commit()

def get_session():
    with Session(engine) as session:
        yield session

async def init_redis():
    global redis_client
    if REDIS_URL:
        try:
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            await redis_client.ping()
            print(f"✅ Redis Connected")
        except Exception as e:
            print(f"⚠️ Redis Error: {e}")
            redis_client = None

async def close_redis():
    if redis_client: await redis_client.close()
