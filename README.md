# AITA AI Simulation

Multi-agent simulation of Reddit r/AmItheAsshole threads comparing AI vs real human discussions.

## Quick Start

### 1. Clone & Install
```bash
git clone <repo>
cd aita-ai-simulation
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set Up Environment
```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY (default provider is OpenAI)
```

### 3. Run a Test Simulation
```bash
export PYTHONPATH=$(pwd)
./.venv/bin/python scripts/cli.py \
  --post-id test-1 \
  --title "AITA for eating my roommate's leftovers?" \
  --body "I was hungry..." \
  --num-commenters 3 \
  --max-steps 2
```

Results saved to `data/runs/<run_id>.json`, `data/runs/<run_id>.txt`, and `data/runs.db`.

Single-run options now include provider and timeline mode:

```bash
./.venv/bin/python scripts/cli.py \
  --provider openai \
  --timeline-mode 24h \
  --post-id test-1 \
  --title "AITA for eating my roommate's leftovers?" \
  --body "I was hungry..." \
  --num-commenters 12 \
  --max-steps 6
```

### 4. View a Run in the Frontend
Start the local static viewer:

```bash
./scripts/serve_frontend.sh
```

Then open:

```text
http://localhost:8000/frontend/
```

The frontend auto-discovers local runs from `data/runs/`.

Batch runs are saved separately under `data/batch_runs/` and can also be browsed from the same frontend.

### 5. Generate a Viewer Smoke Test (Optional)
This creates a small run and prints the exact viewer URL for it:

```bash
./scripts/test_viewer_run.sh
```

### 6. Start API Server (Optional)
```bash
uvicorn app.api.main:app --port 8000 --reload
# Visit http://localhost:8000/docs
```

## Batch Simulations

Run a scraped-post batch and save one combined artifact:

```bash
./.venv/bin/python scripts/run_scraped_batch.py \
  --source data/reddit/aita_posts.json \
  --provider-strategy balanced \
  --timeline-mode 24h \
  --max-steps 6 \
  --commenter-cap 50 \
  --concurrency 4
```

Notes:
- `--concurrency` controls how many posts are simulated in parallel.
- `--provider-strategy balanced` rotates available providers across posts as evenly as possible.
- `--provider-strategy single --provider openai --model gpt-4.1-mini` forces one provider/model for the whole batch.
- `--timeline-mode 24h` uses a six-wave first-day lifecycle; `basic` keeps the simpler mode.
- Each finished batch is saved to `data/batch_runs/<batch_run_id>.json`.
- The terminal now prints a single usage summary at the end instead of per-request token spam.

## Architecture

- **app/schemas.py** — Data models (Post, Comment, Agent, etc.)
- **app/services/simulation.py** — Multi-wave simulation logic
- **app/llm/adapter.py** — LLM integration (OpenAI or Gemini)
- **app/prompts.py** — Agent personality + instruction prompts
- **scripts/cli.py** — Command-line interface

## Next Steps

1. Customize agent personalities in `app/prompts.py`
2. Add real Reddit post scraping
3. Compare AI vs real verdict outcomes

## Team Notes

- All API calls are logged to `log/`
- Results stored in `data/runs.db` + JSON
