import os
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    bundle_dir = Path(sys._MEIPASS)
    # Qt plugins/translations are bundled specifically
    qt_root = bundle_dir / "Qt6"
    
    os.environ['QT_PLUGIN_PATH'] = str(qt_root / "plugins")
    os.environ['QT_TRANSLATIONS_DIR'] = str(qt_root / "translations")
    # NOTE: Set this ONLY if we are sure the structure mimics a Qt install. 
    # For PyInstaller, sometimes it's better to let Qt find its Own path relative to binary?
    # But explicit is usually safer if we bundle 'plugins' folder manually.
    os.environ['QLIBRARYINFO_QT_PREFIX'] = str(qt_root)
