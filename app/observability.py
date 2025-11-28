import os
import logging
import litellm
# Import biến mới LANGFUSE_BASE_URL từ config
from app.config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL

logger = logging.getLogger(__name__)

def setup_observability():
    """
    Cấu hình Langfuse OpenTelemetry (OTEL).
    Sử dụng LANGFUSE_BASE_URL làm nguồn Host duy nhất.
    """
    # 1. Validate Keys
    if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        logger.debug("[Observability] Langfuse keys missing. Skipping.")
        return

    # 2. Setup Environment Variables cho LiteLLM OTEL
    # LiteLLM/OTEL đọc trực tiếp từ os.environ
    os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
    os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY
    
    # Quan trọng: Map từ BASE_URL (của bạn) -> LANGFUSE_OTEL_HOST (của LiteLLM)
    # .rstrip("/") để xóa dấu gạch chéo thừa nếu có (vd: .com/ -> .com)
    otel_host = LANGFUSE_BASE_URL.rstrip("/")
    os.environ["LANGFUSE_OTEL_HOST"] = otel_host

    # 3. Kích hoạt LiteLLM Callback
    try:
        # Check xem thư viện OTEL đã cài chưa
        import opentelemetry
        
        # Đăng ký callback 'langfuse_otel' (chuẩn mới)
        if "langfuse_otel" not in litellm.callbacks:
            litellm.callbacks.append("langfuse_otel")
            
        logger.info(f"✅ [Observability] Langfuse OTEL Enabled")
        logger.info(f"   🔗 Host: {otel_host}")
        
    except ImportError:
        logger.error("❌ [Observability] Missing OTEL libraries.")
        logger.error("Run: uv add opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp")
        
    except Exception as e:
        logger.error(f"❌ [Observability] Setup Failed: {str(e)}")
