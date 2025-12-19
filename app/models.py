from sqlmodel import Field, SQLModel
from typing import Optional
from datetime import datetime
import time

# --- CONFIG MODELS ---

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
    
    # Limits
    rate_limit: Optional[int] = Field(default=None, nullable=True)
    usage_limit: Optional[int] = Field(default=None, nullable=True)

class AdminSession(SQLModel, table=True):
    session_id: str = Field(primary_key=True, index=True)
    created_at: float = Field(default_factory=lambda: time.time())
    expires_at: float

# --- GROUP MODELS ---

class ModelGroup(SQLModel, table=True):
    """
    Nhóm model. ID lưu trong DB là tên gốc (VD: 'gpt-4-ha-noi').
    Client khi gọi sẽ thêm prefix 'group/' (VD: 'group/gpt-4-ha-noi').
    """
    id: str = Field(primary_key=True, index=True) 
    description: Optional[str] = None
    balance_strategy: str = Field(default="random") # random, round_robin, weighted

class GroupMember(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: str = Field(foreign_key="modelgroup.id", index=True)
    
    # Model thực tế sẽ gửi tới provider
    target_model: str 
    
    # Provider xử lý
    provider_name: str = Field(foreign_key="provider.name") 
    
    weight: int = Field(default=1)

# --- LOG MODELS (Updated to SQLModel) ---

class RequestLog(SQLModel, table=True):
    __tablename__ = "request_logs"
    
    id: Optional[int] = Field(default=None, primary_key=True, index=True)
    ts: datetime = Field(default_factory=datetime.utcnow)
    
    # Model client gửi lên (VD: group/my-gpt)
    model: str 
    
    # Model thực tế xử lý (VD: openai/gpt-4-turbo) -> MỚI
    real_model: Optional[str] = Field(default=None, nullable=True)
    
    provider_name: Optional[str] = Field(default=None, nullable=True)
    status: str # success, fail, processing
    latency: float = Field(default=0.0)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    ip: Optional[str] = None
    app_name: Optional[str] = None