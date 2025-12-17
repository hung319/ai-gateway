from sqlmodel import Field, SQLModel
from typing import Optional
import time

class Provider(SQLModel, table=True):
    name: str = Field(primary_key=True, index=True) 
    api_key: str
    base_url: Optional[str] = None 
    provider_type: str = "openai" # openai, azure, openrouter, gemini

class GatewayKey(SQLModel, table=True):
    key: str = Field(primary_key=True, index=True)
    name: str = Field(default="Client App")
    usage_count: int = Field(default=0)
    is_active: bool = Field(default=True)
    is_hidden: bool = Field(default=False)
    
    # --- New Fields for Limits ---
    rate_limit: Optional[int] = Field(default=None, nullable=True)
    usage_limit: Optional[int] = Field(default=None, nullable=True)

class AdminSession(SQLModel, table=True):
    session_id: str = Field(primary_key=True, index=True)
    created_at: float = Field(default_factory=lambda: time.time())
    expires_at: float

class ModelMap(SQLModel, table=True):
    source_model: str = Field(primary_key=True, index=True) # VD: gpt-4
    target_model: str # VD: openai/gpt-4-turbo

# --- NEW: Bảng lưu log để thống kê Dashboard ---
class RequestLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: float = Field(default_factory=lambda: time.time(), index=True)
    status: str = Field(index=True) # "success", "fail", "processing"
    model: str = Field(index=True)
    provider_name: Optional[str] = None
    latency: float = 0.0
    key_name: Optional[str] = None