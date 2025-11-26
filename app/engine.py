import os
from typing import Optional
from sqlmodel import Session, select
from litellm import Router
from app.models import Provider
from app.config import REDIS_URL, ENABLE_CACHE
from app.observability import setup_observability

class AIEngine:
    def __init__(self):
        self.router: Optional[Router] = None
        
    def initialize(self, session: Session):
        print("🔄 [Engine] Initializing...")
        
        # 1. Setup Observability
        setup_observability()

        # 2. Load Providers
        providers = session.exec(select(Provider)).all()
        model_list = []
        
        for p in providers:
            # --- [FIX QUAN TRỌNG] ---
            # Lấy tên model thật (nếu có), nếu không thì fallback về alias
            # Điều này giúp sửa lỗi 404 khi Alias (duckai) khác tên model thật (gpt-4o-mini)
            real_name = p.default_model if p.default_model else p.name

            # Tạo chuỗi model chuẩn cho LiteLLM
            if p.provider_type == "openai":
                litellm_model = f"openai/{real_name}"
            elif p.provider_type == "azure":
                litellm_model = f"azure/{real_name}"
            else:
                litellm_model = f"{p.provider_type}/{real_name}"

            deployment = {
                "model_name": p.name, # Alias (Gateway dùng để định tuyến)
                "litellm_params": {
                    "model": litellm_model, # Model thật (LiteLLM gửi đi)
                    "api_key": p.api_key,
                }
            }
            
            if p.base_url: 
                deployment["litellm_params"]["api_base"] = p.base_url
                
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
