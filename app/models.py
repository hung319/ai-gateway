from sqlmodel import Field, SQLModel
from typing import Optional
import time

class Provider(SQLModel, table=True):
    name: str = Field(primary_key=True, index=True)
    api_key: str
    base_url: Optional[str] = None
    provider_type: str = "openai"

class GatewayKey(SQLModel, table=True):
    key: str = Field(primary_key=True, index=True)
    name: str = Field(default="Client App")
    usage_count: int = Field(default=0)
    is_active: bool = Field(default=True)
    is_hidden: bool = Field(default=False)

# --- MỚI: BẢNG QUẢN LÝ SESSION ---
class AdminSession(SQLModel, table=True):
    session_id: str = Field(primary_key=True, index=True)
    created_at: float = Field(default_factory=lambda: time.time())
    expires_at: float # Session sẽ hết hạn sau 1 khoảng thời gian
