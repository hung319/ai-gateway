import os
from typing import Optional
from sqlmodel import Session, select
from litellm import Router
from app.models import Provider
from app.config import REDIS_URL, ENABLE_CACHE, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

class AIEngine:
    def __init__(self):
        self.router: Optional[Router] = None
        
    def initialize(self, session: Session):
        print("🔄 [Engine] Initializing...")
        
        if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
            os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
            os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY
            from litellm import success_callback, failure_callback
            if "langfuse" not in success_callback: success_callback.append("langfuse")
            if "langfuse" not in failure_callback: failure_callback.append("langfuse")

        providers = session.exec(select(Provider)).all()
        model_list = []
        
        for p in providers:
            # --- FIX: Sử dụng Model thật để gọi Upstream ---
            real_model_name = p.default_model if p.default_model else p.name
            
            if p.provider_type == "openai":
                litellm_model = f"openai/{real_model_name}"
            elif p.provider_type == "azure":
                litellm_model = f"azure/{real_model_name}"
            else:
                litellm_model = f"{p.provider_type}/{real_model_name}"

            deployment = {
                "model_name": p.name, # Alias dùng để định tuyến nội bộ
                "litellm_params": {
                    "model": litellm_model, # Tên thật gửi đi (VD: openai/gpt-4o-mini)
                    "api_key": p.api_key,
                }
            }
            if p.base_url: deployment["litellm_params"]["api_base"] = p.base_url
            model_list.append(deployment)

        if not model_list:
            self.router = None
            print("⚠️ [Engine] No providers found.")
            return

        router_config = { "model_list": model_list, "set_verbose": False }
        
        if REDIS_URL and ENABLE_CACHE:
            router_config["cache_responses"] = True
            os.environ["REDIS_URL"] = REDIS_URL
            print("✅ [Engine] Cache Enabled")

        try:
            self.router = Router(**router_config)
            print(f"🚀 [Engine] Ready ({len(model_list)} providers)")
        except Exception as e:
            print(f"❌ [Engine] Error: {e}")
            self.router = None

    async def reload(self, session: Session):
        self.initialize(session)

ai_engine = AIEngine()
