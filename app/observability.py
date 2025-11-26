import os
import litellm
from app.config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

def setup_observability():
    """
    Cấu hình Langfuse cho LiteLLM.
    Có cơ chế bắt lỗi để không làm sập server nếu sai phiên bản thư viện.
    """
    # 1. Kiểm tra cấu hình
    if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        print("ℹ️ [Observability] Langfuse keys not found. Skipping.")
        return

    # 2. Thiết lập biến môi trường (LiteLLM tự động đọc cái này)
    os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
    os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY
    os.environ["LANGFUSE_HOST"] = LANGFUSE_HOST

    # 3. Kích hoạt Callback trong LiteLLM
    try:
        # Thử import langfuse để xem có thư viện chưa
        import langfuse
        
        # Đăng ký callback
        if "langfuse" not in litellm.success_callback:
            litellm.success_callback.append("langfuse")
        
        if "langfuse" not in litellm.failure_callback:
            litellm.failure_callback.append("langfuse")
            
        print(f"✅ [Observability] Langfuse Enabled (v{langfuse.version.__version__})")
        
    except ImportError:
        print("⚠️ [Observability] 'langfuse' library not installed. Run 'uv add langfuse'.")
    except Exception as e:
        # Bắt lỗi sdk_integration hoặc các lỗi init khác
        print(f"⚠️ [Observability] Failed to initialize Langfuse: {e}")
        print("👉 Tip: Hãy cập nhật langfuse: 'uv add langfuse>=2.39.0'")
        
        # Gỡ bỏ khỏi callback để tránh lỗi liên tục khi chat
        if "langfuse" in litellm.success_callback:
            litellm.success_callback.remove("langfuse")
