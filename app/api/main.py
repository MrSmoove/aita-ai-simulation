from fastapi import FastAPI
from app.api.routers import posts, simulate

app = FastAPI(title="AITA AI Simulation Prototype")

app.include_router(posts.router)
app.include_router(simulate.router)


@app.on_event("startup")
def startup():
    from app.services import storage
    storage.init_db()