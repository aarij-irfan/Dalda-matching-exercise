# Git sync guide — Dalda matching exercise

Use this between **your dev PC** (where fixes are made) and **the Dalda office PC** (where you run the app).

Repo: **https://github.com/aarij-irfan/Dalda-matching-exercise.git**  
Branch: **`main`**

---

## One-time setup (each computer)

### 1. Install Git
- Download: https://git-scm.com/download/win  
- Use default options; **Git Bash** or **Command Prompt** both work.

### 2. Clone the repo (first time only)

```bash
cd "E:\Office - Coding Projects"
git clone https://github.com/aarij-irfan/Dalda-matching-exercise.git
cd Dalda-matching-exercise
```

If the repo is **private**, Git will ask you to sign in (browser or Personal Access Token).

### 3. Run the app (after clone)

Double-click **`START.bat`**  
or:

```bash
python setup_and_run.py
```

---

## Daily sync — office PC (get latest fixes)

Open terminal in the project folder, then:

```bash
cd "path\to\Dalda-matching-exercise"

git status
git pull origin main
```

Then run the app again (`START.bat` or `python setup_and_run.py`).

**Short version (when you know there are no local edits):**

```bash
git pull origin main
```

---

## Dev PC — after fixes are pushed (your side)

When code is updated and pushed to GitHub:

```bash
cd "E:\Office - Coding Projects\Dalda matching exercise"

git status
git add .
git commit -m "Describe what you fixed"
git push origin main
```

---

## Full workflow (issue → fix → sync)

| Step | Who | Command / action |
|------|-----|------------------|
| 1 | Office PC | Find issue, note error or send screenshot |
| 2 | Dev / Cursor | Fix code locally |
| 3 | Dev PC | `git add .` → `git commit -m "Fix: ..."` → `git push origin main` |
| 4 | Office PC | `git pull origin main` |
| 5 | Office PC | Run `START.bat` again |

---

## Useful commands

### See if you’re up to date

```bash
git fetch origin
git status
```

`Your branch is up to date with 'origin/main'` = nothing to pull.

### Pull latest from GitHub

```bash
git pull origin main
```

### See what changed (after pull)

```bash
git log -3 --oneline
```

### Discard local changes (careful — loses unsaved edits)

Only if you did **not** change code on the office PC and pull fails:

```bash
git fetch origin
git reset --hard origin/main
```

---

## If `git pull` shows a conflict

You edited files on the office PC **and** GitHub has newer code.

**Option A — keep GitHub version (usual for office PC):**

```bash
git fetch origin
git reset --hard origin/main
```

**Option B — keep your local edits:** ask for help; don’t force push from the office PC.

---

## If `git push` is rejected

Someone else pushed first, or you’re behind:

```bash
git pull origin main
git push origin main
```

---

## Private repo — sign in once

When `git clone` or `git pull` asks for credentials:

1. Sign in with your **GitHub account** that has access to the repo, or  
2. Use a **Personal Access Token** as the password (Settings → Developer settings → Tokens on GitHub).

You don’t need to stay logged in to **run** the Python app—only for **git pull/push**.

---

## Copy-paste blocks

### Office PC — update before running matcher

```bash
cd "C:\path\to\Dalda-matching-exercise"
git pull origin main
python setup_and_run.py
```

### Dev PC — send fix to GitHub

```bash
cd "E:\Office - Coding Projects\Dalda matching exercise"
git add .
git commit -m "Fix: short description of the issue"
git push origin main
```

---

## Do not run on office PC (unless you know why)

- `git push --force` — can overwrite remote history  
- `git config` changes — not needed for normal sync  

---

## No Git? Use ZIP instead

1. GitHub → repo → **Code** → **Download ZIP**  
2. Extract and replace the old folder (keep your Dalda outlet file / output paths if needed)  
3. Run **`START.bat`**

ZIP does not auto-sync; repeat when you get a new version.
