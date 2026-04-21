const form = document.querySelector("#run-form");
const runFormEl = document.querySelector("#run-form");
const runSelect = document.querySelector("#run-select");
const runIdInput = document.querySelector("#run-id");
const statusEl = document.querySelector("#status");
const batchFeedEl = document.querySelector("#batch-feed");
const batchPostViewEl = document.querySelector("#batch-post-view");
const viewerEl = document.querySelector("#viewer");
const tabBatchesEl = document.querySelector("#tab-batches");
const tabRunsEl = document.querySelector("#tab-runs");
const batchMetaEl = document.querySelector("#batch-meta");
const batchSelectEl = document.querySelector("#batch-select");
const postListEl = document.querySelector("#post-list");
const feedItemTemplate = document.querySelector("#feed-item-template");
const backToBatchFeedEl = document.querySelector("#back-to-batch-feed");
const backToRunListEl = document.querySelector("#back-to-run-list");
const postTitleEl = document.querySelector("#post-title");
const postBodyEl = document.querySelector("#post-body");
const postAuthorEl = document.querySelector("#post-author");
const postCreatedEl = document.querySelector("#post-created");
const verdictBadgeEl = document.querySelector("#simulated-verdict");
const commentsListEl = document.querySelector("#comments-list");
const commentTemplate = document.querySelector("#comment-template");
const batchSourceVerdictEl = document.querySelector("#batch-source-verdict");
const batchAuthorEl = document.querySelector("#batch-author");
const batchCreatedEl = document.querySelector("#batch-created");
const batchSourceCommentsEl = document.querySelector("#batch-source-comments");
const batchSourceUrlEl = document.querySelector("#batch-source-url");
const batchTitleEl = document.querySelector("#batch-title");
const batchBodyEl = document.querySelector("#batch-body");
const batchPostScoreEl = document.querySelector("#batch-post-score");
const batchCommentsMetaEl = document.querySelector("#batch-comments-meta");
const batchCommentsListEl = document.querySelector("#batch-comments-list");

let batchRuns = [];
let activeBatch = null;

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

function formatUnixTimestamp(seconds) {
  if (!seconds) {
    return "unknown time";
  }
  return new Date(seconds * 1000).toLocaleString();
}

function setMode(mode) {
  const isBatch = mode === "batch";
  tabBatchesEl.classList.toggle("is-active", isBatch);
  tabRunsEl.classList.toggle("is-active", !isBatch);
  runFormEl.classList.toggle("hidden", isBatch);
  if (isBatch) {
    viewerEl.classList.add("hidden");
  } else {
    batchFeedEl.classList.add("hidden");
    batchPostViewEl.classList.add("hidden");
  }
}

function showBatchFeed() {
  setMode("batch");
  batchFeedEl.classList.remove("hidden");
  batchPostViewEl.classList.add("hidden");
  const postCount = activeBatch?.posts?.length ?? 0;
  setStatus(`Loaded ${postCount} generated posts from batch.`);
  const url = new URL(window.location.href);
  url.searchParams.delete("batch");
  url.searchParams.delete("post");
  window.history.replaceState({}, "", url);
}

function showBatchPost(postId) {
  const post = activeBatch?.posts?.find((item) => item.post.post_id === postId);
  if (!post) {
    setStatus(`Could not find generated post ${postId}.`, true);
    return;
  }

  setMode("batch");
  batchFeedEl.classList.add("hidden");
  batchPostViewEl.classList.remove("hidden");

  batchSourceVerdictEl.textContent = post.source_verdict || "Unknown verdict";
  batchSourceVerdictEl.classList.toggle("hidden", !post.source_verdict);
  batchAuthorEl.textContent = post.post.author || "OP";
  batchCreatedEl.textContent = formatCreatedAt(activeBatch.created_at);
  batchSourceCommentsEl.textContent = `${post.source_num_comments ?? 0} source comments`;
  batchSourceUrlEl.href = post.source_url || "#";
  batchTitleEl.textContent = post.post.title || "(untitled)";
  batchBodyEl.textContent = post.post.body || "";
  batchPostScoreEl.textContent = `${post.source_score ?? 0}`;
  batchCommentsMetaEl.textContent = `${post.timeline?.length ?? 0} generated comments in this synthetic thread`;
  renderBatchPostComments(post);
  setStatus(`Viewing generated post ${post.post.post_id}`);

  const url = new URL(window.location.href);
  url.searchParams.set("batch", activeBatch.batch_run_id);
  url.searchParams.set("post", post.post.post_id);
  window.history.replaceState({}, "", url);
}

function renderBatchPostComments(post) {
  batchCommentsListEl.innerHTML = "";
  const scores = post.metadata?.comment_scores || {};
  const winnerId = post.metadata?.verdict_comment_id || null;
  const threadItems = deriveThreadStructure(post.timeline || []);

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

    batchCommentsListEl.appendChild(fragment);
  });
}

function renderBatchFeed(batchRun) {
  activeBatch = batchRun;
  postListEl.innerHTML = "";
  batchMetaEl.textContent = `${batchRun.posts.length} generated posts in this batch`;

  batchRun.posts.forEach((post) => {
    const fragment = feedItemTemplate.content.cloneNode(true);
    const buttonEl = fragment.querySelector(".feed-item-button");
    const scoreEl = fragment.querySelector(".feed-score");
    const topicEl = fragment.querySelector(".feed-topic");
    const commentsCountEl = fragment.querySelector(".feed-comments-count");
    const titleEl = fragment.querySelector(".feed-title");
    const bodyPreviewEl = fragment.querySelector(".feed-body-preview");
    const authorEl = fragment.querySelector(".feed-author");
    const verdictEl = fragment.querySelector(".feed-verdict");
    const simMetaEl = fragment.querySelector(".feed-sim-meta");

    scoreEl.textContent = `${post.source_score ?? 0}`;
    topicEl.textContent = post.post.topic || "aita";
    commentsCountEl.textContent = `${post.source_num_comments ?? 0} source comments`;
    titleEl.textContent = post.post.title || "(untitled)";
    bodyPreviewEl.textContent = post.post.body || "";
    authorEl.textContent = `${post.post.author || "OP"} • ${activeBatch.config.model_name}`;
    verdictEl.textContent = `Source: ${post.source_verdict || "Unknown"}`;
    simMetaEl.textContent = `Sim: ${post.metadata?.verdict_comment_id ? "generated" : "no verdict"} • ${post.simulated_config?.num_commenters ?? 0} commenters`;
    buttonEl.addEventListener("click", () => showBatchPost(post.post.post_id));

    postListEl.appendChild(fragment);
  });
}

async function fetchBatchRun(batchId) {
  const response = await fetch(`../data/batch_runs/${batchId}.json`);
  if (!response.ok) {
    throw new Error(`Could not load batch run ${batchId}.`);
  }
  return response.json();
}

async function loadBatchOptions() {
  const response = await fetch("../data/batch_runs/");
  if (!response.ok) {
    throw new Error("Unable to read data/batch_runs directory listing.");
  }

  const html = await response.text();
  const doc = new DOMParser().parseFromString(html, "text/html");
  const batchFiles = [...doc.querySelectorAll("a")]
    .map((link) => link.getAttribute("href") || "")
    .filter((href) => href.endsWith(".json"))
    .map((href) => href.replace(/^\.\//, "").replace(/\.json$/, ""));

  batchRuns = await Promise.all(
    batchFiles.map(async (batchId) => {
      try {
        const batch = await fetchBatchRun(batchId);
        return {
          batch_run_id: batch.batch_run_id,
          created_at: batch.created_at,
          count: batch.posts?.length ?? 0,
        };
      } catch {
        return {
          batch_run_id: batchId,
          created_at: "",
          count: 0,
        };
      }
    })
  );

  batchRuns.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  batchSelectEl.innerHTML = [
    '<option value="">Select a generated batch...</option>',
    ...batchRuns.map(
      (batch) =>
        `<option value="${escapeHtml(batch.batch_run_id)}">${escapeHtml(
          `${shortRunId(batch.batch_run_id)} • ${formatCreatedAt(batch.created_at)} • ${batch.count} posts`
        )}</option>`
    ),
  ].join("");
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
  batchFeedEl.classList.add("hidden");
  batchPostViewEl.classList.add("hidden");
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
    setMode("runs");
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

tabBatchesEl.addEventListener("click", () => showBatchFeed());
tabRunsEl.addEventListener("click", () => {
  setMode("runs");
  viewerEl.classList.add("hidden");
  batchFeedEl.classList.add("hidden");
  batchPostViewEl.classList.add("hidden");
  setStatus("Choose a simulation run to load a local JSON file.");
});

backToBatchFeedEl.addEventListener("click", () => showBatchFeed());
backToRunListEl.addEventListener("click", () => {
  setMode("runs");
  viewerEl.classList.add("hidden");
  setStatus("Choose a simulation run to load a local JSON file.");
});

batchSelectEl.addEventListener("change", async (event) => {
  const batchId = event.target.value;
  if (!batchId) {
    return;
  }
  const batch = await fetchBatchRun(batchId);
  renderBatchFeed(batch);
  showBatchFeed();
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
const initialBatchId = params.get("batch");
const initialPostId = params.get("post");

Promise.all([loadRunOptions(), loadBatchOptions()])
  .then(() => {
    if (initialBatchId) {
      batchSelectEl.value = initialBatchId;
      return fetchBatchRun(initialBatchId).then((batch) => {
        renderBatchFeed(batch);
        if (initialPostId) {
          showBatchPost(initialPostId);
          return;
        }
        showBatchFeed();
      });
    }

    if (batchRuns.length > 0) {
      batchSelectEl.value = batchRuns[0].batch_run_id;
      return fetchBatchRun(batchRuns[0].batch_run_id).then((batch) => {
        renderBatchFeed(batch);
        showBatchFeed();
      });
    }

    if (initialPostId) {
      setStatus("No batch runs available for requested post.", true);
      return;
    }

    if (initialRunId) {
      runIdInput.value = initialRunId;
      runSelect.value = initialRunId;
      loadRun(initialRunId);
      return;
    }

    setStatus("No generated batch runs found yet. Run scripts/run_scraped_batch.py first.");
  })
  .catch((error) => {
    setStatus(error.message, true);
  });
