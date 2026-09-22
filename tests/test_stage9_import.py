"""Tests for Stage 9: import tiers, Path B substitution, safety gate."""
import pytest
from unittest.mock import MagicMock, patch

from scripts.stage9_import import (
    apply_path_b_and_import,
    safety_gate_check,
    mark_dependents_skipped,
)


SAMPLE_TABLE_MANIFEST = [
    {
        "obj_type": "tables",
        "obj_id": "obj_001",
        "metadata_id": "guid-1",
        "name": "Sales Fact",
        "tml_path": "orgs/sales/tables/sales_fact__obj_001.table.tml",
    }
]


class TestApplyPathBAndImport:
    def test_substitutes_before_import(self, sample_table_tml, sample_org_config):
        client = MagicMock()
        client.import_tml.return_value = [
            {"metadata_obj_id": "obj_001", "response_code": 200, "metadata_name": "Sales Fact"}
        ]

        result = apply_path_b_and_import(
            client=client,
            tml=sample_table_tml,
            manifest_entry=SAMPLE_TABLE_MANIFEST[0],
            org_config=sample_org_config,
            import_policy="PARTIAL_OBJECT",
        )
        # The TML passed to import should have PROD values, not DEV values
        call_args = client.import_tml.call_args
        import_tml_str = call_args[1].get("tml_list") or call_args[0][0]
        import_str = str(import_tml_str)
        assert "PROD_DB" in import_str
        assert "DEV_DB" not in import_str


class TestSafetyGateCheck:
    def test_fails_when_source_value_present(self):
        # Simulate table read-back still containing source db
        readback_tml = {
            "table": {
                "db": "DEV_DB",  # source value leaked
                "schema": "PROD_SCHEMA",
            }
        }
        passed, reason = safety_gate_check(
            readback_tml,
            source_db="DEV_DB",
            source_schema="DEV_SCHEMA",
        )
        assert passed is False
        assert "DEV_DB" in reason

    def test_passes_when_target_values(self):
        readback_tml = {
            "table": {
                "db": "PROD_DB",
                "schema": "PROD_SCHEMA",
            }
        }
        passed, _ = safety_gate_check(
            readback_tml,
            source_db="DEV_DB",
            source_schema="DEV_SCHEMA",
        )
        assert passed is True


class TestMarkDependentsSkipped:
    def test_marks_downstream_skipped(self):
        manifest = [
            {"obj_id": "obj_001", "reason": "tagged", "status": "failed"},
            {"obj_id": "obj_002", "reason": "dependency_of:obj_001", "status": "pending"},
            {"obj_id": "obj_003", "reason": "tagged", "status": "pending"},
        ]
        updated = mark_dependents_skipped(manifest, failed_obj_id="obj_001")
        dep = next(e for e in updated if e["obj_id"] == "obj_002")
        assert dep["status"] == "skipped"
        assert dep["skip_reason"] == "dependency obj_001 failed"
        # obj_003 is independent; should not be skipped
        independent = next(e for e in updated if e["obj_id"] == "obj_003")
        assert independent["status"] == "pending"
