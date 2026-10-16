#!/bin/bash
# 生成 /Applications/字幕翻译.app（无权限时装到 ~/Applications）
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/Applications; [ -w "$DEST" ] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
APP="$DEST/字幕翻译.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
T=$(mktemp -d); python3 "$SRC/assets/make_icon.py" "$T/i.png"
mkdir "$T/i.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s "$T/i.png" --out "$T/i.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$T/i.png" --out "$T/i.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$T/i.iconset" -o "$APP/Contents/Resources/AppIcon.icns"; rm -rf "$T"
cat > "$APP/Contents/MacOS/字幕翻译" <<SH
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:\$HOME/miniconda3/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export LANG=zh_CN.UTF-8 PYTHONUNBUFFERED=1
cd "$SRC"
[ -f keys.env ] && { set -a; . ./keys.env; set +a; }
pgrep -x ollama >/dev/null || (nohup ollama serve >/tmp/ollama_serve.log 2>&1 &)
echo "=== \$(date) 启动 ===" >> app.log
exec "$SRC/.venv/bin/python" "$SRC/gui.py" >> app.log 2>&1
SH
chmod +x "$APP/Contents/MacOS/字幕翻译"
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>字幕翻译</string>
<key>CFBundleDisplayName</key><string>字幕翻译</string>
<key>CFBundleExecutable</key><string>字幕翻译</string>
<key>CFBundleIdentifier</key><string>local.subtitle-pipeline</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.0</string>
<key>LSMinimumSystemVersion</key><string>12.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PL
xattr -cr "$APP"; touch "$APP"
echo "已安装: $APP"
