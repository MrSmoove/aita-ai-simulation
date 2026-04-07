from fastapi import APIRouter, BackgroundTasks, HTTPException
from app.schemas import Post, SimulationConfig
from app.services import simulation, storage
import uuid
import asyncio

router = APIRouter(prefix="/simulate", tags=["simulate"])


@router.post("/run")
async def start_simulation(post: Post, config: SimulationConfig, background_tasks: BackgroundTasks):
    storage.init_db()
    run_id = str(uuid.uuid4())

    # schedule the async coroutine properly from BackgroundTasks by using a sync wrapper
    def _schedule(post_dict, config_dict, run_id):
        asyncio.create_task(simulation.run_single_post(Post(**post_dict), SimulationConfig(**config_dict), run_id=run_id))

    background_tasks.add_task(_schedule, post.dict(), config.dict(), run_id)
    return {"status": "started", "run_id": run_id, "post_id": post.post_id}


@router.get("/run/{run_id}")
async def get_run(run_id: str):
    data = storage.load_run_db(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return data