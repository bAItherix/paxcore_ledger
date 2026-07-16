from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime

class AgentInput(BaseModel):
    query: str
    session_id: str
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)

class AgentState(BaseModel):
    session_id: str
    query: str
    timestamp: datetime = Field(default_factory=datetime.now)
    memory_vector: Optional[list] = Field(default_factory=list)
    safety_cleared: bool = False