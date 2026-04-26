"""Quick sanity check for the new action-policy fields in the latest run."""
import glob
import json
import os

p = max(glob.glob("data/runs/*.json"), key=os.path.getmtime)
d = json.load(open(p, encoding="utf-8"))
m = d.get("metadata", {})
prof = m.get("commenter_profiles", [])
votes = m.get("comment_votes", {})
tl = d.get("timeline", [])

need = ("max_top_level_comments", "max_reply_comments", "max_votes", "downvote_likelihood")
has_caps = all(all(k in x for k in need) for x in prof) if prof else False

total_down = sum(v.get("downvotes", 0) for v in votes.values())
total_up = sum(v.get("upvotes", 0) for v in votes.values())

commenters_who_commented = {a["agent_id"] for a in tl if a["role"] == "commenter"}
vote_only_agents = {p["agent_id"] for p in prof if p["agent_id"] not in commenters_who_commented}

replies = [a for a in tl if a.get("parent_comment_id") and a["role"] == "commenter"]
top_level = [a for a in tl if not a.get("parent_comment_id") and a["role"] == "commenter"]

print(f"RUN FILE     = {p}")
print(f"RUN_ID       = {d['run_id']}")
print(f"PROFILES     = {len(prof)}")
print(f"HAS_CAPS     = {has_caps}  {'PASS' if has_caps else 'FAIL'}")
print(f"UPVOTES      = {total_up}")
print(f"DOWNVOTES    = {total_down}  {'PASS' if total_down > 0 else 'none this run (random, retry if needed)'}")
print(f"TOP_LEVEL    = {len(top_level)}")
print(f"REPLIES      = {len(replies)}")
print(f"COMMENTED    = {len(commenters_who_commented)} / {len(prof)} agents")
print(f"VOTE_ONLY    = {len(vote_only_agents)} agents had no comment in timeline")
print()
print("PER-AGENT CAPS (first 5):")
for agent in prof[:5]:
    print(
        f"  {agent['agent_id']:4}  "
        f"max_top={agent['max_top_level_comments']}  "
        f"max_reply={agent['max_reply_comments']}  "
        f"max_votes={agent['max_votes']}  "
        f"activity={agent['activity_style']}"
    )

print()
if has_caps:
    print(">>> ACTION POLICY CHECK PASSED")
else:
    print(">>> ACTION POLICY CHECK FAILED - caps missing from profiles")
