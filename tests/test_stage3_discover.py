"""Tests for Stage 3: discover tagged objects."""
import json
import pytest
from unittest.mock import MagicMock, patch

from scripts.stage3_discover import (
    build_manifest,
    filter_objects_without_obj_id,
    SEARCH_TYPES,
)


OBJS_WITH_IDS = [
    {
        "metadata_id": "guid-1",
        "metadata_name": "Table A",
        "metadata_type": "LOGICAL_TABLE",
        "metadata_subtype": "TABLE",
        "metadata_obj_id": "obj_001",
        "tags": [{"name": "sales_readyformigration"}, {"name": "finance"}],
    },
    {
        "metadata_id": "guid-2",
        "metadata_name": "LB A",
        "metadata_type": "LIVEBOARD",
        "metadata_subtype": None,
        "metadata_obj_id": "obj_002",
        "tags": [{"name": "sales_readyformigration"}],
    },
]

OBJ_WITHOUT_ID = {
    "metadata_id": "guid-3",
    "metadata_name": "No ID Table",
    "metadata_type": "LOGICAL_TABLE",
    "metadata_subtype": "TABLE",
    "metadata_obj_id": None,
    "tags": [{"name": "sales_readyformigration"}],
}


class TestFilterObjectsWithoutObjId:
    def test_separates_objects_missing_obj_id(self):
        objs = OBJS_WITH_IDS + [OBJ_WITHOUT_ID]
        good, bad = filter_objects_without_obj_id(objs)
        assert len(good) == 2
        assert len(bad) == 1
        assert bad[0]["metadata_name"] == "No ID Table"

    def test_all_have_ids(self):
        good, bad = filter_objects_without_obj_id(OBJS_WITH_IDS)
        assert len(good) == 2
        assert bad == []


class TestBuildManifest:
    def test_tagged_reason_set(self):
        entries = build_manifest(
            OBJS_WITH_IDS,
            tagged_guids={"guid-1", "guid-2"},
            migration_tag="sales_readyformigration",
        )
        assert all(e["reason"] == "tagged" for e in entries)

    def test_other_tags_exclude_migration_tag(self):
        entries = build_manifest(
            OBJS_WITH_IDS,
            tagged_guids={"guid-1", "guid-2"},
            migration_tag="sales_readyformigration",
        )
        table_entry = next(e for e in entries if e["obj_id"] == "obj_001")
        assert "sales_readyformigration" not in table_entry["other_tags"]
        assert "finance" in table_entry["other_tags"]

    def test_dependency_reason_set(self):
        entries = build_manifest(
            OBJS_WITH_IDS,
            tagged_guids={"guid-2"},  # only liveboard tagged; table is a dep
            migration_tag="sales_readyformigration",
            dependency_of={"guid-1": "obj_002"},
        )
        table_entry = next(e for e in entries if e["obj_id"] == "obj_001")
        assert table_entry["reason"].startswith("dependency_of:")
