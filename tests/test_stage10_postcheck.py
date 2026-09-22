"""Tests for Stage 10: post-check and tag cleanup."""
import pytest
from unittest.mock import MagicMock

from scripts.stage10_postcheck import (
    postcheck_objects,
    filter_for_tag_removal,
)


class TestPostcheckObjects:
    def _make_target_client(self, found_ids):
        client = MagicMock()
        client.search_metadata.return_value = [
            {"metadata_obj_id": oid} for oid in found_ids
        ]
        return client

    def test_confirms_present_objects(self):
        manifest = [
            {"obj_id": "obj_001", "status": "succeeded", "name": "T", "obj_type": "tables"},
            {"obj_id": "obj_002", "status": "succeeded", "name": "LB", "obj_type": "liveboards"},
        ]
        client = self._make_target_client(["obj_001", "obj_002"])
        results = postcheck_objects(client, manifest)
        assert all(r["postcheck"] == "confirmed" for r in results)

    def test_flags_missing_object(self):
        manifest = [
            {"obj_id": "obj_001", "status": "succeeded", "name": "T", "obj_type": "tables"},
            {"obj_id": "obj_999", "status": "succeeded", "name": "Missing", "obj_type": "tables"},
        ]
        client = self._make_target_client(["obj_001"])  # obj_999 missing
        results = postcheck_objects(client, manifest)
        missing = next(r for r in results if r["obj_id"] == "obj_999")
        assert missing["postcheck"] == "missing"


class TestFilterForTagRemoval:
    def test_only_removes_for_tagged_and_confirmed(self):
        objects = [
            {"obj_id": "obj_001", "reason": "tagged",
             "status": "succeeded", "postcheck": "confirmed", "metadata_id": "g1"},
            {"obj_id": "obj_002", "reason": "dependency_of:obj_001",  # dep, not tagged
             "status": "succeeded", "postcheck": "confirmed", "metadata_id": "g2"},
            {"obj_id": "obj_003", "reason": "tagged",
             "status": "failed", "postcheck": "missing", "metadata_id": "g3"},
        ]
        to_remove = filter_for_tag_removal(objects)
        ids = [o["metadata_id"] for o in to_remove]
        assert "g1" in ids        # tagged + confirmed
        assert "g2" not in ids    # dependency, not tagged
        assert "g3" not in ids    # failed
