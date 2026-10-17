#!/usr/bin/env bash
# Applies the macOS look (WhiteSur, Inter, top panel, Plank dock) and drops
# dev launchers on the desktop.
set -u
export DISPLAY=:1
until xdpyinfo >/dev/null 2>&1; do sleep 1; done
sleep 3

apply() { xfconf-query -c "$1" -p "$2" -s "$3" --create -t string 2>/dev/null || true; }
THEME=$(ls -d /usr/share/themes/WhiteSur-Light* 2>/dev/null | head -1 | xargs -r basename)
[ -n "$THEME" ] && { apply xsettings /Net/ThemeName "$THEME"; apply xfwm4 /general/theme "$THEME"; }
ICONS=$(ls -d /usr/share/icons/WhiteSur 2>/dev/null | head -1 | xargs -r basename)
[ -n "$ICONS" ] && apply xsettings /Net/IconThemeName "$ICONS"
apply xsettings /Gtk/FontName "Inter 10"
apply xfwm4 /general/button_layout "CHM|"            # traffic lights on the left

# Move panel-1 to the top (menu bar); hide panel-2 if present (Plank replaces it).
xfconf-query -c xfce4-panel -p /panels/panel-1/position -s "p=6;x=0;y=0" --create -t string 2>/dev/null || true
xfconf-query -c xfce4-panel -p /panels/panel-2/autohide-behavior -s 2 --create -t uint 2>/dev/null || true

pgrep -x plank >/dev/null || (plank >/tmp/plank.log 2>&1 &)

mkdir -p "$HOME/Desktop" "$HOME/projects"
ln -sfn "$HOME/shared" "$HOME/Desktop/shared"
cat >"$HOME/Desktop/VS Code.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=VS Code
Exec=code --no-sandbox --disable-gpu /home/kasm-user/projects
Icon=com.visualstudio.code
Terminal=false
EOF
chmod +x "$HOME/Desktop/VS Code.desktop"

sleep infinity
