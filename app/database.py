import sys
from typing import Optional, AsyncGenerator
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import redis.asyncio as redis

from app.config import DATABASE_URL, REDIS_URL, MASTER_TRACKER_ID
from app.models import GatewayKey

# --- 1. SETUP ASYNC ENGINE ---
connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args=connect_args,
    pool_size=20 if "postgres" in DATABASE_URL else 5,
    max_overflow=10 if "postgres" in DATABASE_URL else 10,
    pool_pre_ping=True 
)

if "postgres" in DATABASE_URL:
    print("✅ [Database] Using PostgreSQL (Async)")
else:
    print("✅ [Database] Using SQLite (Async)")

# --- 2. SESSION FACTORY (ĐỔI TÊN Ở ĐÂY) ---
# Đổi từ async_session_factory -> AsyncSessionLocal
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

# Dependency Injection
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

# --- 3. REDIS SETUP ---
redis_client: Optional[redis.Redis] = None

async def init_redis():
    global redis_client
    if REDIS_URL:
        try:
            redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            await redis_client.ping()
            print(f"✅ [Redis] Connected")
        except Exception as e:
            print(f"⚠️ [Redis] Connection failed: {e}")
            redis_client = None

async def close_redis():
    if redis_client:
        await redis_client.close()
        print("✅ [Redis] Closed")

# --- 4. INIT DB ---
async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSessionLocal() as session:
        existing = await session.get(GatewayKey, MASTER_TRACKER_ID)
        if not existing:
            print(f"👑 Creating Master Tracker ID: {MASTER_TRACKER_ID}")
            session.add(GatewayKey(key=MASTER_TRACKER_ID, name="👑 ADMIN TRACKER", usage_count=0, is_hidden=True))
            await session.commit()