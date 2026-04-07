from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import posts, simulate

app = FastAPI(title="AITA AI Simulation Prototype")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(posts.router)
app.include_router(simulate.router)


@app.on_event("startup")
def startup():
    from app.services import storage

    storage.init_db()