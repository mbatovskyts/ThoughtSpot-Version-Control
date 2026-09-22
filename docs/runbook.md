# ThoughtSpot Migration Pipeline — Runbook

## Table of Contents

1. [Overview](#overview)
2. [Adding a New Org](#adding-a-new-org)
3. [Required Secrets and Environments](#required-secrets-and-environments)
4. [Branch Protection Setup](#branch-protection-setup)
5. [Running the Workflow](#running-the-workflow)
6. [Reading the Reports](#reading-the-reports)
7. [Re-queuing a Failed Object](#re-queuing-a-failed-object)
8. [Dry Run Mode](#dry-run-mode)
9. [Troubleshooting](#troubleshooting)

---

## Overview

This pipeline migrates ThoughtSpot content (Tables, Models, Answers, Liveboards, Collections, etc.) from a **source (dev)** cluster/org to a **target (prod)** cluster/org. Content is identified by a migration tag (`<org_key>_readyformigration`) applied in the source.

The pipeline:
- Exports tagged objects as TML into the `ts-dev` GitHub branch
- Opens a PR into `ts-prod` for review/approval
- Imports TML into the target cluster after the PR merges
- Removes the migration tag from successfully migrated objects
- Produces a full report per run

**No deletions** ever occur. **Source is read-only** except for tag removal.

---

## Adding a New Org

### 1. Create the org config file

Create `config/orgs/<org_key>.yml` (org_key must be lowercase, no spaces):

```yaml
org_key: my_org                          # Must match filename without .yml
display_name: My Organization
migration_tag: my_org_readyformigration  # MUST equal <org_key>_readyformigration

source:
  base_url: https://dev-ts.mycompany.com
  org_id: 12                             # ThoughtSpot org ID on the source cluster

target:
  base_url: https://prod-ts.mycompany.com
  org_id: 3                              # ThoughtSpot org ID on the target cluster

dependency_mode: include  # include | skip_if_exists | require_tagged

variables:
  database:
    ts_variable_name: ts_db_name         # Name of the TABLE_MAPPING variable
    source_value: DEV_DB                 # Source literal value (Path B detection only)
    target_value: PROD_DB                # Value to set in target (NEVER hardcode in TML)
  schema:
    ts_variable_name: ts_schema_name
    source_value: DEV_SCHEMA
    target_value: PROD_SCHEMA
  extra:
    # Optional: formula variables, connection properties used in RLS, etc.
    # - { ts_variable_name: region_filter, type: FORMULA_VARIABLE, target_value: "EMEA" }
```

**Same-cluster (org-to-org) migration:** Use the same `base_url` but different `org_id` values. Both secret keys will be the same value; set them identically in both `dev` and `prod` environments.

### 2. Add secrets to GitHub Environments

See [Required Secrets and Environments](#required-secrets-and-environments).

### 3. Tag content in the source cluster

In the source ThoughtSpot org, create a tag named `<org_key>_readyformigration` and apply it to every object you want to migrate. Objects without this tag are ignored.

**Important:** Every object must have an `obj_id` set (contact ThoughtSpot Support to enable the Object ID feature on both clusters if not already active).

### 4. Run a dry run first

Trigger the workflow with `org=<org_key>` and `dry_run=true`. Review the generated report before running live.

---

## Required Secrets and Environments

The pipeline uses two GitHub Environments:

| Environment | Holds | Notes |
|-------------|-------|-------|
| `dev` | Source cluster credentials | `extract` and `untag_source` jobs use this |
| `prod` | Target cluster credentials | `import` job uses this; configure required reviewers here for approval gate |

### Secrets to configure

**In both environments:**

| Secret name | Description |
|-------------|-------------|
| `TS_SOURCE_USERNAME` | ThoughtSpot username for the source cluster |
| `TS_SOURCE_SECRET_KEY` | Trusted Authentication secret key for the source cluster |
| `TS_TARGET_USERNAME` | ThoughtSpot username for the target cluster |
| `TS_TARGET_SECRET_KEY` | Trusted Authentication secret key for the target cluster |
| `GH_AUTOMATION_TOKEN` | (Optional) GitHub PAT with `repo` + `workflow` scopes, needed for auto-merging PRs |

**Per-org secret overrides** (optional): if an org uses different credentials, add secrets named `TS_SOURCE_SECRET_KEY_<ORG_KEY_UPPER>` (e.g. `TS_SOURCE_SECRET_KEY_SALES`). These take precedence over the base secret.

**To configure environments:**
1. Go to **Settings → Environments** in the GitHub repo
2. Create environments named `dev` and `prod`
3. For `prod`: add required reviewers to enforce the approval gate before import runs
4. Add the secrets listed above to each environment

### Branch protection

Configure the `ts-prod` branch with:
- **Require pull request reviews before merging** (at least 1 reviewer)
- **Require status checks to pass** (add the `migrate` job from `ts-migration.yml`)
- **Restrict who can push**: only the `GH_AUTOMATION_TOKEN` user (for auto-merge) and admins

**Auto-merge requirement:** The `GH_AUTOMATION_TOKEN` PAT must belong to a user with write access to the repo. Without it, the pipeline falls back to `GITHUB_TOKEN`, which cannot merge its own PRs — in that case, a human must merge the PR before the import job runs.

---

## Running the Workflow

1. Go to **Actions → ThoughtSpot Migration → Run workflow**
2. Fill in:
   - **org**: org key (e.g. `sales`) or `all` to run every configured org
   - **dry_run**: `true` for validate-only (no writes); `false` for a live migration
3. Click **Run workflow**

Each org runs in its own job with its own concurrency group (`ts-migration-<org_key>`). A failure in one org does not block others.

### Jobs per org (sequential)

| Job | Stage | Environment | What it does |
|-----|-------|-------------|-------------|
| `extract` | 1–6 | `dev` | Config, auth, discover, export TML, sanitize, commit to ts-dev |
| `promote` | 7 | — | Create promote branch, open PR into ts-prod |
| `import` | 8–9 | `prod` | Sync variables, connection preflight, validate, import |
| `untag_source` | 10 | `dev` | Post-check, remove migration tag from successes |
| `report` | 11 | — | Generate all report files (runs even on failure) |

---

## Reading the Reports

Reports are in two places:
1. **Workflow artifacts** (90-day retention): download from the Actions run page
2. **Git history**: committed to `ts-dev` under `reports/<org_key>/<timestamp>_<run_id>/`

### Files

| File | Description |
|------|-------------|
| `migration_summary.txt` | Human-readable overview: counts and lists per section |
| `failures_report.txt` | One entry per failed object with error details |
| `failures.json` | Machine-readable failures (same data as txt, structured) |
| `manifest.json` | All objects considered for migration with their status |

### Summary sections

1. **PULLED** — objects identified for migration (tagged + dependencies)
2. **SUCCEEDED** — imported and post-check confirmed
3. **FAILED** — import failed; see `failures_report.txt` for details
4. **SKIPPED** — excluded due to missing obj_id, failed dependency, missing connection, etc.
5. **POST-MIGRATION CHECK** — target vs manifest counts; any missing objects
6. **TAG CLEANUP** — how many migration tags removed vs retained
7. **UNSUPPORTED CONTENT** — Collections/Memories if API not available, etc.

### GitHub job summary

Each org's `report` job writes a summary table directly to the GitHub Actions job summary page (visible in the Actions UI without downloading artifacts).

---

## Re-queuing a Failed Object

When an object fails or is skipped due to a dependency failure:

1. Diagnose the error in `failures_report.txt` or `failures.json`
2. Fix the root cause (e.g. add the missing connection in the target, enable the Variable API)
3. **Re-apply the migration tag** to the failed object in the source cluster
   - Objects that failed keep their migration tag automatically
   - Objects where the dependency failed: re-tag the root dependency's parent object
4. Re-run the workflow

Because matching is done by `obj_id`, re-running **updates** the existing target object rather than creating a duplicate.

**Note:** An object whose migration tag was already removed (successful migration) will not be picked up on re-run unless you re-apply the tag in the source. Re-tagging is safe — the next run will update the target object in place.

---

## Dry Run Mode

A dry run completes Stages 1–8 (including validate-only import) but:
- Makes **zero writes** to the target cluster
- Makes **zero tag changes** in the source
- Opens the promote PR but does not auto-merge it
- Stage 9 (live import) is entirely skipped
- Stage 10 (tag cleanup) is entirely skipped

Use dry runs to:
- Validate TML before committing to a migration
- Detect missing connections or variable mismatches
- Preview what would be migrated without side effects

---

## Troubleshooting

### `migration_tag must equal <org_key>_readyformigration`
The `migration_tag` value in the org config doesn't match the required format. Fix `config/orgs/<org_key>.yml`.

### `Token org mismatch`
The auth token returned by the cluster has a different `org_id` than configured. Check `org_id` in the config and confirm you're using the correct secret key for that org.

### `obj_id missing` for an object
The Object ID feature is not enabled on the source cluster, or the specific object was created before obj_ids were enabled. Contact ThoughtSpot Support to enable the Object ID feature and backfill existing objects.

### `Connection "X" missing in target org`
The table references a data source connection that doesn't exist in the target org. Create the connection in the target first (connections are out of scope for migration).

### `Variable API not available (403)`
The Variable API (beta) is not enabled on the cluster. Contact ThoughtSpot Support to enable it. The pipeline logs a warning and continues; variable sync will be skipped.

### `Hard stop: TABLE_MAPPING variable has no target_value`
A TABLE_MAPPING variable in the config's `variables` block is missing `target_value`. This is a required field — add it to `config/orgs/<org_key>.yml`.

### Stage 9 skipped unexpectedly
Check that `dry_run` is set to `false` in the workflow dispatch inputs.

### PR auto-merge not working
`GH_AUTOMATION_TOKEN` is missing or the token user doesn't have write access to the repo. Either configure the secret or merge the PR manually.

### Push to ts-dev fails with `non-fast-forward`
Two orgs pushed simultaneously and one lost the race. The pipeline retries with jitter up to 6 times. If it still fails, re-run the workflow — this is a transient conflict.

### Safety gate fails: `source db/schema value found in target table`
After table import, the table still resolves to a source database/schema value. This means Path B substitution or variable binding did not apply correctly. Check:
1. `source_value` / `target_value` in config match the actual values in the TML
2. The Variable API is enabled and `ts_db_name` / `ts_schema_name` exist in the target
3. The `parameterize-fields` call succeeded (check stage 9 logs)
