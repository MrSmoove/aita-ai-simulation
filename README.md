# AITA AI Simulation

Multi-agent simulation of Reddit r/AmItheAsshole threads. Agents (commenters + OP) respond to posts over multiple steps.

## Quick start

### 1. Setup (one-time)
```bash
cd aita-ai-simulation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run a simulation
```bash
python scripts/cli.py \
  --post-id my-run-1 \
  --title "AITA for eating my roommate's leftovers?" \
  --body "I was hungry and saw leftover pizza in the fridge..." \
  --num-commenters 3 \
  --max-steps 2 \
  --op-enabled
```

Output:
- JSON: `data/runs/{run_id}.json`
- DB: `data/runs.db`

### 3. View results
```bash
# Pretty-print timeline
python - <<'PY'
import json
with open("data/runs/{run_id}.json") as f:
    run = json.load(f)
    for action in run["timeline"]:
        print(f"[Step {action['step']}] {action['role']}: {action['text']}")
PY

# Query DB
sqlite3 data/runs.db "SELECT run_id, post_id, created_at FROM runs ORDER BY created_at DESC LIMIT 5;"
```

## Project structure
```
app/
  schemas.py        # Data models (Post, SimulationConfig, etc.)
  prompts.py        # Agent prompt templates (customize tone, behavior)
  storage.py        # SQLite + JSON persistence
  oasis/
    adapter.py      # LLM client (stub — needs real camel-oasis setup)
  services/
    simulation.py   # Orchestration: seed post → run agents → save
  api/
    main.py         # FastAPI (optional, for batch runs / integrations)
    routers/
      posts.py      # POST /posts/upload, GET /posts/sample
      simulate.py   # POST /simulate/run, GET /simulate/run/{run_id}

scripts/
  cli.py            # Local CLI for quick runs (recommended)
  run_one_post.py   # Example batch run

data/
  runs.db           # SQLite database (auto-created)
  runs/             # JSON exports per run
```

## Customization

### Prompt templates (agent tone, behavior)
Edit `app/prompts.py`:
- `commenter_prompt()` — what commenters see and how they respond
- `op_reply_prompt()` — what OP sees when replying
- `system_prompt()` — global instructions (e.g., be sarcastic, be formal)

Example: change commenters to be more formal:
```python
# app/prompts.py
def commenter_prompt(post_title: str, post_body: str, context: str = "") -> str:
    prompt = f"""You are a formal Reddit commenter. Respond professionally and objectively.

Post: {post_title}
{post_body}

Your formal 1-liner:"""
    return prompt
```

### CLI options
```bash
python scripts/cli.py --help
```

All options:
- `--post-id` — unique run identifier
- `--title`, `--body`, `--author` — post content
- `--num-commenters` — how many commenter agents (default 3)
- `--max-steps` — how many reply rounds (default 2)
- `--op-enabled` — whether OP replies (default true)
- `--model` — model name for agents (default "oasis-small")
- `--output` — JSON output path (default `data/runs/{run_id}.json`)

## Next steps

### 1. Wire up real LLM (REQUIRED for real responses)
Currently agents return stubs. To enable real LLM generation:
1. Get camel-oasis GitHub link / API keys
2. Update `app/oasis/adapter.py` with real client
3. Set env vars: `export OASIS_API_KEY=...`

### 2. Batch runs (optional)
- Use FastAPI backend: `uvicorn app.api.main:app --port 8000`
- POST to `/simulate/run` with post + config JSON
- Poll `/simulate/run/{run_id}` for results

### 3. Analysis / export (optional)
- Query `data/runs.db` for aggregated stats
- Export timelines to CSV for further analysis

## Troubleshooting

**ModuleNotFoundError: No module named 'app'**
```bash
export PYTHONPATH=$(pwd)
python scripts/cli.py
```

**datetime is not JSON serializable**
- Already fixed; ensure `app/services/simulation.py` converts `created_at` to ISO string

**Agents returning stubs**
- Expected until real LLM is wired. See "Wire up real LLM" above.

## Team workflow

1. **Edit prompts** → `app/prompts.py` (customize agent tone/behavior)
2. **Run local test** → `python scripts/cli.py --title "..." --body "..."`
3. **Check results** → `cat data/runs/{run_id}.json | jq .timeline`
4. **Commit & push** → `git add .; git commit -m "..."; git push`

Questions? Check `scripts/cli.py --help` or open an issue.
