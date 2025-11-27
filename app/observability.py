import os
import logging
import litellm
from app.config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

logger = logging.getLogger(__name__)

def setup_observability():
    """
    Cấu hình Langfuse (Python SDK v2).
    """
    if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        logger.debug("[Observability] Langfuse keys missing. Skipping.")
        return

    # 1. Setup Env Vars
    os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
    os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY
    if LANGFUSE_HOST:
        os.environ["LANGFUSE_HOST"] = LANGFUSE_HOST

    # 2. Hook vào LiteLLM
    try:
        import langfuse
        
        # --- FIX: Cách lấy version an toàn hơn ---
        # Ưu tiên lấy __version__ (string) trước. 
        # Tránh dùng langfuse.version vì nó có thể là module object.
        version = getattr(langfuse, "__version__", "unknown")
        
        # Check kỹ: chỉ warning nếu version là string thực sự
        if isinstance(version, str) and version.startswith("3."):
             logger.warning(f"⚠️ [Observability] Detected Langfuse v{version}. LiteLLM native callback works best with v2!")

        # Đăng ký Callback
        if "langfuse" not in litellm.success_callback:
            litellm.success_callback.append("langfuse")
        
        if "langfuse" not in litellm.failure_callback:
            litellm.failure_callback.append("langfuse")

        logger.info(f"✅ [Observability] Langfuse Integration Enabled (Lib v{version})")

    except ImportError:
        logger.error("❌ [Observability] Library 'langfuse' not found. Run `uv add 'langfuse>=2.59.7,<3.0.0'`")
    except Exception as e:
        logger.error(f"❌ [Observability] Setup Failed: {str(e)}")
