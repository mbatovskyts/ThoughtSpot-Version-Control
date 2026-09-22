"""Tests for Stage 8: variable sync, connection preflight, validate-only import."""
import pytest
from unittest.mock import MagicMock

from scripts.stage8_prod_prep import (
    sync_variable,
    check_connection_exists,
    SyncVariableResult,
)


class TestSyncVariable:
    def _make_client(self, existing_vars=None):
        client = MagicMock()
        client.search_variables.return_value = existing_vars or []
        client.create_variable.return_value = {"id": "new-var-id", "name": "ts_db_name"}
        client.set_variable_org_value.return_value = {}
        return client

    def test_creates_missing_variable(self):
        client = self._make_client(existing_vars=[])
        result = sync_variable(
            client,
            ts_variable_name="ts_db_name",
            var_type="TABLE_MAPPING",
            target_value="PROD_DB",
            org_id=3,
        )
        assert result == SyncVariableResult.CREATED
        client.create_variable.assert_called_once()
        client.set_variable_org_value.assert_called_once()

    def test_skips_existing_same_type(self):
        existing = [{"id": "v1", "name": "ts_db_name", "type": "TABLE_MAPPING"}]
        client = self._make_client(existing_vars=existing)
        result = sync_variable(
            client,
            ts_variable_name="ts_db_name",
            var_type="TABLE_MAPPING",
            target_value="PROD_DB",
            org_id=3,
        )
        assert result == SyncVariableResult.VALUE_SET
        client.create_variable.assert_not_called()

    def test_fails_on_type_mismatch(self):
        existing = [{"id": "v1", "name": "ts_db_name", "type": "FORMULA_VARIABLE"}]
        client = self._make_client(existing_vars=existing)
        with pytest.raises(ValueError, match="type mismatch"):
            sync_variable(
                client,
                ts_variable_name="ts_db_name",
                var_type="TABLE_MAPPING",
                target_value="PROD_DB",
                org_id=3,
            )


class TestCheckConnectionExists:
    def test_returns_true_when_found(self):
        client = MagicMock()
        client.search_connections.return_value = [
            {"header": {"id": "conn-1", "name": "Snowflake_Prod"}}
        ]
        assert check_connection_exists(client, "Snowflake_Prod") is True

    def test_returns_false_when_missing(self):
        client = MagicMock()
        client.search_connections.return_value = []
        assert check_connection_exists(client, "Missing_Conn") is False
