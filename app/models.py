from sqlmodel import Field, SQLModel
from typing import Optional

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
