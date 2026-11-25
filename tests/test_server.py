"""The web API's safeguards (no model calls)."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from forgeai import server

client = TestClient(server.app)
FILES = {"files": ("a.txt", b"hello", "text/plain")}
FORM = {"brief": "An assistant that answers questions about the handbook.", "name": "new_agent"}


def test_public_server_without_code_cannot_build(monkeypatch):
    monkeypatch.setattr(server, "PUBLIC", True)
    monkeypatch.setattr(server, "ACCESS_CODE", "")
    assert client.get("/api/config").json()["build_enabled"] is False
    assert client.post("/api/build", data=FORM, files=FILES).status_code == 403


def test_access_code_is_enforced(monkeypatch):
    monkeypatch.setattr(server, "ACCESS_CODE", "right")
    assert client.post("/api/build", data=FORM, files=FILES).status_code == 401
    assert client.post("/api/build", data=FORM, files=FILES, headers={"X-Access-Code": "wrong"}).status_code == 401


def test_bad_names_and_file_types_are_rejected(monkeypatch):
    monkeypatch.setattr(server, "ACCESS_CODE", "")
    monkeypatch.setattr(server, "PUBLIC", False)
    assert client.post("/api/build", data={**FORM, "name": "../x"}, files=FILES).status_code == 400
    assert client.post("/api/build", data=FORM, files={"files": ("a.exe", b"x", "application/octet-stream")}).status_code == 400
    assert client.get("/api/runs/..%2F..%2Fetc").status_code == 404


def test_chat_is_rate_limited(monkeypatch):
    monkeypatch.setattr(server, "CHAT_PER_MINUTE", 2)
    server._chat_log.clear()
    codes = [client.post("/api/runs/missing/chat", json={"question": "hi"}).status_code for _ in range(3)]
    assert codes == [404, 404, 429]
