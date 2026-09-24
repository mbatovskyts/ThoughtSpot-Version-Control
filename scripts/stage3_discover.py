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


def _resolve_tag_id(source_client: TSClient, tag_name: str, cfg: dict) -> str:
    """
    Return the tag identifier to use in tag_identifiers filter.
    tag_identifiers accepts both the tag name and its GUID; the tag name is
    simpler and confirmed to work. We use it directly.
    """
    print(f"[STAGE 3] Using tag name as identifier: {tag_name}")
    return tag_name


def discover(source_client: TSClient, cfg: dict, report: RunReport) -> list[dict]:
    tag = cfg["migration_tag"]
    dep_mode = cfg.get("dependency_mode", "include")
    manifest: list[dict] = []
    seen_guids: set[str] = set()

    # Resolve the tag identifier to use in tag_identifiers filter (server-side only).
    # Priority: config-provided GUID > /tags/search GUID > tag name as fallback.
    tag_id_for_filter = _resolve_tag_id(source_client, tag, cfg)

    for meta_type in SEARCH_TYPES:
        objects = _search_by_tag(source_client, meta_type, tag_id_for_filter)
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


def _search_by_tag(
    source_client: TSClient,
    meta_type: str,
    tag_id_for_filter: str,
) -> list[dict]:
    """Return objects of meta_type that match the tag_identifiers server-side filter."""
    all_objects: list[dict] = []
    offset = 0
    page_size = 500  # avoid record_size:-1 which crashes TS when combined with tag_identifiers

    while True:
        body: dict = {
            "metadata": [{"type": meta_type}],
            "tag_identifiers": [tag_id_for_filter],
            "include_headers": True,
            "record_size": page_size,
            "record_offset": offset,
        }
        resp = source_client.post("/metadata/search", body)
        if resp.status_code != 200:
            print(
                f"[WARN] metadata/search type={meta_type} HTTP {resp.status_code}: {resp.text[:200]}",
                file=sys.stderr,
            )
            return []
        page = _unwrap_response(resp.json())
        all_objects.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    print(f"[STAGE 3] type={meta_type}: tag filter returned {len(all_objects)} objects")
    return all_objects


def _extract_tags(obj: dict) -> list[str]:
    # Tags may sit at top level OR nested under metadata_header depending on TS version
    tag_list = obj.get("tags") or []
    if not tag_list:
        header = obj.get("metadata_header") or {}
        tag_list = header.get("tags") or []
    return [t if isinstance(t, str) else t.get("name", "") for t in tag_list]


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

    tagged_count = sum(1 for e in manifest if e.get("reason") == "tagged")
    if tagged_count == 0:
        print(
            f"[INFO] 0 objects with tag '{cfg['migration_tag']}' found in source org "
            f"{src['org_id']}. Nothing to migrate — pipeline will exit cleanly.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
