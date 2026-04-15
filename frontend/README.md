# Frontend

Minimal read-only viewer for simulation runs.

## Run It

Start a simple static server from the repo root:

```bash
python3 -m http.server 8000
```

Then open:

```text
http://localhost:8000/frontend/
```

To load a specific run directly:

```text
http://localhost:8000/frontend/?run=<run_id>
```

The page reads local JSON from:

```text
data/runs/<run_id>.json
```

It also tries to auto-discover available runs from the local `data/runs/` directory and show them in a dropdown with a readable label:

```text
post_id • title • created time • short run id
```
