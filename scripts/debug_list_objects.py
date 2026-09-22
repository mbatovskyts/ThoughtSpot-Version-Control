#!/usr/bin/env python3
"""
Debug: list object names from the source org with no tag filter.
Confirms auth works and the account can read metadata.
Prints up to 50 objects per type (LOGICAL_TABLE, ANSWER, LIVEBOARD, COLLECTION).
Does not write any files or modify anything.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.ts_client import TSClient

SEARCH_TYPES = ["LOGICAL_TABLE", "ANSWER", "LIVEBOARD", "COLLECTION"]


def main():
    org_key = os.environ["ORG_KEY"]
    cfg_path = os.environ.get("CONFIG_OUT", f"/tmp/ts_migration_{org_key}_config.json")
    cfg = json.loads(Path(cfg_path).read_text())

    src = cfg["source"]
    client = TSClient(
        src["base_url"],
        src["org_id"],
        os.environ["TS_SOURCE_USERNAME"],
        os.environ["TS_SOURCE_SECRET_KEY"],
    )
    client.authenticate()

    for meta_type in SEARCH_TYPES:
        body = {
            "metadata": [{"type": meta_type}],
            "record_size": 50,
            "record_offset": 0,
        }
        resp = client.post("/metadata/search", body)
        if resp.status_code != 200:
            print(f"[DEBUG] {meta_type}: HTTP {resp.status_code} — {resp.text[:300]}", file=sys.stderr)
            continue

        raw = resp.json()
        items = raw if isinstance(raw, list) else raw.get("data") or raw.get("metadata") or []
        print(f"\n[DEBUG] {meta_type}: {len(items)} objects (first 50)")
        for obj in items:
            name = obj.get("metadata_name") or (obj.get("metadata_header") or {}).get("name") or "?"
            guid = obj.get("metadata_id", "")
            obj_id = obj.get("metadata_obj_id") or ""
            tags = []
            for t in (obj.get("tags") or (obj.get("metadata_header") or {}).get("tags") or []):
                tags.append(t if isinstance(t, str) else t.get("name", ""))
            tag_str = f"  tags={tags}" if tags else ""
            print(f"  {name}  (guid={guid}  obj_id={obj_id or 'NONE'}){tag_str}")


if __name__ == "__main__":
    main()
