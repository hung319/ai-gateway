import os
import logging
from typing import Optional
from sqlmodel import Session, select
from litellm import Router
from app.models import Provider
from app.config import REDIS_URL, ENABLE_CACHE
from app.observability import setup_observability  # <--- Import hàm setup

# Setup Logger
logger = logging.getLogger("app.engine")

class AIEngine:
    def __init__(self):
        self.router: Optional[Router] = None
        
    def initialize(self, session: Session):
        logger.info("🔄 [Engine] Initializing...")
        
        # 1. Setup Observability (Langfuse)
        # Tách logic ra module chuyên biệt để code engine gọn hơn
        setup_observability()

        # 2. Load Providers -> Router
        providers = session.exec(select(Provider)).all()
        model_list = []
        
        for p in providers:
            # Construct real model name
            if p.provider_type == "openai":
                real_model = f"openai/{p.name}" 
            elif p.provider_type == "azure":
                real_model = f"azure/{p.name}"
            else:
                real_model = f"{p.provider_type}/{p.name}"

            deployment = {
                "model_name": p.name, 
                "litellm_params": {
                    "model": real_model, 
                    "api_key": p.api_key,
                }
            }
            
            if p.base_url:
                deployment["litellm_params"]["api_base"] = p.base_url
            
            model_list.append(deployment)

        # 3. Init Router
        if not model_list:
            logger.warning("⚠️ [Engine] No providers found. Router empty.")
            self.router = None
            return

        router_config = {
            "model_list": model_list,
            "set_verbose": False # Tắt verbose log của LiteLLM để terminal sạch
        }
        
        if REDIS_URL and ENABLE_CACHE:
            router_config["cache_responses"] = True
            os.environ["REDIS_URL"] = REDIS_URL
            logger.info("✅ [Engine] Semantic Caching Enabled")

        try:
            self.router = Router(**router_config)
            logger.info(f"🚀 [Engine] Router Ready with {len(model_list)} providers")
        except Exception as e:
            logger.error(f"❌ [Engine] Init Error: {e}")
            self.router = None

    async def reload(self, session: Session):
        self.initialize(session)

ai_engine = AIEngine()
