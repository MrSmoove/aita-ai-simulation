<<<<<<< HEAD
# aita-ai-simulation
=======
# AITA AI Simulation

Simulating Reddit r/AmITheAsshole discussions using AI agents and comparing results to real human behavior.

## Features
- AI-generated Reddit threads
- OP agent interaction
- Multi-agent simulation using OASIS
- Verdict comparison (AI vs human)

## Setup

```bash
git clone <repo-url>
cd aita-ai-simulation
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Minimal prototype: FastAPI backend + Streamlit frontend for AITA simulation.

Run backend:
  cd aita-ai-simulation
  uvicorn app.api.main:app --reload --port 8000

Run frontend:
  streamlit run frontend/streamlit_app.py --server.port 8501

Data:
  - SQLite DB is created at data/runs.db
  - JSON run exports saved to data/runs/{run_id}.json
>>>>>>> daeb5d8 (chore: intial prototype)
