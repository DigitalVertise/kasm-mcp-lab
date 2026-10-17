# macOS-themed frontend/web dev desktop: Kasm Ubuntu 24.04 XFCE skinned with
# WhiteSur (GTK + icons), a Plank dock and top panel, plus Node.js, pnpm and
# VS Code. It looks like macOS; it is Linux (see README / ADR-003).
ARG KASM_TAG=1.18.0
FROM kasmweb/ubuntu-noble-desktop:${KASM_TAG}
ARG NODE_MAJOR=22

USER root

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      plank fonts-inter sassc libglib2.0-dev-bin gnupg ca-certificates \
      xdotool imagemagick x11-utils wmctrl git curl jq build-essential \
 && rm -rf /var/lib/apt/lists/*

# Node.js (NodeSource) + pnpm via corepack
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && corepack enable \
 && rm -rf /var/lib/apt/lists/*

# VS Code (Microsoft apt repo)
RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
 && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/code stable main" \
      > /etc/apt/sources.list.d/vscode.list \
 && apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends code \
 && rm -rf /var/lib/apt/lists/*

# WhiteSur theme + icons (cosmetic: warn, don't fail, if upstream changes)
RUN git clone --depth 1 https://github.com/vinceliuice/WhiteSur-gtk-theme.git /tmp/ws \
 && (cd /tmp/ws && ./install.sh -d /usr/share/themes -c light -c dark) || echo "WARN: WhiteSur GTK install failed" ; \
    rm -rf /tmp/ws
RUN git clone --depth 1 https://github.com/vinceliuice/WhiteSur-icon-theme.git /tmp/wsi \
 && (cd /tmp/wsi && ./install.sh -d /usr/share/icons) || echo "WARN: WhiteSur icon install failed" ; \
    rm -rf /tmp/wsi

COPY --chmod=0755 custom_startup.sh /dockerstartup/custom_startup.sh
USER 1000
