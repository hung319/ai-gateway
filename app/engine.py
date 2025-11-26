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
        
        # 1. Langfuse Config
        if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
            os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
            os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY
            from litellm import success_callback, failure_callback
            if "langfuse" not in success_callback: success_callback.append("langfuse")
            if "langfuse" not in failure_callback: failure_callback.append("langfuse")
            print("✅ [Engine] Langfuse Logging Active")

        # 2. Load Providers -> Router
        providers = session.exec(select(Provider)).all()
        model_list = []
        
        for p in providers:
            # --- [FIX QUAN TRỌNG] ---
            # Luôn định dạng model là "provider/name" để LiteLLM không bị lỗi
            # với các model custom (ví dụ: duckai, local-model...)
            
            # Nếu là OpenAI standard (Custom URL hoặc Official)
            if p.provider_type == "openai":
                # Ép buộc format: openai/tên_alias
                # Điều này báo cho LiteLLM biết: "Dùng giao thức OpenAI để gọi model này"
                litellm_model_id = f"openai/{p.name}"
            else:
                # Các loại khác (gemini/tên, openrouter/tên...)
                litellm_model_id = f"{p.provider_type}/{p.name}"

            deployment = {
                "model_name": p.name, # Alias dùng để routing
                "litellm_params": {
                    "model": litellm_model_id,
                    "api_key": p.api_key,
                }
            }
            
            if p.base_url:
                deployment["litellm_params"]["api_base"] = p.base_url
            
            model_list.append(deployment)

        # 3. Init Router
        if not model_list:
            print("⚠️ [Engine] No providers found in DB. Waiting for setup...")
            self.router = None
            return

        router_config = {
            "model_list": model_list,
            "set_verbose": False
        }
        
        # Redis Cache
        if REDIS_URL and ENABLE_CACHE:
            router_config["cache_responses"] = True
            os.environ["REDIS_URL"] = REDIS_URL
            print("✅ [Engine] Semantic Caching Enabled")

        try:
            self.router = Router(**router_config)
            print(f"🚀 [Engine] Router Ready with {len(model_list)} providers")
        except Exception as e:
            print(f"❌ [Engine] Router Init Failed: {e}")
            # Không crash app nếu config sai, để admin còn vào sửa được
            self.router = None

    async def reload(self, session: Session):
        self.initialize(session)

ai_engine = AIEngine()
