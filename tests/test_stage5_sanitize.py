"""Tests for Stage 5: sanitize and parameterization checks."""
import pytest
from scripts.stage5_sanitize import (
    check_parameterization,
    SanitizeWarning,
)


class TestCheckParameterization:
    def test_warns_on_literal_db(self, sample_org_config):
        tml = {
            "table": {
                "db": "DEV_DB",  # literal source value
                "schema": "DEV_SCHEMA",
            }
        }
        warnings = check_parameterization(
            tml,
            source_db="DEV_DB",
            source_schema="DEV_SCHEMA",
        )
        assert len(warnings) > 0
        assert any("db" in w.field for w in warnings)

    def test_no_warning_on_variable_bound(self):
        tml = {
            "table": {
                "db": "${ts_db_name}",
                "schema": "${ts_schema_name}",
            }
        }
        warnings = check_parameterization(
            tml, source_db="DEV_DB", source_schema="DEV_SCHEMA"
        )
        assert warnings == []

    def test_no_warning_for_non_table(self, sample_liveboard_tml):
        warnings = check_parameterization(
            sample_liveboard_tml, source_db="DEV_DB", source_schema="DEV_SCHEMA"
        )
        assert warnings == []
