const form = document.querySelector("#run-form");
const runSelect = document.querySelector("#run-select");
const runIdInput = document.querySelector("#run-id");
const statusEl = document.querySelector("#status");
const viewerEl = document.querySelector("#viewer");
const postTitleEl = document.querySelector("#post-title");
const postBodyEl = document.querySelector("#post-body");
const postAuthorEl = document.querySelector("#post-author");
const postCreatedEl = document.querySelector("#post-created");
const verdictBadgeEl = document.querySelector("#simulated-verdict");
const commentsListEl = document.querySelector("#comments-list");
const commentTemplate = document.querySelector("#comment-template");

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.style.color = isError ? "#b42318" : "";
}

function formatRole(action) {
  if (action.role === "op") {
    return "OP";
  }
  return action.agent_id || action.role || "comment";
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function shortRunId(runId) {
  return runId ? runId.slice(0, 8) : "unknown";
}

function formatCreatedAt(createdAt) {
  if (!createdAt) {
    return "unknown time";
  }

  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) {
    return createdAt;
  }

  return date.toLocaleString();
}

function buildRunLabel(run) {
  const postId = run.post?.post_id || "unknown-post";
  const title = run.post?.title || "(untitled)";
  const createdAt = formatCreatedAt(run.created_at);
  return `${postId} • ${title} • ${createdAt} • ${shortRunId(run.run_id)}`;
}

function deriveThreadStructure(timeline) {
  const items = timeline || [];
  const byId = new Map(items.filter((item) => item.comment_id).map((item) => [item.comment_id, item]));

  return items.map((action) => {
    const item = { ...action, depth: 0, replyLabel: "" };
    const parentId = action.parent_comment_id;

    if (!parentId) {
      item.replyLabel = action.role === "op" ? "Original poster" : "Top-level reply";
      return item;
    }

    const parent = byId.get(parentId);
    if (!parent) {
      item.replyLabel = "Reply";
      return item;
    }

    let depth = 1;
    let cursor = parent;
    while (cursor?.parent_comment_id) {
      depth += 1;
      cursor = byId.get(cursor.parent_comment_id);
    }

    item.depth = Math.min(depth, 2);
    item.replyLabel = parent.role === "op" ? "Replying to OP" : `Replying to ${formatRole(parent)}`;
    return item;
  });
}

function renderRun(run) {
  const scores = run.metadata?.comment_scores || {};
  const winnerId = run.metadata?.verdict_comment_id || null;
  const threadItems = deriveThreadStructure(run.timeline || []);

  postTitleEl.textContent = run.post?.title || "(untitled)";
  postBodyEl.textContent = run.post?.body || "";
  postAuthorEl.textContent = run.post?.author || "u/anonymous";
  postCreatedEl.textContent = formatCreatedAt(run.created_at);

  verdictBadgeEl.classList.toggle("hidden", !winnerId);
  viewerEl.classList.remove("hidden");
  commentsListEl.innerHTML = "";

  threadItems.forEach((action, index) => {
    const fragment = commentTemplate.content.cloneNode(true);
    const shellEl = fragment.querySelector(".comment-shell");
    const roleEl = fragment.querySelector(".comment-role");
    const scoreEl = fragment.querySelector(".comment-score");
    const textEl = fragment.querySelector(".comment-text");
    const replyChipEl = fragment.querySelector(".reply-chip");
    const winnerChipEl = fragment.querySelector(".winner-chip");

    roleEl.textContent = formatRole(action);
    scoreEl.textContent = `${scores[action.comment_id] ?? 0}`;
    textEl.textContent = action.text || "";
    shellEl.classList.add(`depth-${action.depth}`);
    shellEl.style.animationDelay = `${index * 28}ms`;

    if (action.comment_id === winnerId) {
      shellEl.classList.add("winner");
      winnerChipEl.classList.remove("hidden");
    }

    if (action.replyLabel) {
      replyChipEl.textContent = action.replyLabel;
      replyChipEl.classList.remove("hidden");
    }

    commentsListEl.appendChild(fragment);
  });

  setStatus(`Loaded ${run.run_id}`);
}

async function fetchRunJson(runId) {
  const response = await fetch(`../data/runs/${runId}.json`);
  if (!response.ok) {
    throw new Error(`File not found: data/runs/${runId}.json`);
  }

  return response.json();
}

async function loadRun(runId) {
  if (!runId) {
    setStatus("Enter a run ID to load a local JSON file.", false);
    return;
  }

  setStatus(`Loading ${runId}...`);

  try {
    const run = await fetchRunJson(runId);
    renderRun(run);
    runIdInput.value = runId;
    runSelect.value = runId;
  } catch (error) {
    viewerEl.classList.add("hidden");
    setStatus(error.message, true);
  }
}

async function loadRunOptions() {
  try {
    const response = await fetch("../data/runs/");
    if (!response.ok) {
      throw new Error("Unable to read data/runs directory listing.");
    }

    const html = await response.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const runFiles = [...doc.querySelectorAll("a")]
      .map((link) => link.getAttribute("href") || "")
      .filter((href) => href.endsWith(".json"))
      .map((href) => href.replace(/^\.\//, "").replace(/\.json$/, ""));

    if (runFiles.length === 0) {
      runSelect.innerHTML = '<option value="">No local run files found</option>';
      return;
    }

    const runs = await Promise.all(
      runFiles.map(async (runId) => {
        try {
          const run = await fetchRunJson(runId);
          return { runId, label: buildRunLabel(run), createdAt: run.created_at || "" };
        } catch {
          return { runId, label: `${runId} • unreadable`, createdAt: "" };
        }
      })
    );

    runs.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());

    runSelect.innerHTML = [
      '<option value="">Select a local run...</option>',
      ...runs.map(
        (run) => `<option value="${escapeHtml(run.runId)}">${escapeHtml(run.label)}</option>`
      ),
    ].join("");
  } catch (error) {
    runSelect.innerHTML = '<option value="">Unable to list local runs</option>';
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const runId = runIdInput.value.trim();
  if (runId) {
    const url = new URL(window.location.href);
    url.searchParams.set("run", runId);
    window.history.replaceState({}, "", url);
  }
  loadRun(runId);
});

runSelect.addEventListener("change", (event) => {
  const runId = event.target.value;
  if (!runId) {
    return;
  }

  const url = new URL(window.location.href);
  url.searchParams.set("run", runId);
  window.history.replaceState({}, "", url);
  loadRun(runId);
});

const params = new URLSearchParams(window.location.search);
const initialRunId = params.get("run");
loadRunOptions().then(() => {
  if (initialRunId) {
    runIdInput.value = initialRunId;
    runSelect.value = initialRunId;
    loadRun(initialRunId);
  }
});
