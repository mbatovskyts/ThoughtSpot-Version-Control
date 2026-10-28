// Run UI for the migration pipeline. Talks to the GitHub REST API from the browser with the
// user's own token. All text from the API goes into the page with textContent, never innerHTML.
(function () {
  "use strict";
  const L = window.UiLib;
  const $ = (id) => document.getElementById(id);
  const API = "https://api.github.com";
  let repo = null;
  let token = "";
  let timer = null;
  let connected = false;
  const VIEWS = ["migrations", "approvals", "reports", "restore", "settings"];

  // ---------------------------------------------------------------- navigation
  function currentView() {
    const v = (location.hash.replace(/^#\/?/, "") || "migrations").split("/")[0];
    if (!connected) return "settings";
    return VIEWS.includes(v) ? v : "migrations";
  }
  function route() {
    const view = currentView();
    document.querySelectorAll(".view").forEach((s) => { s.hidden = s.dataset.view !== view; });
    document.querySelectorAll("[data-nav]").forEach((a) => {
      if (a.dataset.nav === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    document.title = view.charAt(0).toUpperCase() + view.slice(1) + " · ThoughtSpot Migration";
    if (view === "reports" && connected && !$("report-run").options.length) loadReportRuns();
  }
  function go(view) { location.hash = "#/" + view; route(); }

  // ---------------------------------------------------------------- storage
  function store(kind) { try { return window[kind]; } catch (e) { return null; } }
  function getItem(kind, key) { const s = store(kind); try { return s ? s.getItem(key) : null; } catch (e) { return null; } }
  function setItem(kind, key, v) { const s = store(kind); try { if (s) s.setItem(key, v); } catch (e) { /* storage blocked */ } }
  function delItem(kind, key) { const s = store(kind); try { if (s) s.removeItem(key); } catch (e) { /* storage blocked */ } }

  // ---------------------------------------------------------------- dom helpers
  function el(tag, props, ...kids) {
    const n = document.createElement(tag);
    Object.entries(props || {}).forEach(([k, v]) => {
      if (k === "class") n.className = v;
      else if (k === "onclick") n.addEventListener("click", v);
      else if (v !== undefined && v !== false) n.setAttribute(k, v === true ? "" : v);
    });
    kids.flat().forEach((k) => { if (k != null) n.append(k.nodeType ? k : document.createTextNode(String(k))); });
    return n;
  }
  function badge(state) { return el("span", { class: "badge " + state.tone }, state.label); }
  function link(url, text) { const u = L.safeUrl(url); return u ? el("a", { href: u, target: "_blank", rel: "noopener noreferrer" }, text) : text; }
  function setMsg(id, text, tone) { const n = $(id); n.textContent = text || ""; n.className = "msg" + (tone ? " " + tone : ""); }
  function empty(box, text) { box.replaceChildren(el("p", { class: "empty" }, text)); }

  // ---------------------------------------------------------------- api
  async function gh(path, opts) {
    const o = opts || {};
    const res = await fetch(API + path, {
      method: o.method || "GET",
      headers: Object.assign({
        "Authorization": "Bearer " + token,
        "Accept": o.raw ? "application/vnd.github.raw+json" : "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      }, o.body ? { "Content-Type": "application/json" } : {}),
      body: o.body ? JSON.stringify(o.body) : undefined,
    });
    if (!res.ok) {
      let msg = res.statusText;
      try { const j = await res.json(); if (j && j.message) msg = j.message; } catch (e) { /* not json */ }
      const err = new Error(res.status + " " + msg);
      err.status = res.status;
      throw err;
    }
    if (res.status === 204) return null;
    return o.raw ? res.text() : res.json();
  }
  const base = () => "/repos/" + repo.full;

  // ---------------------------------------------------------------- connect
  async function connect() {
    $("repo").value = L.normalizeRepo($("repo").value, location.hostname);
    repo = L.parseRepo($("repo").value);
    token = $("token").value.trim();
    if (!repo) return setMsg("connect-msg", "Enter the repository as owner/repo.", "bad");
    if (!token) return setMsg("connect-msg", "Paste a GitHub token.", "bad");
    setMsg("connect-msg", "Connecting…");
    try {
      await gh(base());
      const orgs = L.orgKeys(await gh(base() + "/contents/config/orgs?ref=" + L.PROD_BRANCH));
      if (!orgs.length) throw new Error("No org config found in config/orgs on " + L.PROD_BRANCH);
      fillOrgs(orgs);
    } catch (e) {
      return setMsg("connect-msg", "Could not connect: " + e.message + (e.status === 404 ? " (check the repository name and that the token can read it)" : ""), "bad");
    }
    const kind = $("remember").checked ? "localStorage" : "sessionStorage";
    delItem("localStorage", "tsui.token"); delItem("sessionStorage", "tsui.token");
    setItem(kind, "tsui.token", token);
    setItem("localStorage", "tsui.repo", repo.full);
    setMsg("connect-msg", "Connected to " + repo.full + ".", "ok");
    connected = true;
    $("conn-chip").textContent = repo.full; $("conn-chip").hidden = false;
    $("open-start").hidden = false;
    $("report-run").replaceChildren();
    if (location.hash === "" || location.hash === "#/settings") go("migrations"); else route();
    await refresh();
    schedule();
  }

  function forget() {
    delItem("localStorage", "tsui.token"); delItem("sessionStorage", "tsui.token");
    token = ""; $("token").value = ""; connected = false;
    $("conn-chip").hidden = true; $("open-start").hidden = true; $("nav-count").hidden = true;
    clearTimeout(timer);
    go("settings");
    setMsg("connect-msg", "Token forgotten.");
  }

  function fillOrgs(orgs) {
    for (const id of ["org", "report-org"]) {
      const sel = $(id);
      const opts = orgs.map((o) => el("option", { value: o }, o));
      if (id === "org" && orgs.length > 1) opts.push(el("option", { value: "all" }, "all orgs"));
      sel.replaceChildren(...opts);
    }
  }

  // ---------------------------------------------------------------- start a run
  async function start() {
    const org = $("org").value;
    const dry = $("dry").checked;
    let body;
    try { body = L.dispatchBody(org, dry); } catch (e) { return setMsg("start-msg", e.message, "bad"); }
    if (!dry && !window.confirm("Start a LIVE migration of '" + org + "'?\n\nIt exports from the source org, opens a promote PR, waits for you to merge it, then imports into the target.")) return;
    $("start-btn").disabled = true;
    setMsg("start-msg", "Starting…");
    try {
      await gh(base() + "/actions/workflows/" + L.WORKFLOW_FILE + "/dispatches", { method: "POST", body: body });
      setMsg("start-msg", (dry ? "Dry run" : "Live run") + " queued for " + org + ". It appears under Recent runs in a few seconds.", "ok");
      setTimeout(() => { closeStart(); go("migrations"); }, 1200);
      setTimeout(refresh, 4000);
    } catch (e) {
      setMsg("start-msg", "Could not start the run: " + e.message + (e.status === 403 || e.status === 404 ? " (the token needs Actions: read and write)" : ""), "bad");
    } finally {
      $("start-btn").disabled = false;
    }
  }

  function openStart() { setMsg("start-msg", ""); const d = $("start-dialog"); if (!d.open) d.showModal(); }
  function closeStart() { const d = $("start-dialog"); if (d.open) d.close(); }

  // ---------------------------------------------------------------- refresh
  async function refresh() {
    if (!repo || !token) return;
    await Promise.all([loadRuns(), loadPrs(), loadTags()]);
  }

  async function loadRuns() {
    const box = $("runs");
    try {
      const data = await gh(base() + "/actions/workflows/" + L.WORKFLOW_FILE + "/runs?per_page=8");
      const runs = data.workflow_runs || [];
      if (!runs.length) { $("tile-latest").textContent = "–"; $("tile-latest-sub").textContent = "No runs yet"; return empty(box, "No runs yet."); }
      const latest = L.runState(runs[0]);
      $("tile-latest").textContent = latest.label.charAt(0).toUpperCase() + latest.label.slice(1);
      $("tile-latest-sub").textContent = "Run #" + runs[0].run_number + " · " + L.ago(runs[0].created_at);
      const active = runs.filter(L.isActive).slice(0, 2);
      const jobsById = {};
      await Promise.all(active.map(async (r) => {
        try { jobsById[r.id] = (await gh(base() + "/actions/runs/" + r.id + "/jobs?per_page=30")).jobs; } catch (e) { /* show the run without detail */ }
      }));
      box.replaceChildren(...runs.map((r) => runItem(r, jobsById[r.id])));
    } catch (e) {
      box.replaceChildren(el("p", { class: "msg bad" }, "Could not load runs: " + e.message));
    }
  }

  function runItem(run, jobs) {
    const state = L.runState(run);
    const dry = /dry/i.test(run.display_title || "") ? " (dry run)" : "";
    const meta = ["#" + run.run_number, L.ago(run.created_at), run.actor && run.actor.login].filter(Boolean).join(" · ");
    const kids = [el("div", { class: "title" }, "Run #" + run.run_number, dry, badge(state)), el("div", { class: "meta" }, meta)];
    if (jobs) {
      const p = L.progress(jobs);
      kids.push(el("div", { class: "meta" },
        p.waitingForMerge ? "Waiting for you to merge the promote PR (see Approvals)." :
        p.job ? p.job + (p.step ? " · " + p.step : "") + " (" + p.done + " of " + p.total + " jobs done)" : ""));
    }
    return el("div", { class: "item" }, el("div", { class: "main" }, kids), el("div", { class: "btns" }, link(run.html_url, "Open in GitHub")));
  }

  async function loadPrs() {
    const box = $("prs");
    try {
      const prs = L.promotePrs(await gh(base() + "/pulls?state=open&per_page=30"));
      const live = prs.filter((p) => !p.dryRun).length;
      $("tile-waiting").textContent = String(live);
      $("tile-waiting-sub").textContent = live ? "Promote PR to merge" : "Nothing needs you";
      $("nav-count").textContent = String(live); $("nav-count").hidden = !live;
      if (!prs.length) return empty(box, "Nothing is waiting.");
      box.replaceChildren(...prs.map(prItem));
    } catch (e) {
      box.replaceChildren(el("p", { class: "msg bad" }, "Could not load pull requests: " + e.message));
    }
  }

  function prItem(pr) {
    const note = el("span", { class: "msg", role: "status" });
    const btns = [el("span", {}, link(pr.url, "Review the changes"))];
    if (pr.dryRun) {
      btns.push(el("button", { class: "quiet", onclick: () => closePr(pr, note) }, "Close"));
    } else {
      btns.push(el("button", { class: "primary", onclick: () => mergePr(pr, note) }, "Merge (approve)"));
    }
    return el("div", { class: "item" },
      el("div", { class: "main" },
        el("div", { class: "title" }, "#" + pr.number + " " + pr.title, pr.dryRun ? el("span", { class: "badge idle" }, "dry run") : el("span", { class: "badge wait" }, "waiting")),
        el("div", { class: "meta" }, "org " + pr.org + " · run " + pr.runId),
        note),
      el("div", { class: "btns" }, btns));
  }

  async function mergePr(pr, note) {
    if (!window.confirm("Merge #" + pr.number + " into " + L.PROD_BRANCH + "?\n\nThis approves the promotion: the import into the target org starts right after.")) return;
    note.textContent = "Merging…"; note.className = "msg";
    try {
      await gh(base() + "/pulls/" + pr.number + "/merge", { method: "PUT", body: { merge_method: "squash" } });
      note.textContent = "Merged. The import starts within about 30 seconds."; note.className = "msg ok";
      setTimeout(refresh, 3000);
    } catch (e) {
      note.textContent = "Could not merge: " + e.message + (e.status === 405 ? " (not mergeable yet; checks may still be running or a review is required)" : ""); note.className = "msg bad";
    }
  }

  async function closePr(pr, note) {
    if (!window.confirm("Close #" + pr.number + " without merging?")) return;
    note.textContent = "Closing…"; note.className = "msg";
    try {
      await gh(base() + "/pulls/" + pr.number, { method: "PATCH", body: { state: "closed" } });
      note.textContent = "Closed."; note.className = "msg ok";
      setTimeout(refresh, 3000);
    } catch (e) {
      note.textContent = "Could not close: " + e.message; note.className = "msg bad";
    }
  }

  async function loadTags() {
    const box = $("tags");
    try {
      const tags = L.restorePoints(await gh(base() + "/tags?per_page=50"));
      $("tile-restore").textContent = tags.length ? tags[0] : "None yet";
      if (!tags.length) return empty(box, "No restore points yet. A clean live run creates one.");
      box.replaceChildren(...tags.slice(0, 10).map((t) => el("div", { class: "item" }, el("div", { class: "main" }, el("code", {}, t)))));
    } catch (e) {
      box.replaceChildren(el("p", { class: "msg bad" }, "Could not load tags: " + e.message));
    }
  }

  // ---------------------------------------------------------------- reports
  async function loadReportRuns() {
    const org = $("report-org").value;
    const sel = $("report-run");
    $("report").textContent = ""; $("counts").replaceChildren();
    try {
      const dirs = L.reportDirs(await gh(base() + "/contents/reports/" + encodeURIComponent(org) + "?ref=" + L.DEV_BRANCH));
      if (!dirs.length) { sel.replaceChildren(el("option", { value: "" }, "no reports")); return; }
      sel.replaceChildren(...dirs.slice(0, 20).map((d) => el("option", { value: d }, d)));
      loadReport();
    } catch (e) {
      sel.replaceChildren(el("option", { value: "" }, e.status === 404 ? "no reports yet" : "error"));
      if (e.status !== 404) $("report").textContent = "Could not load reports: " + e.message;
    }
  }

  async function loadReport() {
    const org = $("report-org").value;
    const dir = $("report-run").value;
    if (!dir) return;
    try {
      const text = await gh(base() + "/contents/reports/" + encodeURIComponent(org) + "/" + encodeURIComponent(dir) + "/migration_summary.txt?ref=" + L.DEV_BRANCH, { raw: true });
      const counts = L.summaryCounts(text);
      $("counts").replaceChildren(...Object.entries(counts).map(([k, v]) =>
        el("div", { class: "count" + (k === "FAILED" && v > 0 ? " bad" : "") }, el("b", {}, v), el("span", {}, k.toLowerCase()))));
      $("report").textContent = text;
    } catch (e) {
      $("counts").replaceChildren();
      $("report").textContent = "Could not load the report: " + e.message;
    }
  }

  // ---------------------------------------------------------------- refresh loop
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if (!document.hidden) await refresh();
      schedule();
    }, 20000);
  }

  // ---------------------------------------------------------------- wire up
  $("connect-btn").addEventListener("click", connect);
  $("forget-btn").addEventListener("click", forget);
  $("start-btn").addEventListener("click", start);
  $("open-start").addEventListener("click", openStart);
  $("cancel-start").addEventListener("click", closeStart);
  window.addEventListener("hashchange", route);
  $("refresh-btn").addEventListener("click", refresh);
  $("report-org").addEventListener("change", loadReportRuns);
  $("report-run").addEventListener("change", loadReport);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && repo && token) refresh(); });

  const savedRepo = getItem("localStorage", "tsui.repo");
  $("repo").value = savedRepo || L.repoFromPages(location.hostname, location.pathname);
  const savedToken = getItem("sessionStorage", "tsui.token") || getItem("localStorage", "tsui.token");
  route();
  if (savedToken) { $("token").value = savedToken; $("remember").checked = !!getItem("localStorage", "tsui.token"); if (savedRepo) connect(); }
})();
