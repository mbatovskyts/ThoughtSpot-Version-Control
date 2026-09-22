#!/usr/bin/env python3
"""
Stage 3: Discover tagged objects in the source org.

Finds all objects tagged with <migration_tag> across all in-scope types,
resolves dependencies per dependency_mode, and writes manifest.json.

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

# Types to search — one API call per main metadata_type.
# Subtype classification happens client-side from metadata_header.type.
SEARCH_TYPES = [
    "LOGICAL_TABLE",
    "ANSWER",
    "LIVEBOARD",
    "COLLECTION",
]

# Maps metadata_header.type → folder name for LOGICAL_TABLE objects
_TABLE_SUBTYPE_FOLDER = {
    "TABLE":           "tables",
    "SQL_VIEW":        "views",
    "WORKSHEET":       "models",
    "AGGR_WORKSHEET":  "models",
    "MODEL":           "models",
}


def _unwrap_response(raw) -> list:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("data", "results", "objects", "metadata"):
            if key in raw and isinstance(raw[key], list):
                return raw[key]
    return []


def _folder_for_object(meta_type: str, obj: dict) -> str:
    if meta_type == "LOGICAL_TABLE":
        header = obj.get("metadata_header") or {}
        subtype = header.get("type", "")
        return _TABLE_SUBTYPE_FOLDER.get(subtype, "tables")
    return {"ANSWER": "answers", "LIVEBOARD": "liveboards", "COLLECTION": "collections"}.get(meta_type, "misc")


def _resolve_tag_guid(source_client: TSClient, tag_name: str) -> str:
    """Return the GUID of a tag by name. Exits with error if not found."""
    tags = source_client.search_tags(name_pattern=tag_name)
    for t in tags:
        if t.get("name") == tag_name:
            guid = t.get("id") or t.get("tag_id") or t.get("identifier", "")
            print(f"[STAGE 3] Resolved tag '{tag_name}' → GUID {guid}")
            return guid
    all_names = [t.get("name") for t in tags]
    print(f"[ERROR] Tag '{tag_name}' not found in source org. "
          f"Tags matching pattern: {all_names}", file=sys.stderr)
    sys.exit(1)


def discover(source_client: TSClient, cfg: dict, report: RunReport) -> list[dict]:
    tag = cfg["migration_tag"]
    dep_mode = cfg.get("dependency_mode", "include")
    manifest: list[dict] = []
    seen_guids: set[str] = set()

    # Resolve tag name → GUID so tag_identifiers filter works reliably
    tag_guid = _resolve_tag_guid(source_client, tag)

    for meta_type in SEARCH_TYPES:
        # Debug: log total object count without tag filter to verify connectivity
        probe_resp = source_client.post("/metadata/search", {
            "metadata": [{"type": meta_type}],
            "record_size": 1,
            "record_offset": 0,
        })
        probe_total = "?"
        if probe_resp.status_code == 200:
            probe_raw = probe_resp.json()
            probe_total = len(probe_raw) if isinstance(probe_raw, list) else "?"
        print(f"[DEBUG] type={meta_type}: total_in_org(sample)={probe_total} (no tag filter)")

        body: dict = {
            "metadata": [{"type": meta_type}],
            "tag_identifiers": [tag_guid],
            "record_size": 500,
            "record_offset": 0,
        }

        resp = source_client.post("/metadata/search", body)
        if resp.status_code != 200:
            print(f"[WARN] search_metadata type={meta_type} returned HTTP {resp.status_code}: {resp.text[:200]}",
                  file=sys.stderr)
            continue

        raw = resp.json()
        print(f"[DEBUG] type={meta_type}: HTTP {resp.status_code}, "
              f"response={type(raw).__name__}, count={len(raw) if isinstance(raw, list) else '?'} "
              f"(tag_identifier={tag_guid})")

        objects = _unwrap_response(raw)
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

            folder = _folder_for_object(meta_type, obj)
            entry = {
                "type": meta_type,
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
                            continue
                        dep_entry = {
                            "type": dep_type,
                            "folder": _folder_for_object(dep_type, dep),
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
