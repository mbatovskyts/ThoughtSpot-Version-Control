#!/usr/bin/env python3
"""
Stage 3: Discover tagged objects in the source org.

Finds all objects tagged with <org_key>_readyformigration across all
in-scope types, resolves dependencies per dependency_mode, and writes
manifest.json.

Objects without obj_id are recorded as failures and excluded.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.ts_client import TSClient
from lib.report import RunReport, ObjectRecord

# Types to search per iteration
# Each entry: (metadata_type, subtypes_list_or_None, canonical_folder_name)
SEARCH_TYPES = [
    ("LOGICAL_TABLE", ["TABLE"],              "tables"),
    ("LOGICAL_TABLE", ["SQL_VIEW"],            "views"),
    ("LOGICAL_TABLE", ["WORKSHEET"],           "models"),
    ("LOGICAL_TABLE", ["AGGR_WORKSHEET"],      "models"),  # TODO(verify): Sets subtype
    ("ANSWER",        None,                    "answers"),
    ("LIVEBOARD",     None,                    "liveboards"),
    ("COLLECTION",    None,                    "collections"),
]


def discover(source_client: TSClient, cfg: dict, report: RunReport) -> list[dict]:
    tag = cfg["migration_tag"]
    dep_mode = cfg.get("dependency_mode", "include")
    manifest: list[dict] = []
    seen_guids: set[str] = set()
    failed_obj_ids: set[str] = set()

    for meta_type, subtypes, folder in SEARCH_TYPES:
        body: dict = {
            "tag_identifiers": [tag],
            "record_size": -1,
            "record_offset": 0,
        }
        if subtypes:
            body["subtypes"] = subtypes

        resp = source_client.post(f"/metadata/search", {
            **body,
            "type": meta_type,
        })
        if resp.status_code != 200:
            print(f"[WARN] search_metadata type={meta_type} subtypes={subtypes} "
                  f"returned HTTP {resp.status_code}", file=sys.stderr)
            continue

        objects = resp.json()
        for obj in objects:
            guid = obj.get("metadata_id", "")
            if guid in seen_guids:
                continue
            seen_guids.add(guid)

            obj_id = obj.get("metadata_obj_id") or ""
            name = obj.get("metadata_name", "")
            tags_on_obj = _extract_tags(obj)
            other_tags = [t for t in tags_on_obj if t != tag]

            if not obj_id:
                rec = ObjectRecord(
                    obj_type=meta_type,
                    name=name,
                    obj_id="",
                    source_guid=guid,
                    reason="missing_obj_id",
                    stage="discover",
                    status="failed",
                    error="Object has no obj_id. Enable Object ID feature and assign one.",
                    suggested_action="Assign a custom obj_id via ThoughtSpot UI or API, then re-tag.",
                )
                report.mark_failed(rec)
                print(f"[SKIP] {meta_type} '{name}' (GUID {guid}) has no obj_id — excluded.",
                      file=sys.stderr)
                continue

            entry = {
                "type": meta_type,
                "subtypes": subtypes or [],
                "folder": folder,
                "name": name,
                "obj_id": obj_id,
                "source_guid": guid,
                "reason": "tagged",
                "other_tags": other_tags,
            }
            manifest.append(entry)
            pulled_rec = ObjectRecord(
                obj_type=meta_type, name=name, obj_id=obj_id,
                source_guid=guid, reason="tagged", other_tags=other_tags,
            )
            report.add_pulled(pulled_rec)

            # Resolve dependencies
            if dep_mode == "include":
                deps = obj.get("dependent_objects") or {}
                for dep_type, dep_list in deps.items():
                    for dep in (dep_list or []):
                        dep_guid = dep.get("id") or dep.get("metadata_id", "")
                        if dep_guid in seen_guids:
                            continue
                        seen_guids.add(dep_guid)
                        dep_obj_id = dep.get("metadata_obj_id") or dep.get("obj_id", "")
                        dep_name = dep.get("name") or dep.get("metadata_name", "")
                        if not dep_obj_id:
                            rec = ObjectRecord(
                                obj_type=dep_type, name=dep_name,
                                obj_id="", source_guid=dep_guid,
                                reason=f"dependency_of:{obj_id}",
                                stage="discover", status="failed",
                                error="Dependency has no obj_id.",
                                suggested_action="Assign obj_id to this dependency.",
                            )
                            report.mark_failed(rec)
                            failed_obj_ids.add(dep_guid)
                            continue
                        dep_entry = {
                            "type": dep_type,
                            "subtypes": [],
                            "folder": _folder_for_type(dep_type),
                            "name": dep_name,
                            "obj_id": dep_obj_id,
                            "source_guid": dep_guid,
                            "reason": f"dependency_of:{obj_id}",
                            "other_tags": [],
                        }
                        manifest.append(dep_entry)
                        dep_rec = ObjectRecord(
                            obj_type=dep_type, name=dep_name, obj_id=dep_obj_id,
                            source_guid=dep_guid,
                            reason=f"dependency_of:{obj_id}",
                        )
                        report.add_pulled(dep_rec)

    return manifest


def _extract_tags(obj: dict) -> list[str]:
    header = obj.get("metadata_header") or {}
    tags = header.get("tags") or []
    return [t if isinstance(t, str) else t.get("name", "") for t in tags]


def _folder_for_type(meta_type: str) -> str:
    mapping = {
        "LOGICAL_TABLE": "tables",
        "ANSWER": "answers",
        "LIVEBOARD": "liveboards",
        "COLLECTION": "collections",
    }
    return mapping.get(meta_type, "misc")


def main():
    from lib.ts_client import TSClient
    org_key = os.environ["ORG_KEY"]
    run_id = os.environ.get("RUN_ID", "local")
    cfg_path = os.environ.get("CONFIG_OUT", f"/tmp/ts_migration_{org_key}_config.json")
    cfg = json.loads(Path(cfg_path).read_text())

    src = cfg["source"]
    username = os.environ["TS_SOURCE_USERNAME"]
    secret_key = os.environ["TS_SOURCE_SECRET_KEY"]
    source_client = TSClient(src["base_url"], src["org_id"], username, secret_key)
    source_client.authenticate()

    report = RunReport(
        org_key=org_key, run_id=run_id,
        mode="DRY-RUN" if os.environ.get("DRY_RUN", "false").lower() == "true" else "LIVE",
        source_url=src["base_url"], source_org_id=src["org_id"],
        target_url=cfg["target"]["base_url"], target_org_id=cfg["target"]["org_id"],
        migration_tag=cfg["migration_tag"],
    )

    manifest = discover(source_client, cfg, report)

    out_path = os.environ.get("MANIFEST_OUT", f"/tmp/ts_migration_{org_key}_manifest.json")
    Path(out_path).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[STAGE 3] Discovered {len(manifest)} objects -> {out_path}")
    if report.failed:
        print(f"[WARN] {len(report.failed)} objects excluded (no obj_id). See failures.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
