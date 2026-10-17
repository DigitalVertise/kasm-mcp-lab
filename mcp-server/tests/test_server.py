"""Offline tests: auth, MCP handshake, tool listing and tool calls against a fake Docker API.

Run:  cd mcp-server && pip install -r requirements.txt pytest httpx && \
      MCP_AUTH_TOKEN=test-token-0123456789abcdef pytest -q
"""

import json
import os

os.environ.setdefault("MCP_AUTH_TOKEN", "test-token-0123456789abcdef")

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app import server  # noqa: E402
from app.desktops import Desktops  # noqa: E402

TOKEN = os.environ["MCP_AUTH_TOKEN"]
HDRS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


class FakeContainer:
    def __init__(self, env_id):
        self.name = f"kasm-mcp-{env_id}-1"
        self.labels = {"mcp.managed": "true", "mcp.env_id": env_id, "mcp.os": f"{env_id} desktop"}
        self.status = "running"
        self.attrs = {"State": {"Health": {"Status": "healthy"}, "StartedAt": "2026-10-17T00:00:00Z"},
                      "Config": {"Image": f"kasm-mcp/{env_id}"},
                      "NetworkSettings": {"Ports": {"6901/tcp": [{"HostPort": "6901"}]}}}
        self.calls = []

    def reload(self):
        pass

    def exec_run(self, argv, **kw):
        self.calls.append((argv, kw))
        if "import -window root" in argv[-1]:
            return 0, (b"\x89PNG\r\n\x1a\nfake", b"")
        return 0, (f"ran:{argv[-1]}".encode(), b"")

    def logs(self, **kw):
        return b"kasmvnc started\n"


class FakeClient:
    def __init__(self):
        self.cs = {e: FakeContainer(e) for e in ("linux", "windows", "macos")}
        self.containers = self

    def list(self, all=True, filters=None):  # noqa: A002
        return list(self.cs.values())

    def ping(self):
        return True


@pytest.fixture(scope="module")
def app_client():
    # The MCP session manager can only be started once per process.
    with TestClient(server.build_app()) as c:
        yield c


@pytest.fixture()
def client(app_client, tmp_path, monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(server, "desktops", Desktops(client=fake))
    monkeypatch.setattr(server, "SHARED", tmp_path.resolve())
    app_client.fake = fake
    return app_client


def rpc(c, method, params=None, id_=1, auth=True, query=False):
    url = "/mcp" + (f"?key={TOKEN}" if query else "")
    headers = dict(HDRS)
    if auth and not query:
        headers["Authorization"] = f"Bearer {TOKEN}"
    body = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}
    return c.post(url, headers=headers, json=body)


def call(c, name, args):
    r = rpc(c, "tools/call", {"name": name, "arguments": args})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_healthz_is_public(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["docker"] is True


def test_rejects_missing_or_bad_token(client):
    assert rpc(client, "tools/list", auth=False).status_code == 401
    bad = client.post("/mcp", headers={**HDRS, "Authorization": "Bearer nope"}, json={})
    assert bad.status_code == 401


def test_initialize_and_list_tools(client):
    r = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "t", "version": "0"}})
    assert r.status_code == 200 and r.json()["result"]["serverInfo"]["name"] == "kasm-desktops"
    names = {t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert {"list_environments", "exec_command", "get_logs", "screenshot", "gui_action",
            "restart_environment", "read_shared_file", "write_shared_file", "list_shared_files"} <= names


def test_query_key_auth(client):
    assert rpc(client, "tools/list", query=True).status_code == 200


def test_list_and_exec(client):
    envs = json.loads(call(client, "list_environments", {})["content"][0]["text"])
    assert {e["env_id"] for e in envs} == {"linux", "windows", "macos"}
    res = json.loads(call(client, "exec_command", {"env_id": "linux", "command": "uname -a"})["content"][0]["text"])
    assert res["exit_code"] == 0 and "uname -a" in res["stdout"]
    argv, kw = client.fake.cs["linux"].calls[-1]
    assert argv[:4] == ["timeout", "--kill-after=5", "60", "bash"] and kw["user"] == "kasm-user"


def test_screenshot_returns_image(client):
    content = call(client, "screenshot", {"env_id": "macos"})["content"][0]
    assert content["type"] == "image" and content["mimeType"] == "image/png"


def test_gui_type_is_shell_quoted(client):
    call(client, "gui_action", {"env_id": "windows", "action": "type", "text": "hi'; rm -rf /"})
    cmd = client.fake.cs["windows"].calls[-1][0][-1]
    assert cmd == "xdotool type --delay 25 -- 'hi'\"'\"'; rm -rf /'"


def test_shared_files_and_traversal(client):
    call(client, "write_shared_file", {"path": "notes/a.txt", "content": "hello"})
    assert call(client, "read_shared_file", {"path": "notes/a.txt"})["content"][0]["text"] == "hello"
    res = call(client, "read_shared_file", {"path": "../../etc/passwd"})
    assert res["isError"] is True


def test_unknown_env_is_tool_error(client):
    res = call(client, "get_logs", {"env_id": "solaris"})
    assert res["isError"] is True
