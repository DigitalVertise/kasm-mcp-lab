#!/usr/bin/env bash
# =============================================================================
# setup.sh — bootstrap the Kasm multi-OS desktop lab + MCP server
#
#   ./setup.sh               preflight, secrets, network, build, start, verify
#   ./setup.sh --no-build    same, but reuse already-built images
#   ./setup.sh --verify      only run the verification checks
#   ./setup.sh --public-mcp  (Codespaces) also make port 8811 publicly reachable
#   ./setup.sh --down        stop and remove the stack (keeps ./shared and .env)
#   ./setup.sh --rotate      regenerate VNC_PW and MCP_AUTH_TOKEN, then restart
# =============================================================================
set -Eeuo pipefail
cd "$(dirname "$0")"

BUILD=1 VERIFY_ONLY=0 PUBLIC_MCP=0 DOWN=0 ROTATE=0
for arg in "$@"; do
  case "$arg" in
    --no-build) BUILD=0 ;;
    --verify) VERIFY_ONLY=1 ;;
    --public-mcp) PUBLIC_MCP=1 ;;
    --down) DOWN=1 ;;
    --rotate) ROTATE=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

c_ok=$'\e[32m'; c_warn=$'\e[33m'; c_err=$'\e[31m'; c_dim=$'\e[2m'; c_off=$'\e[0m'
ok()   { echo "${c_ok}✔${c_off} $*"; }
warn() { echo "${c_warn}!${c_off} $*"; }
die()  { echo "${c_err}✘ $*${c_off}" >&2; exit 1; }
step() { echo; echo "${c_dim}── $*${c_off}"; }
trap 'die "failed at line $LINENO: $BASH_COMMAND"' ERR

DC=(docker compose)

# ---------------------------------------------------------------- preflight --
preflight() {
  step "Preflight"
  command -v docker >/dev/null || die "docker not found (in Codespaces, rebuild with the included .devcontainer)"
  docker info >/dev/null 2>&1 || die "Docker daemon not reachable. In Codespaces: wait for docker-in-docker to start, or run 'sudo service docker start'."
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 plugin missing"
  command -v curl >/dev/null || die "curl is required"
  ok "Docker $(docker version -f '{{.Server.Version}}'), $(docker compose version --short)"

  local mem_gb cpus
  mem_gb=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 0)
  cpus=$(nproc 2>/dev/null || echo 0)
  if (( mem_gb < 14 )); then
    warn "Only ${mem_gb} GB RAM. Three desktops want ~12 GB; lower DESKTOP_MEMORY in .env or pick a larger Codespace."
  else ok "${cpus} CPUs, ${mem_gb} GB RAM"; fi

  local avail_gb
  avail_gb=$(df -Pk . | awk 'NR==2 {printf "%d", $4/1024/1024}')
  (( avail_gb >= 20 )) && ok "${avail_gb} GB free disk" || warn "Only ${avail_gb} GB free disk; images need ~15 GB."

  if [[ -n "${CODESPACES:-}" ]]; then ok "Running in GitHub Codespace '${CODESPACE_NAME:-?}'"; fi
}

# ------------------------------------------------------------------ secrets --
# Reads a finite chunk first, so no SIGPIPE under pipefail.
rand() { head -c 8192 /dev/urandom | LC_ALL=C tr -dc "$1" | cut -c "1-$2"; }
set_env() { # key value
  if grep -qE "^$1=" .env; then sed -i.bak "s|^$1=.*|$1=$2|" .env && rm -f .env.bak
  else echo "$1=$2" >>.env; fi
}
ensure_env() {
  step "Environment (.env)"
  if [[ ! -f .env ]]; then cp .env.example .env; ok "Created .env from .env.example"; fi
  chmod 600 .env
  # shellcheck disable=SC1091
  set -a; . ./.env; set +a
  if [[ -z "${VNC_PW:-}" || $ROTATE == 1 ]]; then set_env VNC_PW "$(rand 'A-Za-z0-9' 20)"; ok "Generated VNC_PW"; fi
  if [[ -z "${MCP_AUTH_TOKEN:-}" || $ROTATE == 1 ]]; then set_env MCP_AUTH_TOKEN "$(rand 'a-f0-9' 48)"; ok "Generated MCP_AUTH_TOKEN"; fi
  set -a; . ./.env; set +a
  ok "Ports: portal ${PORTAL_PORT} · linux ${LINUX_PORT} · windows ${WINDOWS_PORT} · macos ${MACOS_PORT} · mcp ${MCP_PORT}"
}

# ---------------------------------------------------- network + shared dirs --
ensure_network() {
  step "Docker network"
  if docker network inspect "$DOCKER_NETWORK" >/dev/null 2>&1; then ok "Network '$DOCKER_NETWORK' exists"
  else docker network create --driver bridge --label app=kasm-mcp "$DOCKER_NETWORK" >/dev/null; ok "Created network '$DOCKER_NETWORK'"; fi
}

ensure_shared() {
  step "Shared volume"
  mkdir -p shared
  touch shared/.gitkeep
  # Desktops (kasm-user) and the MCP server both run as uid 1000.
  if [[ "$(stat -c %u shared)" != "1000" ]]; then
    if chown 1000:1000 shared 2>/dev/null || sudo -n chown 1000:1000 shared 2>/dev/null; then :; else chmod 0777 shared; fi
  fi
  chmod u+rwx,g+rwx shared
  ok "./shared → ~/shared in every desktop and /shared in the MCP server"
}

check_ports() {
  step "Port availability"
  local p owner
  for p in "$PORTAL_PORT" "$LINUX_PORT" "$WINDOWS_PORT" "$MACOS_PORT" "$MCP_PORT"; do
    if (exec 3<>/dev/tcp/127.0.0.1/"$p") 2>/dev/null; then
      owner=$(docker ps --filter "publish=$p" --format '{{.Names}}' | head -1)
      if [[ "$owner" == kasm-mcp-* ]]; then ok "$p in use by $owner (this stack)"
      else die "Port $p is already in use by another process${owner:+ ($owner)}. Change it in .env."; fi
    else ok "$p free"; fi
  done
}

# ------------------------------------------------------------ build + start --
start() {
  step "Build & start"
  if (( BUILD )); then "${DC[@]}" build --pull; fi
  "${DC[@]}" up -d --remove-orphans
  ok "Containers started"
}

wait_healthy() {
  step "Waiting for health checks (up to 5 min)"
  local svc deadline=$((SECONDS + 300)) state
  for svc in portal mcp-server linux windows macos; do
    while :; do
      state=$("${DC[@]}" ps --format '{{.Health}}' "$svc" 2>/dev/null | head -1)
      [[ "$state" == "healthy" ]] && { ok "$svc healthy"; break; }
      (( SECONDS > deadline )) && { warn "$svc not healthy yet (state: ${state:-unknown}). Check: docker compose logs $svc"; break; }
      sleep 3
    done
  done
}

# ---------------------------------------------------------------- verify -----
public_url() { # port
  if [[ -n "${CODESPACE_NAME:-}" ]]; then
    echo "https://${CODESPACE_NAME}-$1.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  else echo "http(s)://localhost:$1"; fi
}

verify() {
  step "Verification"
  set -a; . ./.env; set +a
  local fail=0 code svc shm

  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORTAL_PORT}/healthz" || true)
  [[ "$code" == 200 ]] && ok "Portal      :${PORTAL_PORT}  HTTP 200" || { warn "Portal :${PORTAL_PORT} returned ${code}"; fail=1; }

  for pair in "linux:$LINUX_PORT" "windows:$WINDOWS_PORT" "macos:$MACOS_PORT"; do
    svc=${pair%%:*}; p=${pair##*:}
    code=$(curl -sk -o /dev/null -w '%{http_code}' "https://127.0.0.1:${p}/" || true)
    if [[ "$code" =~ ^(200|401)$ ]]; then ok "$(printf '%-11s' "$svc") :${p}  KasmVNC HTTPS ${code}"
    else warn "$svc :${p} returned ${code:-no response}"; fail=1; fi
    shm=$(docker inspect -f '{{.HostConfig.ShmSize}}' "$("${DC[@]}" ps -q "$svc")" 2>/dev/null || echo 0)
    (( shm >= 536870912 )) && ok "            /dev/shm = $((shm / 1024 / 1024)) MiB" \
                         || { warn "$svc /dev/shm is $((shm / 1024 / 1024)) MiB (< 512 MiB)"; fail=1; }
  done

  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${MCP_PORT}/healthz" || true)
  [[ "$code" == 200 ]] && ok "MCP health  :${MCP_PORT}  HTTP 200" || { warn "MCP /healthz returned ${code}"; fail=1; }

  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:${MCP_PORT}/mcp" -H 'Content-Type: application/json' -d '{}' || true)
  [[ "$code" == 401 ]] && ok "MCP auth    rejects unauthenticated requests" || { warn "MCP without token returned ${code} (expected 401)"; fail=1; }

  local body
  body=$(curl -s -X POST "http://127.0.0.1:${MCP_PORT}/mcp" \
    -H "Authorization: Bearer ${MCP_AUTH_TOKEN}" -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_environments","arguments":{}}}' || true)
  if grep -q 'env_id' <<<"$body" && grep -q 'linux' <<<"$body" && grep -q 'windows' <<<"$body" && grep -q 'macos' <<<"$body"; then
    ok "MCP tools   list_environments sees linux, windows, macos"
  else warn "MCP list_environments unexpected response: ${body:0:300}"; fail=1; fi

  if [[ -n "${CODESPACE_NAME:-}" ]] && command -v gh >/dev/null; then
    gh codespace ports -c "$CODESPACE_NAME" 2>/dev/null | grep -E '^(Portal|Linux|Windows|macOS|MCP)|\b(3000|690[123]|8811)\b' >/dev/null \
      && ok "Codespace port forwarding active" || warn "Could not confirm Codespace port forwarding (open the PORTS tab)."
  fi
  return $fail
}

make_mcp_public() {
  [[ -n "${CODESPACE_NAME:-}" ]] || { warn "--public-mcp only applies inside a Codespace"; return; }
  command -v gh >/dev/null || { warn "gh CLI missing; set port 8811 to Public in the PORTS tab"; return; }
  gh codespace ports visibility "${MCP_PORT}:public" -c "$CODESPACE_NAME" >/dev/null \
    && ok "Port ${MCP_PORT} is now Public (still protected by MCP_AUTH_TOKEN)" \
    || warn "Could not change visibility; do it in the PORTS tab"
}

summary() {
  set -a; . ./.env; set +a
  local mcp_url; mcp_url="$(public_url "$MCP_PORT")/mcp"
  cat <<EOF

${c_ok}Lab is up.${c_off}
  Portal          $(public_url "$PORTAL_PORT")
  Linux desktop   $(public_url "$LINUX_PORT")
  Windows apps    $(public_url "$WINDOWS_PORT")
  macOS-style dev $(public_url "$MACOS_PORT")
  Desktop login   kasm_user / (VNC_PW in .env)   →  grep VNC_PW .env

  MCP endpoint    ${mcp_url}
  MCP token       grep MCP_AUTH_TOKEN .env
  Claude Code     claude mcp add --transport http kasm ${mcp_url} --header "Authorization: Bearer \$MCP_AUTH_TOKEN"

  Next: README.md → "Connect an agent". Stop with ./setup.sh --down
EOF
}

# -------------------------------------------------------------------- main ---
if (( DOWN )); then
  "${DC[@]}" down --remove-orphans && ok "Stack stopped (./shared and .env kept)"; exit 0
fi
preflight
ensure_env
if (( VERIFY_ONLY )); then verify && ok "All checks passed" || die "Some checks failed"; exit 0; fi
ensure_network
ensure_shared
check_ports
start
wait_healthy
(( PUBLIC_MCP )) && make_mcp_public
if verify; then ok "All checks passed"; else warn "Some checks failed; see messages above."; fi
summary
