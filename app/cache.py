import json
import asyncio
import logging
import time
from datetime import datetime
from typing import Optional
from sqlmodel import select
from app.database import redis_client, AsyncSessionLocal
from app.models import RequestLog

logger = logging.getLogger("app.cache")

# --- CONFIG ---
BUFFER_KEY = "gw:log_buffer"
PROCESSING_SET = "gw:processing_set" 
BATCH_SIZE = 50  
FLUSH_INTERVAL = 5 

class LogCache:
    """
    Hệ thống Write-Behind Cache cho Logs.
    """

    @staticmethod
    async def add_processing(req_id: str):
        if redis_client:
            await redis_client.sadd(PROCESSING_SET, req_id)

    @staticmethod
    async def remove_processing(req_id: str):
        if redis_client:
            await redis_client.srem(PROCESSING_SET, req_id)

    # --- MAIN LOGGING FUNCTION ---
    async def add_log(self, model: str, real_model: str, status: str, 
                      latency: float, ip: str, app_name: str = None, 
                      input_tokens: int = 0, output_tokens: int = 0,
                      provider_name: str = None):
        """
        Ghi log vào Redis Buffer
        """
        log_entry = {
            "ts": datetime.utcnow().timestamp(), 
            "model": model,
            "real_model": real_model, 
            "status": status,
            "latency": latency,
            "ip": ip,
            "app_name": app_name,     
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "provider_name": provider_name
        }
        await self.buffer_log(log_entry)

    @staticmethod
    async def buffer_log(log_data: dict):
        if redis_client:
            try:
                await redis_client.rpush(BUFFER_KEY, json.dumps(log_data))
            except Exception as e:
                logger.error(f"Redis Push Error: {e}")

    @staticmethod
    async def flush_to_db():
        if not redis_client:
            return

        try:
            len_buffer = await redis_client.llen(BUFFER_KEY)
            if len_buffer == 0:
                return

            items = await redis_client.lpop(BUFFER_KEY, BATCH_SIZE)
            if not items:
                return
            
            logs_to_insert = []
            for i in items:
                try:
                    data = json.loads(i)
                    # Convert timestamp float -> datetime
                    if "ts" in data and isinstance(data["ts"], float):
                        data["ts"] = datetime.fromtimestamp(data["ts"])
                    
                    logs_to_insert.append(RequestLog(**data))
                except Exception as parse_err:
                    logger.error(f"Log Parse Error: {parse_err}")
            
            if logs_to_insert:
                async with AsyncSessionLocal() as session:
                    session.add_all(logs_to_insert)
                    await session.commit()
                    logger.info(f"✅ [Cache] Flushed {len(logs_to_insert)} logs to DB.")
                    
        except Exception as e:
            logger.error(f"❌ [Cache] Flush Error: {e}")

log_cache = LogCache()