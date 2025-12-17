import json
import asyncio
import logging
import time
from sqlmodel import select
from app.database import redis_client, AsyncSessionLocal
from app.models import RequestLog

logger = logging.getLogger("app.cache")
BUFFER_KEY = "gw:log_buffer"
PROCESSING_SET = "gw:processing_set" # Dùng Set để lưu các request ID đang chạy
BATCH_SIZE = 50  # Số lượng log mỗi lần ghi vào DB
FLUSH_INTERVAL = 5 # Giây (Thời gian tự động ghi nếu chưa đủ batch)

class LogCache:
    """
    Hệ thống Write-Behind Cache cho Logs.
    1. Request đến -> Lưu vào Redis (Nhanh).
    2. Background Task -> Lấy từ Redis -> Bulk Insert vào DB (Hiệu quả).
    """

    @staticmethod
    async def add_processing(req_id: str):
        """Đánh dấu request đang xử lý (để hiện màu Vàng trên dashboard)"""
        if redis_client:
            await redis_client.sadd(PROCESSING_SET, req_id)

    @staticmethod
    async def remove_processing(req_id: str):
        """Xóa đánh dấu đang xử lý"""
        if redis_client:
            await redis_client.srem(PROCESSING_SET, req_id)

    @staticmethod
    async def buffer_log(log_data: dict):
        """Đẩy log hoàn chỉnh vào Redis Queue"""
        if redis_client:
            try:
                # Serialize log thành JSON string
                await redis_client.rpush(BUFFER_KEY, json.dumps(log_data))
            except Exception as e:
                logger.error(f"Redis Push Error: {e}")

    @staticmethod
    async def flush_to_db():
        """
        Lấy dữ liệu từ Redis và Insert vào DB.
        Được gọi bởi Background Task hoặc khi Shutdown.
        """
        if not redis_client:
            return

        # Lấy tất cả log đang chờ trong Redis
        # Dùng lpop hoặc lrange. Ở đây dùng transaction pipeline để an toàn.
        try:
            len_buffer = await redis_client.llen(BUFFER_KEY)
            if len_buffer == 0:
                return

            # Lấy tối đa BATCH_SIZE items
            items = await redis_client.lpop(BUFFER_KEY, BATCH_SIZE)
            if not items:
                return
            
            logs_to_insert = []
            for i in items:
                data = json.loads(i)
                logs_to_insert.append(RequestLog(**data))
            
            if logs_to_insert:
                async with AsyncSessionLocal() as session:
                    session.add_all(logs_to_insert)
                    await session.commit()
                    logger.info(f"✅ [Cache] Flushed {len(logs_to_insert)} logs to DB.")
                    
        except Exception as e:
            logger.error(f"❌ [Cache] Flush Error: {e}")
            # Nếu lỗi, có thể cân nhắc push lại vào Redis (tùy chiến lược)

# Biến global để quản lý background task
log_cache = LogCache()