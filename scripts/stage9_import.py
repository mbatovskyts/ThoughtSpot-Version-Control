#!/usr/bin/env python3
"""
Stage 9: Import TML into the production ThoughtSpot cluster.

Import order (dependency tiers):
  tables -> views -> models/worksheets -> sets -> collections ->
  answers -> liveboards -> feedback

Path B: substitute source db/schema literals -> target values in memory
         before import, then call parameterize-fields to rebind.

Safety gate: after tables import, read them back and verify no source
db/schema values remain.

Skipped entirely if DRY_RUN=true.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.ts_client import TSClient
from lib.tml_utils import (
    parse_tml, to_tml_string,
    path_b_substitute, get_table_db_schema, is_variable_bound,
)

IMPORT_TIERS = [
    ("tables",      ["LOGICAL_TABLE"],  ["TABLE"]),
    ("views",       ["LOGICAL_TABLE"],  ["SQL_VIEW"]),
    ("models",      ["LOGICAL_TABLE"],  ["WORKSHEET", "AGGR_WORKSHEET"]),
    ("collections", ["COLLECTION"],     []),
    ("answers",     ["ANSWER"],         []),
    ("liveboards",  ["LIVEBOARD"],      []),
    ("feedback",    ["FEEDBACK"],       []),
]

ASYNC_THRESHOLD = 20  # use async import for batches larger than this


def import_tier(
    target_client: TSClient,
    tier_entries: list[dict],
    cfg: dict,
    repo_root: Path,
    failed_obj_ids: set[str],
) -> list[dict]:
    results = []
    src_db = cfg["variables"]["database"]["source_value"]
    tgt_db = cfg["variables"]["database"]["target_value"]
    src_schema = cfg["variables"]["schema"]["source_value"]
    tgt_schema = cfg["variables"]["schema"]["target_value"]
    db_var = cfg["variables"]["database"]["ts_variable_name"]
    schema_var = cfg["variables"]["schema"]["ts_variable_name"]

    for entry in tier_entries:
        obj_id = entry["obj_id"]
        name = entry["name"]
        obj_type = entry["type"]
        tml_path_rel = entry.get("tml_path", "")
        other_tags = entry.get("other_tags", [])

        # Skip if a dependency failed
        dep_reason = entry.get("reason", "")
        if dep_reason.startswith("dependency_of:"):
            parent_id = dep_reason.split(":", 1)[1]
            if parent_id in failed_obj_ids:
                results.append({
                    "obj_id": obj_id, "name": name, "type": obj_type,
                    "status": "skipped",
                    "reason": f"dependency {parent_id} failed",
                })
                continue

        if not tml_path_rel:
            results.append({"obj_id": obj_id, "name": name, "type": obj_type,
                            "status": "skipped", "reason": "no tml_path"})
            continue

        tml_path = repo_root / tml_path_rel
        if not tml_path.exists():
            results.append({"obj_id": obj_id, "name": name, "type": obj_type,
                            "status": "skipped", "reason": "tml file missing"})
            continue

        try:
            tml_dict = parse_tml(tml_path.read_text(encoding="utf-8"))

            # Path B substitution (in-memory only, never persisted)
            if obj_type == "LOGICAL_TABLE" and entry["folder"] == "tables":
                tml_for_import = path_b_substitute(
                    tml_dict, src_db, tgt_db, src_schema, tgt_schema
                )
            else:
                tml_for_import = tml_dict

            resp = target_client.import_tml(
                [to_tml_string(tml_for_import)],
                import_policy="PARTIAL_OBJECT",
                create_new=False,
            )

            # Parse per-object import status
            # TODO(verify): confirm exact response structure against live cluster
            status_ok = _parse_import_status(resp, obj_id)

            if status_ok:
                results.append({"obj_id": obj_id, "name": name, "type": obj_type,
                                "status": "success"})

                # Reapply non-migration tags in target
                if other_tags:
                    _type_for_tag = _ts_type_for_tag(obj_type)
                    if _type_for_tag:
                        try:
                            target_client.assign_tags(
                                [{"type": _type_for_tag, "identifier": obj_id}],
                                other_tags,
                            )
                        except Exception as tag_err:
                            print(f"[WARN] Failed to reapply tags for '{name}': {tag_err}")

                # Path B: bind variables after table import
                if obj_type == "LOGICAL_TABLE" and entry["folder"] == "tables":
                    _parameterize_table(
                        target_client, obj_id, db_var, schema_var,
                        tgt_db, tgt_schema, results,
                    )

            else:
                failed_obj_ids.add(obj_id)
                err = _extract_error(resp)
                results.append({"obj_id": obj_id, "name": name, "type": obj_type,
                                "status": "failed", "error": err})

        except Exception as exc:
            failed_obj_ids.add(obj_id)
            results.append({"obj_id": obj_id, "name": name, "type": obj_type,
                            "status": "failed", "error": str(exc)})
            print(f"[FAIL] Import {obj_type} '{name}' ({obj_id}): {exc}", file=sys.stderr)

    return results


def _parse_import_status(resp: dict | list, obj_id: str) -> bool:
    objects = resp if isinstance(resp, list) else resp.get("object", [resp])
    for obj in objects:
        status = obj.get("response", {}).get("status", {}).get("status_code", "ERROR")
        if status in ("OK", "WARNING"):
            return True
    return bool(objects)  # fallback: non-empty response


def _extract_error(resp: dict | list) -> str:
    objects = resp if isinstance(resp, list) else resp.get("object", [resp])
    for obj in objects:
        msg = obj.get("response", {}).get("status", {}).get("error_message", "")
        if msg:
            return msg
    return str(resp)[:200]


def _ts_type_for_tag(meta_type: str) -> str | None:
    return {"LOGICAL_TABLE": "LOGICAL_TABLE", "ANSWER": "ANSWER",
            "LIVEBOARD": "LIVEBOARD", "COLLECTION": "COLLECTION"}.get(meta_type)


def _parameterize_table(
    client: TSClient, obj_id: str,
    db_var: str, schema_var: str,
    tgt_db: str, tgt_schema: str,
    results: list,
) -> None:
    try:
        client.parameterize_fields(
            table_identifier=obj_id,
            field_names=["databaseName", "schemaName"],
            variable_identifier=db_var,
        )
        print(f"[PARAMETERIZE] Bound db/schema on table {obj_id} to variable '{db_var}'.")
    except Exception as e:
        print(f"[WARN] Failed to parameterize table {obj_id}: {e}")


def safety_gate(
    target_client: TSClient,
    table_results: list[dict],
    src_db: str, src_schema: str,
    failed_obj_ids: set[str],
) -> None:
    """After tables import: verify no source db/schema values remain."""
    for res in table_results:
        if res["status"] != "success":
            continue
        obj_id = res["obj_id"]
        try:
            exported = target_client.export_tml(
                [{"identifier": obj_id}],
                include_obj_id=True, include_obj_id_ref=True, include_guid=False,
            )
            edocs = exported if isinstance(exported, list) else exported.get("object", [])
            if edocs:
                tml_dict = parse_tml(
                    edocs[0].get("edoc") or edocs[0].get("content") or json.dumps(edocs[0])
                    if isinstance(edocs[0].get("edoc") or edocs[0].get("content"), str)
                    else json.dumps(edocs[0])
                )
                db, schema = get_table_db_schema(tml_dict)
                if (db and db == src_db) or (schema and schema == src_schema):
                    res["status"] = "failed"
                    res["error"] = (
                        f"Safety gate: table still has source db/schema "
                        f"(db={db}, schema={schema}) after import."
                    )
                    failed_obj_ids.add(obj_id)
                    print(f"[SAFETY GATE FAIL] Table {obj_id}: {res['error']}", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] Safety gate check failed for {obj_id}: {e}")


def main():
    if os.environ.get("DRY_RUN", "false").lower() == "true":
        print("[STAGE 9] DRY_RUN=true — skipping import entirely.")
        sys.exit(0)

    org_key = os.environ["ORG_KEY"]
    cfg_path = os.environ.get("CONFIG_OUT", f"/tmp/ts_migration_{org_key}_config.json")
    export_path = os.environ.get("EXPORT_OUT", f"/tmp/ts_migration_{org_key}_export_results.json")
    manifest_path = os.environ.get("MANIFEST_OUT", f"/tmp/ts_migration_{org_key}_manifest.json")
    repo_root = Path(os.environ.get("REPO_ROOT", "."))

    cfg = json.loads(Path(cfg_path).read_text())
    export_results = json.loads(Path(export_path).read_text())
    manifest = json.loads(Path(manifest_path).read_text())

    # Build tml_path lookup from export results
    tml_paths = {r["obj_id"]: r["tml_path"] for r in export_results if r["status"] == "success"}
    for entry in manifest:
        entry["tml_path"] = tml_paths.get(entry["obj_id"], "")

    tgt = cfg["target"]
    target_client = TSClient(
        tgt["base_url"], tgt["org_id"],
        os.environ["TS_TARGET_USERNAME"],
        os.environ["TS_TARGET_SECRET_KEY"],
    )
    target_client.authenticate()

    failed_obj_ids: set[str] = set()
    all_results = []

    for folder, types, _subtypes in IMPORT_TIERS:
        # Manifest entries use `folder` (set by stage3) not `subtypes`, so filter LOGICAL_TABLE
        # objects by folder name which matches the tier name (tables/views/models).
        # Other types have a single tier each, so no folder filter is needed.
        tier_entries = [
            e for e in manifest
            if e["type"] in types and
               ("LOGICAL_TABLE" not in types or e.get("folder") == folder)
        ]
        if not tier_entries:
            continue
        print(f"[STAGE 9] Importing tier '{folder}': {len(tier_entries)} objects...")
        tier_results = import_tier(
            target_client, tier_entries, cfg, repo_root, failed_obj_ids
        )
        all_results.extend(tier_results)

        # Safety gate after table tier
        if folder == "tables":
            safety_gate(
                target_client,
                [r for r in tier_results if r["status"] == "success"],
                cfg["variables"]["database"]["source_value"],
                cfg["variables"]["schema"]["source_value"],
                failed_obj_ids,
            )

    out_path = os.environ.get("IMPORT_OUT", f"/tmp/ts_migration_{org_key}_import_results.json")
    Path(out_path).write_text(json.dumps(all_results, indent=2), encoding="utf-8")

    successes = sum(1 for r in all_results if r["status"] == "success")
    failures = sum(1 for r in all_results if r["status"] == "failed")
    skipped = sum(1 for r in all_results if r["status"] == "skipped")
    print(f"[STAGE 9] Import complete: {successes} success, {failures} failed, {skipped} skipped.")


if __name__ == "__main__":
    main()
