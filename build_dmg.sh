#!/bin/bash
set -e

APP_NAME="MacWhisper"
VERSION="1.0.0"

echo "🚀 Starting build process for $APP_NAME v$VERSION..."

# 1. Clean up
echo "🧹 Cleaning up..."
rm -rf build dist *.spec qt_runtime_hook.py entitlements.plist

# 2. Detect PyQt6 path
echo "🔍 Detecting Qt configuration..."
PYQT_DIR=$(python3 -c 'import PyQt6; print(PyQt6.__path__[0])')
if [ -d "$PYQT_DIR/Qt6" ]; then
    QT_FOLDER="Qt6"
elif [ -d "$PYQT_DIR/Qt" ]; then
    QT_FOLDER="Qt"
else
    echo "❌ Error: Could not find 'Qt' or 'Qt6' directory in $PYQT_DIR"
    exit 1
fi
QT_PATH="$PYQT_DIR/$QT_FOLDER"
echo "✅ Found Qt directory at: $QT_PATH"

# 3. Create Runtime Hook
echo "🪝 Creating runtime hook..."
cat > qt_runtime_hook.py << EOF
import os
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    bundle_dir = Path(sys._MEIPASS)
    # Qt plugins/translations are bundled specifically
    qt_root = bundle_dir / "$QT_FOLDER"
    
    os.environ['QT_PLUGIN_PATH'] = str(qt_root / "plugins")
    os.environ['QT_TRANSLATIONS_DIR'] = str(qt_root / "translations")
    # NOTE: Set this ONLY if we are sure the structure mimics a Qt install. 
    # For PyInstaller, sometimes it's better to let Qt find its Own path relative to binary?
    # But explicit is usually safer if we bundle 'plugins' folder manually.
    os.environ['QLIBRARYINFO_QT_PREFIX'] = str(qt_root)
EOF

# 4. Create Entitlements
echo "📜 Creating entitlements.plist..."
cat > entitlements.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
    <key>com.apple.security.cs.allow-jit</key>
    <true/>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.cs.allow-dyld-environment-variables</key>
    <true/>
    <key>com.apple.security.device.audio-input</key>
    <true/>
</dict>
</plist>
EOF

# 5. Run PyInstaller
echo "🔨 Building .app bundle..."
# Note: We removed the explicit core lib add (--add-binary $QT_PATH/lib/*) to avoid conflicts
# But we KEEP plugins and translations to ensure they exist for the hook.
pyinstaller --noconfirm --name "$APP_NAME" --windowed --contents-directory "." \
    --add-data "$QT_PATH/translations:./$QT_FOLDER/translations" \
    --add-binary "$QT_PATH/plugins/*:./$QT_FOLDER/plugins" \
    --hidden-import="PyQt6" \
    --hidden-import="PyQt6.QtCore" \
    --hidden-import="PyQt6.QtWidgets" \
    --hidden-import="PyQt6.QtGui" \
    --collect-all="openai_whisper" \
    --collect-all="ui" \
    --runtime-hook="qt_runtime_hook.py" \
    --osx-bundle-identifier "com.lishuai.$APP_NAME" \
    main.py

echo "✅ App bundle created."

# 6. MANUAL RECURSIVE SIGNING (The Fix)
APP_PATH="dist/$APP_NAME.app"

echo "🧹 Removing junk build artifacts from bundle..."
find "$APP_PATH" -name "*.o" -delete
find "$APP_PATH" -name "*.c" -delete
find "$APP_PATH" -name "*.cpp" -delete
find "$APP_PATH" -name "*.h" -delete

echo "🔏 Removing metadata/quarantine..."
xattr -cr "$APP_PATH"

echo "🔏 Signing frameworks and libraries individually..."
# Sign all .so, .dylib, .framework folders inside the bundle
find "$APP_PATH" \( -name "*.so" -o -name "*.dylib" -o -name "*.framework" \) -exec codesign --force --sign - --entitlements entitlements.plist "{}" \;

echo "🔏 Signing main executable..."
codesign --force --sign - --entitlements entitlements.plist "$APP_PATH/Contents/MacOS/$APP_NAME"

echo "🔏 Signing the bundle wrapper..."
codesign --force --sign - --entitlements entitlements.plist "$APP_PATH"

echo "✅ Signing complete."

# 7. Create DMG
DMG_NAME="${APP_NAME}_${VERSION}.dmg"
echo "📦 Packaging into DMG..."

if command -v create-dmg &> /dev/null; then
    create-dmg \
      --volname "$APP_NAME Installer" \
      --window-pos 200 120 \
      --window-size 800 400 \
      --icon-size 100 \
      --icon "$APP_NAME.app" 200 190 \
      --hide-extension "$APP_NAME.app" \
      --app-drop-link 600 185 \
      "dist/$DMG_NAME" \
      "dist/$APP_NAME.app"
else
    echo "⚠️ 'create-dmg' not found. Using native hdiutil..."
    rm -f "dist/$DMG_NAME"
    hdiutil create -volname "$APP_NAME" -srcfolder "dist" -ov -format UDZO "dist/$DMG_NAME"
fi

echo "🎉 Build Complete! File: dist/$DMG_NAME"