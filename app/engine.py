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
            dep = {
                "model_name": p.name, # Alias dùng để gọi
                "litellm_params": {
                    "model": f"{p.provider_type}/{p.name}" if p.provider_type != "openai" else p.name,
                    "api_key": p.api_key,
                }
            }
            if p.base_url: dep["litellm_params"]["api_base"] = p.base_url
            model_list.append(dep)

        # 3. Init Router
        router_config = {
            "model_list": model_list,
            "fallbacks": [], # Có thể thêm logic fallback tự động ở đây
            "set_verbose": False
        }
        
        # Caching qua Redis cho Router
        if REDIS_URL and ENABLE_CACHE:
            # LiteLLM yêu cầu redis_host, redis_port riêng lẻ hoặc cache object
            # Ở đây ta dùng cấu hình cache params
            router_config["cache_responses"] = True
            # Redis params sẽ được Router tự parse từ môi trường hoặc truyền thẳng
            # Đơn giản nhất: Router sẽ dùng internal cache nếu ko có redis params cụ thể
            # Để kích hoạt Redis Cache cho Router, cần set os.environ["REDIS_URL"]
            os.environ["REDIS_URL"] = REDIS_URL
            print("✅ [Engine] Semantic Caching Enabled")

        self.router = Router(**router_config)
        print(f"🚀 [Engine] Ready with {len(model_list)} providers")

    async def reload(self, session: Session):
        self.initialize(session)

ai_engine = AIEngine()
