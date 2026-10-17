# Windows-compatible app sandbox: Kasm Ubuntu 24.04 XFCE + Wine (32/64-bit)
# + winetricks, skinned with the Chicago95 (Windows 95-style) theme.
# This runs Windows *applications*, not Windows itself (see README / ADR-003).
ARG KASM_TAG=1.18.0
FROM kasmweb/ubuntu-noble-desktop:${KASM_TAG}

USER root

RUN dpkg --add-architecture i386 \
 && apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      wine wine64 wine32:i386 winetricks cabextract p7zip-full \
      xdotool imagemagick x11-utils wmctrl git curl jq \
 && rm -rf /var/lib/apt/lists/*

# Cosmetic theme: warn instead of failing the build if the upstream layout moves.
RUN git clone --depth 1 https://github.com/grassmunk/Chicago95.git /tmp/c95 \
 && { [ -d /tmp/c95/Theme/Chicago95 ] && cp -r /tmp/c95/Theme/Chicago95 /usr/share/themes/ || echo "WARN: Chicago95 GTK theme not found"; } \
 && { [ -d /tmp/c95/Icons/Chicago95 ] && cp -r /tmp/c95/Icons/Chicago95 /usr/share/icons/ || echo "WARN: Chicago95 icons not found"; } \
 && { [ -d /tmp/c95/Cursors/Chicago95_Cursor_Black ] && cp -r /tmp/c95/Cursors/Chicago95_Cursor_Black /usr/share/icons/ || true; } \
 && rm -rf /tmp/c95

COPY --chmod=0755 custom_startup.sh /dockerstartup/custom_startup.sh
USER 1000
