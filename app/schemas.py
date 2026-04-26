from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime


class Post(BaseModel):
    post_id: str
    title: str
    body: str
    true_verdict: Optional[str] = None
    topic: Optional[str] = None
    author: Optional[str] = None


class SimulationConfig(BaseModel):
    model_name: Optional[str] = "gpt-4.1-mini"
    provider: str = "openai"
    num_commenters: int = Field(3, ge=1, le=300)
    num_voters: int = Field(0, ge=0, le=1000)
    mobility: float = Field(1.0, ge=0.5, le=2.5)
    max_steps: int = Field(3, ge=1, le=50)
    op_enabled: bool = True
    timeline_mode: str = "basic"


class AgentAction(BaseModel):
    agent_id: str
    text: str
    step: int
    role: str  # "commenter" or "op"
    comment_id: Optional[str] = None
    parent_comment_id: Optional[str] = None
    provider: Optional[str] = None
    model_name: Optional[str] = None
    simulated_minute: Optional[int] = None
    bucket_label: Optional[str] = None
    verdict_label: Optional[str] = None  # YTA / NTA / ESH / NAH (top-level commenter comments only)


class SimulationRun(BaseModel):
    run_id: str
    post: Post
    config: SimulationConfig
    timeline: List[AgentAction]
    created_at: datetime
    metadata: Optional[Dict] = None


class BatchPostResult(BaseModel):
    post: Post
    source_num_comments: int
    source_score: Optional[int] = None
    source_verdict: Optional[str] = None
    source_top_comment: Optional[str] = None
    source_top_comment_score: Optional[int] = None
    source_url: Optional[str] = None
    simulation_provider: Optional[str] = None
    simulation_model: Optional[str] = None
    simulated_config: Dict
    timeline: List[AgentAction]
    metadata: Optional[Dict] = None
    verdict_match: Optional[bool] = None  # True if AI verdict == real Reddit verdict


class BatchRun(BaseModel):
    batch_run_id: str
    source_file: str
    created_at: datetime
    config: Dict
    posts: List[BatchPostResult]
