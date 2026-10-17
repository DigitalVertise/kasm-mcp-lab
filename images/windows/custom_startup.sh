#!/usr/bin/env bash
# Applies the Windows-style theme, initialises the Wine prefix on first boot,
# and drops desktop launchers for common Wine tools.
set -u
export DISPLAY=:1
until xdpyinfo >/dev/null 2>&1; do sleep 1; done
sleep 3   # let xfconfd and the panel finish starting

apply() { xfconf-query -c "$1" -p "$2" -s "$3" --create -t string 2>/dev/null || true; }
[ -d /usr/share/themes/Chicago95 ] && {
  apply xsettings /Net/ThemeName Chicago95
  apply xfwm4 /general/theme Chicago95
}
[ -d /usr/share/icons/Chicago95 ] && apply xsettings /Net/IconThemeName Chicago95
[ -d /usr/share/icons/Chicago95_Cursor_Black ] && apply xsettings /Gtk/CursorThemeName Chicago95_Cursor_Black

# First-boot Wine prefix (quiet, no Mono/Gecko popups).
export WINEPREFIX="${WINEPREFIX:-$HOME/.wine}" WINEARCH="${WINEARCH:-win64}" WINEDEBUG=-all
if [ ! -f "$WINEPREFIX/system.reg" ]; then
  WINEDLLOVERRIDES="mscoree,mshtml=" wineboot --init >/tmp/wineboot.log 2>&1 || true
fi

mkdir -p "$HOME/Desktop"
ln -sfn "$HOME/shared" "$HOME/Desktop/shared"
mk() { # name exec icon
  cat >"$HOME/Desktop/$1.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$1
Exec=$2
Icon=$3
Terminal=false
EOF
  chmod +x "$HOME/Desktop/$1.desktop"
}
mk "Wine Explorer" "wine explorer" "folder"
mk "Notepad" "wine notepad" "accessories-text-editor"
mk "Wine Config" "winecfg" "preferences-system"
mk "Command Prompt" "xfce4-terminal -e 'wine cmd'" "utilities-terminal"

sleep infinity
