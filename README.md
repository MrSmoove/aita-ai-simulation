## Professor Quick Reproduction Guide (Windows)

This is the shortest reliable path to run one batch, analyze it, and export spreadsheet rows.

### Step 1. Open PowerShell and enter the project folder

```powershell
git clone <repo-url>
cd aita-ai-simulation
```

If the repo is already cloned, just run the second line.

### Step 2. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### Step 3. Environment file

This repository already includes a .env file.

If API keys are expired or out of credits, batch runs will fail at generation time.

### Step 4. Run one comparable batch

Copy/paste exactly:

```powershell
python scripts/run_scraped_batch.py --source data/reddit/aita_posts_balanced_50_50.json --provider-strategy balanced --timeline-mode 24h --max-steps 6 --commenter-cap 30 --voter-ratio 1.0 --commenter-min 1 --commenter-scale-power 0.5 --mobility 1.0 --concurrency 4
```

You should see output that includes all of the following:
- Batch ID
- Saved to data/batch_runs/<batch_id>.json
- Accuracy line

### Step 5. Analyze the newest batch

```powershell
python scripts/analyze_batch.py
```

This prints:
- Config tracker row
- Results tracker row
- Mismatch and verdict summaries

### Step 6. Export spreadsheet rows

```powershell
python scripts/analyze_batch.py --write-csv data/batch_analysis
```

Creates:
- data/batch_analysis/config_row.csv
- data/batch_analysis/results_row.csv

### Step 7. Optional run-to-run comparison

Last 5 runs:

```powershell
python scripts/compare_runs.py --last 5
```

Specific run IDs:

```powershell
python scripts/compare_runs.py <batch_id_1> <batch_id_2>
```

### Step 8. Optional frontend viewer

```powershell
bash scripts/serve_frontend.sh
```

Open in browser:

```text
http://localhost:8000/frontend/
```

### Troubleshooting

- If python is not found, replace python with py in all commands.
- If API calls fail, verify .env exists in project root and has valid keys.
- If you see ModuleNotFoundError for pydantic_core, reinstall:

```powershell
python -m pip install --upgrade pip
python -m pip install --no-cache-dir --force-reinstall --only-binary=:all: pydantic-core==2.46.3 pydantic==2.13.3
```

### Meaning of the main batch flags

- --concurrency: number of posts simulated in parallel.
- --provider-strategy balanced: rotate across available providers.
- --provider-strategy single --provider openai --model gpt-4.1-mini: force one provider/model.
- --timeline-mode 24h: six-wave first-day lifecycle.
- --voter-ratio: voter agents per commenter agent.
- --mobility: how freely agents return/engage between waves.
- --commenter-scale-power and --commenter-min: map real comment count to simulated commenters.

