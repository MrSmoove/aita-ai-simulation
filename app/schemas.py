from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from enum import Enum
from datetime import datetime


class Post(BaseModel):
    post_id: str
    title: str
    body: str
    true_verdict: Optional[str] = None
    topic: Optional[str] = None
    author: Optional[str] = None


class SimulationConfig(BaseModel):
    model_name: str = "oasis-small"
    num_commenters: int = Field(3, ge=1, le=20)
    max_steps: int = Field(3, ge=1, le=50)
    op_enabled: bool = True


class AgentAction(BaseModel):
    agent_id: str
    text: str
    step: int
    role: str  # "commenter" or "op"


class SimulationRun(BaseModel):
    run_id: str
    post: Post
    config: SimulationConfig
    timeline: List[AgentAction]
    created_at: datetime
    metadata: Optional[Dict] = None