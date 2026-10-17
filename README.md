# Kasm Multi-OS Desktop Lab + MCP

Three browser-streamed desktops running in Docker inside a GitHub Codespace, plus an MCP server that lets Claude (or any MCP client) list them, run shell commands, take screenshots, drive the mouse and keyboard, read logs and exchange files.

| Service | Port | What it is |
|---|---|---|
| `portal` | 3000 | Landing page linking to every desktop and the MCP endpoint |
| `linux` | 6901 | Ubuntu 24.04 XFCE (`kasmweb/ubuntu-noble-desktop`) |
| `windows` | 6902 | Wine app sandbox (32/64-bit, winetricks), Chicago95 Windows-style theme |
| `macos` | 6903 | WhiteSur macOS-style XFCE, Plank dock, Node.js 22, pnpm, VS Code |
| `mcp-server` | 8811 | MCP over Streamable HTTP at `/mcp`, bearer-token auth |
| `docker-proxy` | internal | Least-privilege Docker API used only by `mcp-server` |

```
 Browser ──HTTPS──▶ :6901 linux ┐
                    :6902 windows├── kasm-mcp-net ── mcp-server :8811 ◀── Claude / agents
                    :6903 macos  ┘        │               │
 Browser ──HTTP───▶ :3000 portal          ./shared        └── docker-proxy ── /var/run/docker.sock (ro)
                                  (~/shared in every desktop, /shared in MCP)
```

Every desktop gets 1 GB `/dev/shm` (`DESKTOP_SHM_SIZE`), above the 512 MB minimum Chrome and GL rendering need, plus 2 CPU / 4 GB limits.

---

## 1. Quick start in a GitHub Codespace

1. Push this folder to a GitHub repo.
2. **Code → Codespaces → ⋯ → New with options**, pick an **8-core / 32 GB** machine (16 GB works if you lower `DESKTOP_MEMORY` to `3g`). The included `.devcontainer` adds Docker-in-Docker and the GitHub CLI and forwards every port.
3. In the Codespace terminal:

   ```bash
   ./setup.sh
   ```

   The first run builds three images (about 10–15 minutes). It then:
   - creates `.env` from `.env.example` and generates `VNC_PW` and `MCP_AUTH_TOKEN` (file mode 600)
   - creates the `kasm-mcp-net` network and the `./shared` folder (owned by uid 1000)
   - checks that no other process holds the ports
   - starts the stack, waits for health checks, and verifies each port, the `/dev/shm` size, MCP auth (401 without a token) and an end-to-end `list_environments` call
4. Open the **PORTS** tab and click **Portal (3000)**. Sign in to any desktop as `kasm_user` with the password from `grep VNC_PW .env`.

Other commands:

```bash
./setup.sh --verify       # re-run checks only
./setup.sh --no-build     # restart without rebuilding
./setup.sh --public-mcp   # make port 8811 public (needed for claude.ai; token still required)
./setup.sh --rotate       # new VNC_PW and MCP_AUTH_TOKEN
./setup.sh --down         # stop everything (keeps ./shared and .env)
```

Outside Codespaces, the same works on any Linux host with Docker 24+ and Compose v2.

---

## 2. Connect an agent

Your endpoint is `https://<codespace-name>-8811.app.github.dev/mcp` (printed by `setup.sh`), or `http://localhost:8811/mcp` locally. The token is in `.env`:

```bash
grep MCP_AUTH_TOKEN .env
```

Codespace ports are **private** by default, which means GitHub sign-in is required and agents can't reach them. Pick one of these:

| Option | How | Best for |
|---|---|---|
| **A. Tunnel (most secure)** | On your computer: `gh codespace ports forward 8811:8811 -c <codespace-name>`, then use `http://localhost:8811/mcp` | Claude Desktop, Claude Code on your laptop |
| **B. Public port** | `./setup.sh --public-mcp` (or set 8811 to Public in the PORTS tab) | claude.ai, phones, cloud agents |

### Claude Code

```bash
claude mcp add --transport http kasm https://<codespace>-8811.app.github.dev/mcp \
  --header "Authorization: Bearer <MCP_AUTH_TOKEN>"
```

### Claude Desktop

Claude Desktop launches local stdio servers from its config, so use the `mcp-remote` bridge (needs Node.js on your computer). Edit `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "kasm-desktops": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8811/mcp",
               "--header", "Authorization: Bearer ${KASM_MCP_TOKEN}"],
      "env": { "KASM_MCP_TOKEN": "<MCP_AUTH_TOKEN>" }
    }
  }
}
```

Use the tunnel URL from option A, or the public URL from option B. Restart Claude Desktop.

### claude.ai (web and mobile)

Custom connectors can't send custom headers, so the server also accepts the token as a query parameter:

1. Run `./setup.sh --public-mcp`.
2. In claude.ai: **Settings → Connectors → Add custom connector**, URL `https://<codespace>-8811.app.github.dev/mcp?key=<MCP_AUTH_TOKEN>`.
3. The connector then works from the Claude mobile app too.

The token is part of the URL here, so treat the URL as a secret and run `./setup.sh --rotate` if it leaks.

### Custom agents (Python)

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "https://<codespace>-8811.app.github.dev/mcp"
HEADERS = {"Authorization": "Bearer <MCP_AUTH_TOKEN>"}

async def main():
    async with streamablehttp_client(URL, headers=HEADERS) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            print(await s.call_tool("list_environments", {}))
            print(await s.call_tool("exec_command", {"env_id": "macos", "command": "node -v"}))

asyncio.run(main())
```

Quick check with curl:

```bash
curl -s https://<codespace>-8811.app.github.dev/mcp \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

---

## 3. MCP tools

`env_id` is one of `linux`, `windows`, `macos`.

| Tool | Purpose |
|---|---|
| `list_environments` | Status, health, OS description, image and port of each desktop |
| `exec_command` | Run bash as `kasm-user` (or root with `as_root`), with `DISPLAY=:1` so GUI apps open on the desktop. Timeout up to 900 s; output truncated at `MCP_MAX_OUTPUT_CHARS` |
| `get_logs` | Container logs (`tail`, `since_minutes`) |
| `screenshot` | PNG of the desktop, downscaled to `max_width` |
| `gui_action` | `move`, `click`, `double_click`, `type`, `key` (e.g. `ctrl+l`), `scroll`, `windows` (list windows) via xdotool |
| `restart_environment` | Restart, or start if stopped |
| `list_shared_files` / `read_shared_file` / `write_shared_file` | Files in `./shared`, visible at `~/shared` in every desktop (5 MB limit, path traversal blocked) |

Examples to try in Claude:

- "Take a screenshot of the macOS desktop."
- "In the macos env, scaffold a Vite React app in ~/projects/demo, start the dev server, open it in Chrome and screenshot it."
- "Download PuTTY's Windows installer into the windows env and run it with Wine."

---

## 4. Security model

- **Docker access is mediated.** `mcp-server` never mounts the Docker socket. It talks to `docker-proxy`, which allows only container list, inspect, logs, exec, start, stop and restart. Image, volume, network, build and system APIs are blocked, and the proxy sits on an internal-only network.
- **Scope is label-based.** Only containers labelled `mcp.managed=true` can be listed or controlled.
- **Auth.** All `/mcp` requests need `MCP_AUTH_TOKEN` (constant-time compare). Only `/healthz` is public.
- **Hardened MCP container.** Read-only root filesystem, `no-new-privileges`, non-root uid 1000.
- **Binding.** Ports bind to `127.0.0.1` by default. Codespaces forwarding still works; nothing is exposed on a raw VM.
- **Blast radius.** `exec_command` is intentionally powerful inside the desktops (including `as_root`). Treat the desktops as disposable sandboxes and don't put real credentials in them.

---

## 5. Architecture decisions

**ADR-001 Standalone Kasm images instead of the full Kasm Workspaces platform.**
*Problem:* the brief mentioned "Kasm Core / Web server". *Options:* (a) install Kasm Workspaces (API, manager, agent, DB, proxy) and let it spawn sessions; (b) run Kasm's workspace images directly with Compose. *Decision:* (b), with a lightweight nginx portal on :3000. *Rationale:* Kasm Workspaces uses its own installer, needs privileged host access and spawns containers outside Compose, which fits Codespaces poorly. The images already embed KasmVNC, so each desktop streams on its own. *Tradeoff:* no Kasm admin UI, multi-user session management or recording. If you need those, install Kasm Workspaces on a dedicated VM and point the MCP server's `DOCKER_HOST` at that host.

**ADR-002 Docker-in-Docker in the Codespace.**
*Options:* Docker-in-Docker vs Docker-outside-of-Docker. *Decision:* Docker-in-Docker. *Rationale:* bind mounts such as `./shared` resolve correctly, and the stack is isolated per Codespace. *Tradeoff:* image layers are rebuilt per Codespace. Prebuilds or pushing images to GHCR remove that cost.

**ADR-003 "Windows" and "macOS" are Linux desktops.**
GitHub Codespaces has no KVM, so full Windows or macOS VMs aren't possible, and Apple's license allows macOS only on Apple hardware. The `windows` env runs Windows applications through Wine; many work, while anti-cheat, kernel drivers and some .NET/DirectX apps don't. The `macos` env is a macOS-styled Linux desktop for web and frontend work, so Safari and Xcode aren't available. For real Windows, use a cloud VM or `dockurr/windows` on a KVM host. For real macOS, use an Apple-hardware CI runner or a Mac cloud host.

**ADR-004 Python FastMCP over Streamable HTTP, stateless.**
*Rationale:* the official SDK, a single process and the docker-py client. Stateless JSON mode survives restarts and Codespace proxying. A header token or a `?key=` fallback covers both programmatic clients and claude.ai connectors.

---

## 6. Configuration (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `KASM_TAG` | `1.18.0` | Kasm image tag; check Docker Hub `kasmweb/ubuntu-noble-desktop` for newer ones |
| `NODE_MAJOR` | `22` | Node.js in the macOS-style env |
| `BIND_ADDR` | `127.0.0.1` | Use `0.0.0.0` only behind a firewall |
| `*_PORT` | 3000 / 6901–6903 / 8811 | Host ports |
| `DESKTOP_SHM_SIZE` | `1gb` | Keep it at 512m or more |
| `DESKTOP_CPUS` / `DESKTOP_MEMORY` | `2` / `4g` | Per-desktop limits |
| `MCP_MAX_OUTPUT_CHARS` | `20000` | Truncation for exec and log output |
| `TZ` | `Africa/Cairo` | Desktop time zone |

Run only some desktops with `docker compose up -d portal mcp-server docker-proxy linux`.

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `Docker daemon not reachable` | Docker-in-Docker is still starting; wait 30 s or run `sudo service docker start` |
| Desktop shows a certificate warning | Expected locally (KasmVNC self-signed cert). Codespaces URLs use GitHub's certificate |
| Desktop tab shows 502 in Codespaces | The port's protocol must be HTTPS. The devcontainer sets this; otherwise right-click the port → Change Port Protocol → HTTPS |
| Black screen or tab crash in Chrome | Confirm `/dev/shm` with `./setup.sh --verify`; raise `DESKTOP_MEMORY` |
| Theme didn't apply | Themes are fetched from GitHub at build time; check the build log for `WARN:` lines, then `docker compose restart windows macos` |
| Agent gets 401 | Token mismatch or private port. Check `grep MCP_AUTH_TOKEN .env` and the port visibility |
| Wine first launch is slow | The prefix initialises on first boot (about 1 min); check `/tmp/wineboot.log` |

Costs: Codespaces bills compute while the Codespace runs. Stop it when you're done (GitHub's idle timeout also stops it), and run `./setup.sh --no-build` after a restart.

---

## 8. Development

```bash
cd mcp-server
pip install -r requirements.txt pytest httpx
MCP_AUTH_TOKEN=test-token-0123456789abcdef pytest -q   # 9 offline tests, no Docker needed
```

```
.
├── docker-compose.yml        # stack definition
├── setup.sh                  # bootstrap + verification
├── .env.example              # config template (secrets generated by setup.sh)
├── .devcontainer/            # Codespace: Docker-in-Docker, ports, machine size
├── portal/                   # nginx landing page (:3000)
├── images/{linux,windows,macos}/   # Dockerfile + custom_startup.sh per desktop
├── mcp-server/               # FastMCP server, Docker access layer, tests
└── shared/                   # mounted at ~/shared in every desktop
```
