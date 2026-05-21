# PyInstaller spec — Dalda Outlet Matcher
# Run:  python -m PyInstaller --noconfirm dalda_matcher.spec
# Or:   build_exe.bat

import sys
from pathlib import Path

block_cipher = None
root = Path(SPECPATH)

datas = [
    (str(root / "Census Database"), "Census Database"),
    (str(root / "Boudaries"), "Boudaries"),
]

hiddenimports = [
    "shapely",
    "shapely.geometry",
    "matplotlib",
    "boundary_check",
    "sklearn.neighbors._ball_tree",
    "sklearn.utils._cython_blas",
    "sklearn.utils._typedefs",
    "sklearn.neighbors._partition_nodes",
    "pandas._libs.tslibs.timedeltas",
    "openpyxl",
    "rapidfuzz",
]

a = Analysis(
    ["dalda_matcher_app.py"],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt5",
        "PySide2",
        "PySide6",
        "torch",
        "tensorflow",
        "keras",
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        "pygame",
        "tkinter",
        "cv2",
        "transformers",
        "sklearn.externals",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Dalda Outlet Matcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Dalda Outlet Matcher",
)
