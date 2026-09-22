"""Tests for TSClient: auth, retry, token refresh, secret masking."""
import time
import pytest
from unittest.mock import MagicMock, patch, call

from scripts.lib.ts_client import TSClient


BASE_URL = "https://dev.example.com"
USERNAME = "admin"
SECRET_KEY = "super_secret_key"
ORG_ID = 12


@pytest.fixture
def client():
    return TSClient(BASE_URL, USERNAME, SECRET_KEY, ORG_ID)


class TestAuthenticate:
    def test_stores_token(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "token": "tok_abc",
            "token_validity_duration_in_sec": 3600,
            "org_id": ORG_ID,
        }
        with patch("requests.Session.post", return_value=mock_resp):
            client.authenticate()
        assert client._token == "tok_abc"

    def test_raises_on_org_mismatch(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "token": "tok_abc",
            "token_validity_duration_in_sec": 3600,
            "org_id": 999,  # wrong org
        }
        with patch("requests.Session.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="org mismatch"):
                client.authenticate()

    def test_secret_not_in_exception_message(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_resp.raise_for_status.side_effect = Exception("401")
        with patch("requests.Session.post", return_value=mock_resp):
            try:
                client.authenticate()
            except Exception as e:
                assert SECRET_KEY not in str(e)


class TestRetry:
    def test_retries_on_429(self, client):
        client._token = "tok"
        client._token_expires_at = time.time() + 3600

        fail_resp = MagicMock(status_code=429, headers={"Retry-After": "0"})
        fail_resp.raise_for_status.side_effect = Exception("429")
        ok_resp = MagicMock(status_code=200)
        ok_resp.raise_for_status.return_value = None
        ok_resp.json.return_value = {"data": []}

        with patch.object(client._session, "request",
                          side_effect=[fail_resp, ok_resp]) as mock_req:
            result = client.request("GET", "/api/rest/2.0/metadata/search")
        assert mock_req.call_count == 2

    def test_no_retry_on_400(self, client):
        client._token = "tok"
        client._token_expires_at = time.time() + 3600

        bad_resp = MagicMock(status_code=400)
        bad_resp.raise_for_status.side_effect = Exception("400 Bad Request")

        with patch.object(client._session, "request", return_value=bad_resp):
            with pytest.raises(Exception, match="400"):
                client.request("GET", "/api/rest/2.0/metadata/search")


class TestTokenRefresh:
    def test_reauthenticates_when_token_near_expiry(self, client):
        client._token = "old_tok"
        # set expiry to 30 seconds from now (within 60s buffer)
        client._token_expires_at = time.time() + 30

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "token": "new_tok",
            "token_validity_duration_in_sec": 3600,
            "org_id": ORG_ID,
        }
        with patch("requests.Session.post", return_value=mock_resp):
            client._ensure_token()
        assert client._token == "new_tok"
