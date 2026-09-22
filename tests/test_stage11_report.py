"""Tests for Stage 11: report generation and exit code."""
import json
import os
import tempfile
import pytest

from scripts.lib.report import RunReport, ObjectRecord


def make_report(failures=0, succeeded=1):
    report = RunReport(
        org_key="sales", run_id="999", timestamp="20240101T000000Z",
        dry_run=False, source_url="https://dev.ex.com", source_org_id=12,
        target_url="https://prod.ex.com", target_org_id=3,
        migration_tag="sales_readyformigration",
    )
    for i in range(succeeded):
        report.add_succeeded(ObjectRecord(
            obj_type="tables", name=f"T{i}", obj_id=f"obj_{i:03d}",
            source_guid=f"g{i}", reason="tagged", other_tags=[],
            stage="import", status="succeeded",
        ))
    for i in range(failures):
        report.add_failed(ObjectRecord(
            obj_type="liveboards", name=f"LB_fail_{i}", obj_id=f"obj_fail_{i:03d}",
            source_guid=f"gf{i}", reason="tagged", other_tags=[],
            stage="import", status="failed", error="Timeout",
        ))
    return report


class TestReportExitCodes:
    def test_no_failures_produces_no_failure_entries(self):
        report = make_report(failures=0, succeeded=2)
        with tempfile.TemporaryDirectory() as tmp:
            report.write_all(tmp)
            with open(os.path.join(tmp, "failures.json")) as f:
                data = json.load(f)
        assert data == []

    def test_failures_present_in_json(self):
        report = make_report(failures=2, succeeded=1)
        with tempfile.TemporaryDirectory() as tmp:
            report.write_all(tmp)
            with open(os.path.join(tmp, "failures.json")) as f:
                data = json.load(f)
        assert len(data) == 2

    def test_dry_run_labeled_in_summary(self):
        report = RunReport(
            org_key="sales", run_id="1", timestamp="T",
            dry_run=True, source_url="u", source_org_id=1,
            target_url="u2", target_org_id=2, migration_tag="t",
        )
        with tempfile.TemporaryDirectory() as tmp:
            report.write_all(tmp)
            with open(os.path.join(tmp, "migration_summary.txt")) as f:
                content = f.read()
        assert "DRY-RUN" in content
