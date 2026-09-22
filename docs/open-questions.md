# Open Questions

Items that require live verification or a decision before implementation proceeds.

---

## 1. Path A vs Path B — Parameterized Table TML (BLOCKING)

**Question:** When a Table is parameterized (db/schema bound to a TABLE_MAPPING variable via `parameterize-fields`), does the exported TML carry:
- **Path A:** a variable reference (e.g., `db: "${ts_db_name}"`) that is preserved on import, OR
- **Path B:** the literal resolved value (e.g., `db: "DEV_DB"`) that requires in-memory substitution before import?

**Why it matters:** Determines whether the pipeline needs to substitute source → target values in memory before import (Path B) and then call `parameterize-fields` to rebind after import.

**How to verify:** Export one parameterized table from the dev cluster using the pipeline export flags (`include_obj_id: true`, `include_guid: false`) and inspect the `db` and `schema` fields in the TML.

**Current assumption:** Path B. Implementation includes substitution + re-parameterization. Remove if Path A is confirmed.

---

## 2. Sets Object Subtype

**Question:** What is the `subtypes` value for Sets in `POST /api/rest/2.0/metadata/search`?

**Suspected value:** `AGGR_WORKSHEET` (aggregate worksheet). Needs confirmation against a live cluster that has a Set object.

**Impact:** Stage 3 (Discover) uses the correct subtype to find Sets tagged for migration.

---

## 3. Variable API Enablement Per Cluster

**Question:** Are the Variable APIs (26.4.0.cl+) enabled on both the source and target clusters?

**Action required:** Have ThoughtSpot Support confirm that `POST /api/rest/2.0/template/variables/create` and related endpoints are enabled on both clusters. The pipeline detects a 403 or specific error and reports `variable API not enabled` rather than failing silently.

---

## 4. Async TML Import — Per-Object Status in Response

**Question:** What is the exact structure of `import_response` inside the async task status response? Specifically, how are per-object success/failure statuses returned (object GUID, obj_id, error message, HTTP status)?

**How to verify:** Run an async import on the dev cluster with `include_import_response: true` and inspect the response.

**Impact:** Stage 9 parses per-object status to build the failure list and dependency skip list.

---

## 5. Collections TML Import — Object Membership

**Question:** Does importing a Collection TML recreate the membership (which Liveboards/Answers belong to the collection)? Or does membership need to be set separately after import?

**Impact:** Stage 9 collection handling.

---

## 6. Other Potentially Migratable Content Types (Do Not Build Without Asking)

The following content types were identified in the API but are not in scope yet:

| Content Type | Endpoint / Notes | Status |
|---|---|---|
| Custom Calendars | `POST /api/rest/2.0/customcalendars/search` — appears to exist | Out of scope; ask before building |
| Column Security Rules | `export_column_security_rules: true` in TML export (10.12.0.cl+) | Out of scope; ask before building |
| Schedules | Not in scope per spec | Out of scope |
| Custom Actions | Not in scope per spec | Out of scope |

---

## 7. Branch Protection and Auto-Merge

**Question:** Does the `ts-prod` branch have protection rules requiring reviews? If so, the `GH_AUTOMATION_TOKEN` PAT needs `bypass-branch-protection` or must be a branch protection rule admin.

**Action required:** Set up `GH_AUTOMATION_TOKEN` with:
- `contents: write`
- `pull-requests: write`
- Branch protection bypass if required

See `docs/runbook.md` for setup instructions.
