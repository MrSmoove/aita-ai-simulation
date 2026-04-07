from __future__ import annotations

from camel.models import ModelFactory
from camel.types import ModelPlatformType, ModelType

import oasis
from oasis import ActionType, generate_reddit_agent_graph


def build_model():
    return ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=ModelType.GPT_4O_MINI,
    )


def build_actions():
    return [
        ActionType.CREATE_COMMENT,
        ActionType.LIKE_COMMENT,
        ActionType.DISLIKE_COMMENT,
        ActionType.SEARCH_POSTS,
        ActionType.REFRESH,
        ActionType.DO_NOTHING,
    ]


async def build_agent_graph(profile_path: str, model):
    return await generate_reddit_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=build_actions(),
    )


def make_env(agent_graph, db_path: str):
    return oasis.make(
        agent_graph=agent_graph,
        platform=oasis.DefaultPlatformType.REDDIT,
        database_path=db_path,
    )