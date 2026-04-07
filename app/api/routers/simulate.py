from fastapi import APIRouter, BackgroundTasks, HTTPException
from app.schemas import Post, SimulationConfig
from app.services import simulation
from app.services import storage

router = APIRouter(prefix="/simulate", tags=["simulate"])


@router.post("/run")
async def start_simulation(post: Post, config: SimulationConfig, background_tasks: BackgroundTasks):
    # Validate DB exists
    storage.init_db()
    # Kick off background task so API returns quickly
    background_tasks.add_task(simulation.run_single_post, post, config)
    return {"status": "started", "post_id": post.post_id}


@router.get("/run/{run_id}")
async def get_run(run_id: str):
    data = storage.load_run_db(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return data