from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional


class ScrapedPost(BaseModel):
    post_id: str
    title: str
    body: str
    true_verdict: Optional[str] = None
    topic: Optional[str] = None
    author: Optional[str] = None


class OPAgentConfig(BaseModel):
    agent_id: str
    source_post_id: str
    grounding_text: str
    allowed_actions: list[str] = Field(default_factory=list)