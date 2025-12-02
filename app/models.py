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

class AdminSession(SQLModel, table=True):
    session_id: str = Field(primary_key=True, index=True)
    created_at: float = Field(default_factory=lambda: time.time())
    expires_at: float

class ModelMap(SQLModel, table=True):
    source_model: str = Field(primary_key=True, index=True) # VD: gpt-4
    target_model: str # VD: openai/gpt-4-turbo
