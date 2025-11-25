import os
from typing import List, Optional
from sqlmodel import Session, select
from litellm import Router
from app.models import Provider
from app.config import REDIS_URL, ENABLE_CACHE, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

class AIEngine:
    def __init__(self):
        self.router: Optional[Router] = None
        
    def initialize(self, session: Session):
        """Khởi tạo Router từ Database"""
        print("🔄 [Engine] Initializing AI Router...")
        
        # 1. Setup Observability (Langfuse)
        if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
            os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
            os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY
            # LiteLLM tự động nhận diện qua biến môi trường để kích hoạt callback
            from litellm import success_callback, failure_callback
            if "langfuse" not in success_callback: success_callback.append("langfuse")
            if "langfuse" not in failure_callback: failure_callback.append("langfuse")
            print("✅ [Engine] Langfuse Enabled")

        # 2. Load Providers từ DB
        providers = session.exec(select(Provider)).all()
        model_list = []
        
        for p in providers:
            # Cấu hình từng deployment cho Router
            # LiteLLM Router cần format: [{ "model_name": "gpt-4", "litellm_params": { ... } }]
            
            # Ta sẽ map tất cả provider về một model "ảo" hoặc giữ nguyên tên model
            # Để đơn giản hóa Fallback, ta cần user cấu hình nhiều provider cùng loại.
            # Ví dụ: Provider A (OpenAI), Provider B (Azure) đều phục vụ model "gpt-4o"
            
            deployment = {
                "model_name": p.name, # Alias dùng để routing (vd: gpt-4o)
                "litellm_params": {
                    "model": f"{p.provider_type}/{p.name}" if p.provider_type != "openai" else p.name,
                    "api_key": p.api_key,
                }
            }
            
            if p.base_url:
                deployment["litellm_params"]["api_base"] = p.base_url
                
            model_list.append(deployment)

        # 3. Init Router với Redis Cache
        router_kwargs = {
            "model_list": model_list,
            # Cấu hình Fallback: Nếu 1 provider lỗi, thử cái tiếp theo trong list cùng tên model
            "fallbacks": [], 
            "set_verbose": False
        }
        
        if REDIS_URL and ENABLE_CACHE:
            router_kwargs["redis_host"] = os.getenv("REDIS_HOST", "redis")
            router_kwargs["redis_port"] = int(os.getenv("REDIS_PORT", 6379))
            router_kwargs["redis_password"] = os.getenv("REDIS_PASSWORD", None)
            router_kwargs["cache_responses"] = True
            print(f"✅ [Engine] Caching Enabled (Redis)")

        self.router = Router(**router_kwargs)
        print(f"🚀 [Engine] Router Ready with {len(model_list)} providers")

    async def reload(self, session: Session):
        """Reload nóng khi Admin thay đổi cấu hình"""
        self.initialize(session)

# Global Instance
ai_engine = AIEngine()
