import os
import logging
import litellm
from app.config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

# Setup Logger riêng cho module này
logger = logging.getLogger(__name__)

def setup_observability():
    """
    Cấu hình Langfuse cho LiteLLM.
    Được gọi bởi Engine hoặc Main khi khởi động.
    """
    # 1. Kiểm tra cấu hình
    if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        # Dùng debug thay vì info để đỡ spam nếu người dùng không dùng Langfuse
        logger.debug("[Observability] Langfuse keys not found. Skipping.")
        return

    # 2. Thiết lập biến môi trường
    os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
    os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY
    os.environ["LANGFUSE_HOST"] = LANGFUSE_HOST

    # 3. Kích hoạt Callback trong LiteLLM
    try:
        import langfuse
        
        # Đăng ký callback (tránh duplicate)
        if "langfuse" not in litellm.success_callback:
            litellm.success_callback.append("langfuse")
        
        if "langfuse" not in litellm.failure_callback:
            litellm.failure_callback.append("langfuse")
            
        logger.info(f"✅ [Observability] Langfuse Enabled (v{langfuse.version.__version__})")
        
    except ImportError:
        logger.warning("⚠️ [Observability] 'langfuse' library not installed. Run 'uv add langfuse'.")
    except Exception as e:
        logger.error(f"❌ [Observability] Failed to initialize Langfuse: {e}")
        # Clean up để tránh lỗi runtime
        if "langfuse" in litellm.success_callback:
            litellm.success_callback.remove("langfuse")
