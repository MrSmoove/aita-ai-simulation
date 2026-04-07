from fastapi import APIRouter, UploadFile, File, HTTPException
import json
from app.schemas import Post

router = APIRouter(prefix="/posts", tags=["posts"])


@router.post("/upload", response_model=Post)
async def upload_post(file: UploadFile = File(...)):
    try:
        raw = await file.read()
        decoded = json.loads(raw)
        post = Post(**decoded)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON post file: {e}")
    # for this prototype we just return validated post; client will pass it to /simulate
    return post


@router.get("/sample", response_model=Post)
async def sample_post():
    sample = {
        "post_id": "sample-1",
        "title": "Am I the asshole for refusing to eat my partner's sandwich?",
        "body": "My partner ate my sandwich without asking...",
        "true_verdict": "NTA",
        "topic": "relationship",
        "author": "u/sampleuser",
    }
    return Post(**sample)