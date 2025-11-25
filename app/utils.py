import httpx
from sqlmodel import select, Session
from fastapi import HTTPException
from app.models import Provider
from app.config import MODEL_FETCH_TIMEOUT

async def fetch_provider_models(client: httpx.AsyncClient, provider: Provider):
    """
    Hàm đa năng để lấy danh sách model từ Provider.
    Hỗ trợ:
    1. Google Gemini (Native API)
    2. OpenAI Standard (OpenAI, OpenRouter, Azure, Local...)
    """
    fetched_ids = []
    current_time = 1700000000 # Dummy timestamp

    # --- CASE 1: GOOGLE GEMINI (Native API) ---
    # Google dùng cấu trúc JSON khác hoàn toàn chuẩn OpenAI
    if provider.provider_type == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={provider.api_key}"
        try:
            resp = await client.get(url, timeout=MODEL_FETCH_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                # Google trả về: { "models": [ { "name": "models/gemini-1.5-flash", ... } ] }
                if "models" in data:
                    for item in data["models"]:
                        # Cắt bỏ prefix 'models/' để gọn
                        model_name = item.get("name", "").replace("models/", "")
                        if model_name: 
                            fetched_ids.append(model_name)
        except Exception as e:
            print(f"Error fetching Gemini: {e}")

    # --- CASE 2: OPENAI STANDARD ---
    else:
        api_base = provider.base_url
        
        # Cấu hình URL mặc định nếu người dùng để trống
        if not api_base:
            if provider.provider_type == "openrouter": 
                api_base = "https://openrouter.ai/api/v1"
            elif provider.provider_type == "openai": 
                api_base = "https://api.openai.com/v1"
            else: 
                return [] # Không đoán mò nếu là custom provider mà thiếu URL

        # Chuẩn hóa URL (đảm bảo có /v1 ở cuối)
        api_base = api_base.rstrip('/')
        if not api_base.endswith("/v1"): 
            api_base = f"{api_base}/v1"
        
        url = f"{api_base}/models"
        
        headers = {
            "Authorization": f"Bearer {provider.api_key}", 
            "Content-Type": "application/json"
        }
        
        # OpenRouter yêu cầu thêm Header nhận diện
        if provider.provider_type == "openrouter": 
            headers["HTTP-Referer"] = "gateway"
            headers["X-Title"] = "AI Gateway"

        try:
            resp = await client.get(url, headers=headers, timeout=MODEL_FETCH_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                # Chuẩn OpenAI: { "data": [ { "id": "gpt-4", ... } ] }
                if "data" in data:
                    for item in data["data"]:
                        if "id" in item: 
                            fetched_ids.append(item["id"])
        except Exception as e:
            print(f"Error fetching {provider.name}: {e}")

    # Format kết quả trả về chung cho Gateway
    return [
        {
            "id": f"{provider.name}/{m_id}", # alias/model_name
            "object": "model", 
            "created": current_time, 
            "owned_by": provider.provider_type,
            "permission": []
        } 
        for m_id in fetched_ids
    ]

def parse_model_alias(raw_model: str, session: Session):
    """
    Phân tích tên model để tìm Provider tương ứng.
    Hỗ trợ Smart Routing cho Cursor (khi gửi tên model không có alias).
    """
    # Trường hợp 1: Cursor gửi tên trần (vd: "gpt-4o", "claude-3-5-sonnet")
    if "/" not in raw_model:
        providers = session.exec(select(Provider)).all()
        
        # Chiến thuật ưu tiên: OpenRouter -> Gemini -> OpenAI -> Azure
        # (Vì OpenRouter hỗ trợ routing tên model rất tốt)
        for p in providers:
            if p.provider_type == "openrouter": 
                return p, raw_model
        
        for p in providers:
            if p.provider_type in ["gemini", "openai"]: 
                return p, raw_model
            
        # Fallback: Lấy thằng provider đầu tiên tìm thấy
        if providers: 
            return providers[0], raw_model
        
        raise HTTPException(status_code=400, detail="Unknown model alias and no default provider found.")

    # Trường hợp 2: Chuẩn Gateway (vd: "google/gemini-pro")
    alias, actual_model = raw_model.split("/", 1)
    provider = session.get(Provider, alias)
    
    if not provider: 
        raise HTTPException(status_code=404, detail=f"Provider '{alias}' not found")
        
    return provider, actual_model
