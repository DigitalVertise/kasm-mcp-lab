"""Docker-backed operations on the Kasm desktop containers.

Only containers labelled ``mcp.managed=true`` are reachable; everything else on
the Docker host is invisible to the agent. All Docker calls go through the
socket proxy (DOCKER_HOST=tcp://docker-proxy:2375).
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import docker
from docker.errors import DockerException, NotFound

MANAGED_LABEL = "mcp.managed"
ENV_LABEL = "mcp.env_id"
OS_LABEL = "mcp.os"
DESKTOP_USER = "kasm-user"
DISPLAY = ":1"
MAX_OUTPUT = int(os.environ.get("MCP_MAX_OUTPUT_CHARS", "20000"))


class DesktopError(RuntimeError):
    """Error whose message is safe to return to the agent."""


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str

    def as_dict(self) -> dict:
        return {"exit_code": self.exit_code, "stdout": self.stdout, "stderr": self.stderr}


def truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n... [{len(text) - limit} chars truncated] ...\n{text[-half:]}"


class Desktops:
    def __init__(self, client: docker.DockerClient | None = None):
        self._client = client

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            try:
                self._client = docker.from_env(timeout=30)
            except DockerException as exc:
                raise DesktopError(f"Docker API unreachable: {exc}") from exc
        return self._client

    # ------------------------------------------------------------ lookup ---
    def _managed(self, all_states: bool = True):
        return self.client.containers.list(all=all_states, filters={"label": f"{MANAGED_LABEL}=true"})

    def get(self, env_id: str):
        for c in self._managed():
            if c.labels.get(ENV_LABEL) == env_id:
                return c
        known = sorted(c.labels.get(ENV_LABEL, c.name) for c in self._managed())
        raise DesktopError(f"Unknown environment '{env_id}'. Known: {', '.join(known) or 'none'}")

    def _running(self, env_id: str):
        c = self.get(env_id)
        c.reload()
        if c.status != "running":
            raise DesktopError(f"Environment '{env_id}' is {c.status}; start it with restart_environment.")
        return c

    # ------------------------------------------------------------- tools ---
    def list(self) -> list[dict]:
        out = []
        for c in sorted(self._managed(), key=lambda c: c.labels.get(ENV_LABEL, "")):
            attrs = c.attrs
            ports = attrs.get("NetworkSettings", {}).get("Ports") or {}
            host_port = None
            for binding in ports.get("6901/tcp") or []:
                host_port = binding.get("HostPort")
            out.append({
                "env_id": c.labels.get(ENV_LABEL),
                "os": c.labels.get(OS_LABEL),
                "container": c.name,
                "status": c.status,
                "health": attrs.get("State", {}).get("Health", {}).get("Status", "n/a"),
                "started_at": attrs.get("State", {}).get("StartedAt"),
                "image": attrs.get("Config", {}).get("Image"),
                "desktop_host_port": host_port,
            })
        return out

    def exec(self, env_id: str, command: str, timeout_s: int = 60,
             workdir: str | None = None, as_root: bool = False) -> ExecResult:
        if not command.strip():
            raise DesktopError("command must not be empty")
        timeout_s = max(1, min(int(timeout_s), 900))
        c = self._running(env_id)
        argv = ["timeout", "--kill-after=5", str(timeout_s), "bash", "-lc", command]
        try:
            code, (out, err) = c.exec_run(
                argv,
                user="root" if as_root else DESKTOP_USER,
                workdir=workdir or f"/home/{DESKTOP_USER}",
                environment={"DISPLAY": DISPLAY, "HOME": f"/home/{DESKTOP_USER}"},
                demux=True,
            )
        except DockerException as exc:
            raise DesktopError(f"exec failed: {exc}") from exc
        stdout = (out or b"").decode("utf-8", "replace")
        stderr = (err or b"").decode("utf-8", "replace")
        if code == 124:
            stderr += f"\n[timed out after {timeout_s}s]"
        return ExecResult(code if code is not None else -1, truncate(stdout), truncate(stderr))

    def logs(self, env_id: str, tail: int = 200, since_minutes: int | None = None) -> str:
        c = self.get(env_id)
        kwargs: dict = {"tail": max(1, min(int(tail), 5000)), "timestamps": True}
        if since_minutes:
            kwargs["since"] = datetime.now(timezone.utc) - timedelta(minutes=int(since_minutes))
        return truncate(c.logs(**kwargs).decode("utf-8", "replace"))

    def restart(self, env_id: str) -> dict:
        c = self.get(env_id)
        c.reload()
        if c.status == "running":
            c.restart(timeout=20)
        else:
            c.start()
        c.reload()
        return {"env_id": env_id, "status": c.status}

    def screenshot(self, env_id: str, max_width: int = 1280) -> bytes:
        c = self._running(env_id)
        max_width = max(320, min(int(max_width), 3840))
        cmd = f"import -window root -resize '{max_width}x>' png:-"
        code, (out, err) = c.exec_run(
            ["bash", "-lc", cmd], user=DESKTOP_USER,
            environment={"DISPLAY": DISPLAY}, demux=True,
        )
        if code != 0 or not out:
            raise DesktopError(f"screenshot failed: {(err or b'').decode(errors='replace').strip()}")
        return out

    def gui(self, env_id: str, action: str, x: int | None = None, y: int | None = None,
            text: str | None = None, keys: str | None = None, button: int = 1,
            amount: int = 3) -> ExecResult:
        q = shlex.quote
        if action == "move":
            if x is None or y is None:
                raise DesktopError("'move' needs x and y")
            cmd = f"xdotool mousemove {int(x)} {int(y)}"
        elif action in ("click", "double_click"):
            reps = 2 if action == "double_click" else 1
            pre = f"xdotool mousemove {int(x)} {int(y)} && " if x is not None and y is not None else ""
            cmd = f"{pre}xdotool click --repeat {reps} {int(button)}"
        elif action == "type":
            if text is None:
                raise DesktopError("'type' needs text")
            cmd = f"xdotool type --delay 25 -- {q(text)}"
        elif action == "key":
            if not keys:
                raise DesktopError("'key' needs keys, e.g. 'ctrl+l' or 'Return'")
            cmd = "xdotool key -- " + " ".join(q(k) for k in keys.split())
        elif action == "scroll":
            btn = 4 if amount > 0 else 5
            pre = f"xdotool mousemove {int(x)} {int(y)} && " if x is not None and y is not None else ""
            cmd = f"{pre}xdotool click --repeat {abs(int(amount))} {btn}"
        elif action == "windows":
            cmd = "wmctrl -lG"
        else:
            raise DesktopError("action must be one of move, click, double_click, type, key, scroll, windows")
        return self.exec(env_id, cmd, timeout_s=30)

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:  # noqa: BLE001
            return False


__all__ = ["Desktops", "DesktopError", "ExecResult", "NotFound", "truncate"]
