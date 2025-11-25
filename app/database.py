from sqlmodel import SQLModel, create_engine, Session
from app.config import DB_PATH, REDIS_URL
import redis.asyncio as redis
from typing import Optional

# SQLite
sqlite_url = f"sqlite:///{DB_PATH}"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

# Redis Global Client
redis_client: Optional[redis.Redis] = None

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

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
    if redis_client:
        await redis_client.close()
