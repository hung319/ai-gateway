import os
import logging
from typing import Optional
from sqlmodel import select, func
from sqlalchemy.ext.asyncio import AsyncSession
# from litellm import Router  <-- KHÔNG CẦN NỮA VÌ GATEWAY ĐÃ XỬ LÝ
from app.models import Provider
from app.config import REDIS_URL, ENABLE_CACHE
from app.observability import setup_observability

# Setup Logger
logger = logging.getLogger("app.engine")

class AIEngine:
    def __init__(self):
        # Router không còn cần thiết vì Gateway gọi trực tiếp litellm.acompletion
        self.router = None 
        self.active_model_count: int = 0
        
    async def initialize(self, session: AsyncSession):
        logger.info("🔄 [Engine] Initializing Global Settings...")
        
        # 1. Setup Observability (Langfuse)
        setup_observability()

        # 2. Setup Env for LiteLLM (Optional Global Settings)
        if REDIS_URL and ENABLE_CACHE:
            os.environ["REDIS_URL"] = REDIS_URL
            logger.info("✅ [Engine] Redis Environment Variable Set")

        # 3. Load Stats (Chỉ để hiển thị Log, không load model vào RAM)
        try:
            # Đếm số lượng Provider đang hoạt động
            count_query = select(func.count(Provider.name))
            self.active_model_count = (await session.execute(count_query)).scalar_one()
            
            logger.info(f"🚀 [Engine] System Ready. Available Providers: {self.active_model_count}")
            
        except Exception as e:
            logger.error(f"⚠️ [Engine] Database error during init: {e}")
            self.active_model_count = 0

    async def reload(self, session: AsyncSession):
        """
        Hàm này được gọi từ admin.py khi có thay đổi Provider/Key.
        Chủ yếu để cập nhật lại Log hoặc các config global nếu cần.
        """
        await self.initialize(session)

# Global Instance
ai_engine = AIEngine()