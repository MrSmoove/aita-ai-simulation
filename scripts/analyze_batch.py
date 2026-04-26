import sys, json
from pathlib import Path

batch_id = sys.argv[1] if len(sys.argv) > 1 else None
if not batch_id:
    files = sorted(Path("data/batch_runs").glob("*.json"))
    batch_file = files[-1]
else:
    batch_file = Path(f"data/batch_runs/{batch_id}.json")

data = json.load(open(batch_file, encoding="utf-8"))
posts = data["posts"]
acc = data["config"].get("accuracy", {})

print(f"Batch: {data['batch_run_id']}")
print(f"Accuracy: {acc.get('correct')}/{acc.get('total')} = {acc.get('rate', 0)*100:.1f}%")
print(f"Providers: {data['config'].get('provider_distribution')}")
print()
print(f"{'':2} {'REAL':4}  {'AI':4}  {'TALLY':<30}  TITLE")
print("-" * 90)
for p in posts:
    ai = (p.get("metadata") or {}).get("verdict_label") or "N/A"
    real = p.get("source_verdict") or "?"
    match = p.get("verdict_match")
    tally = str((p.get("metadata") or {}).get("verdict_tally", {}))
    title = p["post"]["title"][:50]
    icon = "OK" if match else ("XX" if match is False else "--")
    print(f"{icon} {real:4}  {ai:4}  {tally:<30}  {title}")
