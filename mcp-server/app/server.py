"""MCP server exposing the Kasm desktops to AI agents.

Transport: Streamable HTTP at /mcp (stateless, JSON responses).
Auth:      `Authorization: Bearer <MCP_AUTH_TOKEN>` or `?key=<MCP_AUTH_TOKEN>`
           (the query form exists for clients that cannot set headers, such as
           claude.ai custom connectors).
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from pathlib import Path
from typing import Literal

import anyio
import uvicorn
from mcp.server.fastmcp import FastMCP, Image
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .desktops import DesktopError, Desktops, truncate

log = logging.getLogger("kasm-mcp")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")
PORT = int(os.environ.get("MCP_PORT", "8811"))
SHARED = Path(os.environ.get("SHARED_DIR", "/shared")).resolve()
MAX_FILE_BYTES = 5 * 1024 * 1024

desktops = Desktops()

mcp = FastMCP(
    "kasm-desktops",
    instructions=(
        "Controls three streamed desktop containers: env_id 'linux' (Ubuntu XFCE), "
        "'windows' (Wine app sandbox; run Windows apps with `wine app.exe`) and "
        "'macos' (macOS-themed Linux dev desktop with Node.js and VS Code). "
        "Start with list_environments. Prefer exec_command for anything scriptable; "
        "use screenshot + gui_action only for GUI-only tasks. Files placed in the "
        "shared folder appear at ~/shared in every desktop."
    ),
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    json_response=True,
)


async def _run(fn, *args, **kwargs):
    """Run a blocking Docker call off the event loop, mapping errors for the agent."""
    try:
        return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))
    except DesktopError as exc:
        raise ValueError(str(exc)) from exc


EnvId = Literal["linux", "windows", "macos"]


# ------------------------------------------------------------------ tools ---
@mcp.tool()
async def list_environments() -> str:
    """List the desktop environments with status, health and OS description."""
    return json.dumps(await _run(desktops.list), indent=2)


@mcp.tool()
async def exec_command(env_id: EnvId, command: str, timeout_seconds: int = 60,
                       workdir: str | None = None, as_root: bool = False) -> str:
    """Run a bash command inside a desktop (as kasm-user unless as_root).

    DISPLAY=:1 is set, so GUI apps launched here appear on the streamed desktop
    (append `&` / use `nohup ... &` for long-running apps). Returns JSON with
    exit_code, stdout and stderr (truncated when large). Max timeout 900 s.
    """
    res = await _run(desktops.exec, env_id, command, timeout_seconds, workdir, as_root)
    log.info("exec env=%s root=%s exit=%s cmd=%r", env_id, as_root, res.exit_code, command[:200])
    return json.dumps(res.as_dict(), indent=2)


@mcp.tool()
async def get_logs(env_id: EnvId, tail: int = 200, since_minutes: int | None = None) -> str:
    """Return the container logs (KasmVNC, desktop startup) for an environment."""
    return await _run(desktops.logs, env_id, tail, since_minutes)


@mcp.tool()
async def screenshot(env_id: EnvId, max_width: int = 1280) -> Image:
    """Capture the current desktop as a PNG (downscaled to max_width)."""
    data = await _run(desktops.screenshot, env_id, max_width)
    return Image(data=data, format="png")


@mcp.tool()
async def gui_action(env_id: EnvId,
                     action: Literal["move", "click", "double_click", "type", "key", "scroll", "windows"],
                     x: int | None = None, y: int | None = None, text: str | None = None,
                     keys: str | None = None, button: int = 1, amount: int = 3) -> str:
    """Drive the mouse/keyboard with xdotool.

    Coordinates are in full-resolution screen pixels; if a screenshot was
    downscaled, scale coordinates back up. `keys` uses xdotool names separated
    by spaces, e.g. "ctrl+l", "Return", "alt+F4". `scroll` amount >0 is up.
    `windows` lists open windows with geometry.
    """
    res = await _run(desktops.gui, env_id, action, x, y, text, keys, button, amount)
    return json.dumps(res.as_dict(), indent=2)


@mcp.tool()
async def restart_environment(env_id: EnvId) -> str:
    """Restart (or start, if stopped) a desktop container."""
    return json.dumps(await _run(desktops.restart, env_id))


def _shared_path(rel: str) -> Path:
    p = (SHARED / rel.lstrip("/")).resolve()
    if p != SHARED and SHARED not in p.parents:
        raise ValueError("path escapes the shared folder")
    return p


@mcp.tool()
async def list_shared_files(subdir: str = "") -> str:
    """List files in the shared folder (~/shared in every desktop)."""
    base = _shared_path(subdir)
    if not base.is_dir():
        raise ValueError(f"not a directory: {subdir or '/'}")
    items = [{"path": str(f.relative_to(SHARED)), "dir": f.is_dir(),
              "bytes": f.stat().st_size if f.is_file() else None}
             for f in sorted(base.iterdir())]
    return json.dumps(items, indent=2)


@mcp.tool()
async def read_shared_file(path: str) -> str:
    """Read a UTF-8 text file from the shared folder."""
    p = _shared_path(path)
    if not p.is_file():
        raise ValueError(f"no such file: {path}")
    if p.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("file larger than 5 MB; use exec_command to inspect it")
    return truncate(p.read_text("utf-8", errors="replace"))


@mcp.tool()
async def write_shared_file(path: str, content: str) -> str:
    """Write a UTF-8 text file into the shared folder (creates parent dirs)."""
    if len(content.encode()) > MAX_FILE_BYTES:
        raise ValueError("content larger than 5 MB")
    p = _shared_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, "utf-8")
    return f"wrote {p.relative_to(SHARED)} ({len(content)} chars); visible at ~/shared/{p.relative_to(SHARED)}"


# ------------------------------------------------------------------- http ---
@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
    docker_ok = await anyio.to_thread.run_sync(desktops.ping)
    return JSONResponse({"ok": True, "docker": docker_ok}, status_code=200)


class BearerAuth(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        header = request.headers.get("authorization", "")
        supplied = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("key", "")
        if not TOKEN or not hmac.compare_digest(supplied.encode(), TOKEN.encode()):
            return JSONResponse({"error": "unauthorized"}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})
        return await call_next(request)


def build_app():
    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuth)
    return app


def main() -> None:
    if len(TOKEN) < 24:
        raise SystemExit("MCP_AUTH_TOKEN must be set (>= 24 chars). Run ./setup.sh.")
    log.info("kasm-mcp listening on :%s/mcp (shared=%s)", PORT, SHARED)
    uvicorn.run(build_app(), host="0.0.0.0", port=PORT, log_level=os.environ.get("LOG_LEVEL", "info").lower(),
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
