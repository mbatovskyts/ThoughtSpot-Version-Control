import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const L = createRequire(import.meta.url)("./lib.js");

test("parseRepo accepts owner/repo and nothing else", () => {
  assert.equal(L.parseRepo(" a/b-c.d ").full, "a/b-c.d");
  for (const bad of ["", "a", "a/b/c", "a b/c", "https://github.com/a/b", "../x/y z"]) assert.equal(L.parseRepo(bad), null);
});

test("safeUrl only lets github.com https links through", () => {
  assert.equal(L.safeUrl("https://github.com/o/r/pull/1"), "https://github.com/o/r/pull/1");
  for (const bad of ["javascript:alert(1)", "http://github.com/x", "https://evil.com/github.com/", "", undefined, 5])
    assert.equal(L.safeUrl(bad), "");
});

test("orgKeys skips the template, hidden files and non-yaml", () => {
  const ls = [{ type: "file", name: "github.yml" }, { type: "file", name: "example.yml" },
    { type: "file", name: "_tmpl.yml" }, { type: "file", name: "notes.md" }, { type: "dir", name: "sub.yml" },
    { type: "file", name: "alpha.yml" }];
  assert.deepEqual(L.orgKeys(ls), ["alpha", "github"]);
  assert.deepEqual(L.orgKeys(undefined), []);
});

test("dispatchBody targets ts-prod and rejects odd org names", () => {
  assert.deepEqual(L.dispatchBody("github", true), { ref: "ts-prod", inputs: { org: "github", dry_run: true } });
  assert.equal(L.dispatchBody("all", false).inputs.dry_run, false);
  for (const bad of ["", "a b", "a;b", "$(x)"]) assert.throws(() => L.dispatchBody(bad, false));
});

test("runState maps status and conclusion", () => {
  assert.deepEqual(L.runState({ status: "completed", conclusion: "success" }), { label: "succeeded", tone: "ok" });
  assert.equal(L.runState({ status: "completed", conclusion: "failure" }).tone, "bad");
  assert.equal(L.runState({ status: "completed", conclusion: "cancelled" }).tone, "idle");
  assert.equal(L.runState({ status: "in_progress" }).label, "running");
  assert.equal(L.runState({ status: "queued" }).label, "queued");
  assert.equal(L.isActive({ status: "in_progress" }), true);
  assert.equal(L.isActive({ status: "completed" }), false);
});

test("progress reports the live job and spots the wait for the merge", () => {
  const jobs = [
    { name: "Extract", status: "completed", steps: [] },
    { name: "Promote", status: "in_progress", steps: [
      { name: "Stage 7 — Promote to ts-prod", status: "completed" },
      { name: "Stage 7b — Wait for PR approval and merge", status: "in_progress" }] },
    { name: "Import", status: "queued", steps: [] }];
  const p = L.progress(jobs);
  assert.equal(p.done, 1); assert.equal(p.total, 3); assert.equal(p.job, "Promote");
  assert.equal(p.waitingForMerge, true);
  assert.equal(L.progress([{ name: "Import", status: "in_progress", steps: [{ name: "Stage 9 — Import", status: "in_progress" }] }]).waitingForMerge, false);
  assert.deepEqual(L.progress([]), { done: 0, total: 0, job: "", step: "", waitingForMerge: false });
});

test("promotePrs keeps only promote branches and flags dry runs", () => {
  const prs = [
    { number: 1, title: "[github] Promote TML run 5-1", html_url: "https://github.com/o/r/pull/1", head: { ref: "promote/github/5-1", sha: "abc" } },
    { number: 2, title: "[DRY RUN] [github] Promote TML run 6-1", html_url: "https://github.com/o/r/pull/2", head: { ref: "promote/github/6-1", sha: "def" } },
    { number: 3, title: "fix", html_url: "https://github.com/o/r/pull/3", head: { ref: "claude/x", sha: "g" } }];
  const out = L.promotePrs(prs);
  assert.deepEqual(out.map((p) => [p.number, p.org, p.runId, p.dryRun]), [[1, "github", "5-1", false], [2, "github", "6-1", true]]);
  assert.equal(L.promotePrs([{ number: 9, title: "t", html_url: "javascript:x", head: { ref: "promote/a/b" } }])[0].url, "");
});

test("reportDirs is newest first and ignores files", () => {
  const ls = [{ type: "dir", name: "20261015T1_a-1" }, { type: "file", name: "x" }, { type: "dir", name: "20261027T1_b-1" }];
  assert.deepEqual(L.reportDirs(ls), ["20261027T1_b-1", "20261015T1_a-1"]);
});

test("summaryCounts reads the Total lines of the real report layout", () => {
  const text = "1. PULLED (identified for migration)\n   Total: 17\n   LIVEBOARD: 2\n\n======\n2. SUCCEEDED\n   Total: 15\n\n3. FAILED\n   Total: 2\n\n4. SKIPPED\n   Total: 0\n";
  assert.deepEqual(L.summaryCounts(text), { PULLED: 17, SUCCEEDED: 15, FAILED: 2, SKIPPED: 0 });
  assert.deepEqual(L.summaryCounts(""), {});
});

test("restorePoints keeps only migrate/<org>/<run> tags, newest first", () => {
  const tags = [{ name: "v1" }, { name: "migrate/github/40560250425-1" }, { name: "migrate/github/40572994271-1" }, { name: "migrate/a/b/c" }];
  assert.deepEqual(L.restorePoints(tags), ["migrate/github/40572994271-1", "migrate/github/40560250425-1"]);
});

test("ago formats elapsed time", () => {
  const now = Date.parse("2026-10-28T12:00:00Z");
  assert.equal(L.ago("2026-10-28T11:59:30Z", now), "30s ago");
  assert.equal(L.ago("2026-10-28T11:15:00Z", now), "45m ago");
  assert.equal(L.ago("2026-10-28T09:00:00Z", now), "3h ago");
  assert.equal(L.ago("2026-10-26T12:00:00Z", now), "2d ago");
  assert.equal(L.ago("garbage", now), "");
});

test("repoFromPages reads owner/repo from a project Pages address", () => {
  assert.equal(L.repoFromPages("mbatovskyts.github.io", "/ThoughtSpot-Version-Control/"), "mbatovskyts/ThoughtSpot-Version-Control");
  assert.equal(L.repoFromPages("mbatovskyts.github.io", "/ThoughtSpot-Version-Control/index.html"), "mbatovskyts/ThoughtSpot-Version-Control");
  for (const [h, p] of [["localhost", "/x/"], ["example.com", "/a/"], ["mbatovskyts.github.io", "/"]]) assert.equal(L.repoFromPages(h, p), "");
});

test("normalizeRepo completes a bare name on Pages and cleans URLs", () => {
  assert.equal(L.normalizeRepo("ThoughtSpot-Version-Control", "mbatovskyts.github.io"), "mbatovskyts/ThoughtSpot-Version-Control");
  assert.equal(L.normalizeRepo("a/b", "mbatovskyts.github.io"), "a/b");
  assert.equal(L.normalizeRepo("https://github.com/a/b.git/", "x.com"), "a/b");
  assert.equal(L.normalizeRepo("bare", "localhost"), "bare");   // no owner to borrow off Pages
  assert.equal(L.normalizeRepo("", "mbatovskyts.github.io"), "");
});

test("backupIndexPath and backupDispatchBody reject odd input", () => {
  assert.equal(L.backupIndexPath("github", "prod"), "backups/github/prod/index.json");
  for (const [o, e] of [["../x", "dev"], ["a b", "dev"], ["github", "staging"], ["", "dev"]]) assert.throws(() => L.backupIndexPath(o, e));
  assert.deepEqual(L.backupDispatchBody("github"), { ref: "ts-prod", inputs: { org: "github" } });
  assert.equal(L.backupDispatchBody("all").inputs.org, "all");
  assert.throws(() => L.backupDispatchBody("a;b"));
});

test("parseBackupIndex keeps well-formed entries only and rejects unsafe paths", () => {
  const raw = { updated: "2026-10-28T01:05:00Z", tag: "Version Control", objects: [
    { key: "LB-1", name: "Liveboard", type: "LIVEBOARD", folder: "liveboards", file: "backups/github/dev/liveboards/LB-1.tml", versions: 3, present: true, last_changed: "x", first_seen: "y", last_seen: "z" },
    { key: "bad", name: "x", file: "backups/../../etc/passwd" },
    { key: "bad2", name: "x", file: "other/x.tml" },
    { name: "no key", file: "backups/a/b.tml" },
    { key: "gone", name: "Old", type: "ANSWER", file: "backups/github/dev/answers/gone.tml", present: false }] };
  const idx = L.parseBackupIndex(JSON.stringify(raw));
  assert.deepEqual(idx.objects.map((o) => [o.key, o.versions, o.present]), [["LB-1", 3, true], ["gone", 0, false]]);
  assert.equal(idx.tag, "Version Control");
  for (const bad of ["not json", null, "{}", { objects: "x" }]) assert.equal(L.parseBackupIndex(bad), null);
});

test("filterBackups hides removed objects unless asked and searches name and type", () => {
  const os = [{ key: "a", name: "Sales Board", type: "LIVEBOARD", present: true }, { key: "b", name: "Old", type: "ANSWER", present: false },
    { key: "c", name: "Stores", type: "LOGICAL_TABLE", present: true }];
  assert.deepEqual(L.filterBackups(os, "", false).map((o) => o.key), ["a", "c"]);
  assert.deepEqual(L.filterBackups(os, "", true).map((o) => o.key), ["a", "b", "c"]);
  assert.deepEqual(L.filterBackups(os, "sales", false).map((o) => o.key), ["a"]);
  assert.deepEqual(L.filterBackups(os, "table", false).map((o) => o.key), ["c"]);
});

test("versionRows and patchFor read GitHub's commit shapes", () => {
  const rows = L.versionRows([{ sha: "abcdef1234567", html_url: "https://github.com/o/r/commit/abc", commit: { message: "backup: 2026-10-28\n\nbody", committer: { date: "2026-10-28T01:06:00Z" } } }, null, {}]);
  assert.deepEqual(rows, [{ sha: "abcdef1234567", short: "abcdef1", date: "2026-10-28T01:06:00Z", message: "backup: 2026-10-28", url: "https://github.com/o/r/commit/abc" }]);
  assert.equal(L.patchFor({ files: [{ filename: "a", patch: "@@ -1 +1 @@" }, { filename: "b" }] }, "a"), "@@ -1 +1 @@");
  assert.equal(L.patchFor({ files: [{ filename: "b" }] }, "b"), "");
  assert.equal(L.patchFor(null, "a"), "");
});
