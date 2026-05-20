# Build standalone .exe (no internet on office PC)

Build this **once** on your dev PC (good internet). Copy the **`release\Dalda Outlet Matcher`** folder to USB. On the Dalda PC, double-click **`Dalda Outlet Matcher.exe`** — no Python, no pip.

## Build steps (dev PC only)

1. Open this folder in terminal.
2. Double-click **`build_exe.bat`**  
   Or run:
   ```bash
   python -m pip install pyinstaller
   python -m PyInstaller --noconfirm dalda_matcher.spec
   ```
3. Wait 5–15 minutes (large download first time for PyInstaller + packaging).
4. Output folder:
   ```
   release\Dalda Outlet Matcher\
     Dalda Outlet Matcher.exe    ← double-click this
     _internal\                  ← required, do not delete
     Census Database\            ← census CSV
   ```

## Copy to office PC

Copy the **entire** `Dalda Outlet Matcher` folder (not only the .exe).

| Include | Required |
|---------|----------|
| `Dalda Outlet Matcher.exe` | Yes |
| `_internal\` | Yes |
| `Census Database\` | Yes |

Put the folder anywhere (Desktop, `D:\DaldaMatcher`, USB). Run the `.exe`.

## Size

Roughly **400–800 MB** total (Python + pandas + PyQt6 + sklearn + 32 MB census). Plan USB space accordingly.

## Do not push .exe to GitHub

The built folder is in `.gitignore`. Share via **USB** or zip file. Git repo stays for code sync only.

## If Windows SmartScreen blocks the app

Click **More info** → **Run anyway** (unsigned local build).

## Rebuild after code fixes

1. `git pull` (get latest code)
2. Run `build_exe.bat` again
3. Copy new `release\Dalda Outlet Matcher` folder to office PC
