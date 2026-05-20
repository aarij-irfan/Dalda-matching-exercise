# Dalda Outlet Matcher

Match Dalda outlet lists against the Access Retail census database (GPS + shop name scoring). Produces **one Excel/CSV** with all Dalda columns, match scores, and all census columns.

## Quick start — office PC (no internet, recommended)

Use the **standalone .exe** (no Python, no pip):

1. Copy the folder **`release\Dalda Outlet Matcher`** from USB (built on dev PC — see `BUILD_EXE.md`).
2. Double-click **`Dalda Outlet Matcher.exe`**.
3. Keep **`_internal`** and **`Census Database`** in the same folder as the .exe.

## Quick start — with Python + internet

1. Install **Python 3.10+** from [python.org](https://www.python.org/) — enable **“Add python.exe to PATH”**.
2. Clone this repo:
   ```bash
   git clone https://github.com/aarij-irfan/Dalda-matching-exercise.git
   cd Dalda-matching-exercise
   ```
3. Run **one file**:
   - **Windows:** double-click `START.bat`
   - **Or:** `python setup_and_run.py`

`setup_and_run.py` installs libraries from `requirements.txt` and opens the app.

## Build the .exe (dev PC, once)

Double-click **`build_exe.bat`** — creates `release\Dalda Outlet Matcher\`. Copy that whole folder to USB.

## What’s included

| Item | Description |
|------|-------------|
| `Census Database/` | Access Retail census CSV (~75k shops) — used automatically |
| `dalda_matcher_app.py` | PyQt6 desktop UI |
| `matching_engine.py` | Matching logic |
| `sample_dalda_outlets.xlsx` | Small test file (optional) |

## Using the app

1. **Files** — Census is pre-loaded from `Census Database/`. Browse for Dalda’s outlet file (CSV/Excel). Choose output path.
2. **Column mapping** — Map Shop ID → `dalda_shop_id`, outlet name → `dalda_outlet_name`, GPS. Census defaults: `Serial` → `census_shop_id`, `Name of Outlet` → `census_outlet_name`.
3. **Settings** — Search radius, score threshold, threads.
4. **Run** — One output file; row count = Dalda row count.

## Output columns

- `dalda_*` — all Dalda source columns (plus `dalda_shop_id`, `dalda_outlet_name`)
- `match_*` — status, score, confidence, distance, etc.
- `census_*` — all census columns (plus `census_shop_id`, `census_outlet_name`)

## Manual install (if needed)

```bash
pip install -r requirements.txt
python dalda_matcher_app.py
```

## Requirements

- Windows 10/11 (or any OS with Python 3.10+)
- Internet on first run (pip install)
- ~500 MB disk space (census + Python packages)
