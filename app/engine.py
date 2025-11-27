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
        
        # 1. Langfuse
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
            # --- FIX QUAN TRỌNG ---
            # Ép buộc prefix để LiteLLM không bị lỗi "Provider NOT provided"
            if p.provider_type == "openai":
                real_model = f"openai/{p.name}" # Luôn thêm openai/
            elif p.provider_type == "azure":
                real_model = f"azure/{p.name}"
            else:
                # OpenRouter / Gemini thường đã có sẵn format chuẩn hoặc tự xử lý
                real_model = f"{p.provider_type}/{p.name}"

            deployment = {
                "model_name": p.name, # Đây là cái tên Gateway sẽ gọi (Alias)
                "litellm_params": {
                    "model": real_model, # Đây là cái tên LiteLLM sẽ gọi xuống Provider
                    "api_key": p.api_key,
                }
            }
            
            if p.base_url:
                deployment["litellm_params"]["api_base"] = p.base_url
            
            model_list.append(deployment)

        # 3. Init Router
        if not model_list:
            print("⚠️ [Engine] No providers found. Router empty.")
            self.router = None
            return

        router_config = {
            "model_list": model_list,
            "set_verbose": False
        }
        
        if REDIS_URL and ENABLE_CACHE:
            router_config["cache_responses"] = True
            os.environ["REDIS_URL"] = REDIS_URL
            print("✅ [Engine] Semantic Caching Enabled")

        try:
            self.router = Router(**router_config)
            print(f"🚀 [Engine] Router Ready with {len(model_list)} providers")
        except Exception as e:
            print(f"❌ [Engine] Init Error: {e}")
            self.router = None

    async def reload(self, session: Session):
        self.initialize(session)

ai_engine = AIEngine()
