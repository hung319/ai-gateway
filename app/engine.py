import os
from typing import Optional
from sqlmodel import Session, select
from litellm import Router
from app.models import Provider
from app.config import REDIS_URL, ENABLE_CACHE
from app.observability import setup_observability # <--- Import file mới

class AIEngine:
    def __init__(self):
        self.router: Optional[Router] = None
        
    def initialize(self, session: Session):
        print("🔄 [Engine] Initializing...")
        
        # 1. Setup Observability (Tách biệt logic)
        setup_observability()

        # 2. Load Providers
        providers = session.exec(select(Provider)).all()
        model_list = []
        
        for p in providers:
            # Tự động thêm prefix cho model
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
            if p.base_url: deployment["litellm_params"]["api_base"] = p.base_url
            model_list.append(deployment)

        # 3. Init Router
        if not model_list:
            print("⚠️ [Engine] No providers found.")
            self.router = None
            return

        router_config = {"model_list": model_list, "set_verbose": False}
        
        if REDIS_URL and ENABLE_CACHE:
            router_config["cache_responses"] = True
            os.environ["REDIS_URL"] = REDIS_URL
            print("✅ [Engine] Cache Enabled")

        try:
            self.router = Router(**router_config)
            print(f"🚀 [Engine] Ready ({len(model_list)} providers)")
        except Exception as e:
            print(f"❌ [Engine] Router Error: {e}")
            self.router = None

    async def reload(self, session: Session):
        self.initialize(session)

ai_engine = AIEngine()
