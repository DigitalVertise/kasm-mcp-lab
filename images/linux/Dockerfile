# Linux desktop: stock Kasm Ubuntu 24.04 XFCE desktop + the small set of
# X11 tools the MCP server needs for screenshots and GUI automation.
ARG KASM_TAG=1.18.0
FROM kasmweb/ubuntu-noble-desktop:${KASM_TAG}

USER root
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      xdotool imagemagick x11-utils wmctrl git curl jq \
 && rm -rf /var/lib/apt/lists/*

COPY --chmod=0755 custom_startup.sh /dockerstartup/custom_startup.sh
USER 1000
