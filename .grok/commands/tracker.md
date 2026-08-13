# /tracker - Local Job Tracker UI

Start the localhost job-search cockpit: scraped inbox, fit scores, and application pipeline. It reads and writes the same files `/scrape`, `/rank`, `/outcome` already use. **It never submits applications to LinkedIn, Naukri, or any ATS.**

## Step 0: Parse Arguments

`$ARGUMENTS` may contain:

- Nothing → start on `http://127.0.0.1:8765/`
- `--port <N>` → use that port
- `--root <path>` → repo root (default: this workspace)

If a tracker is already listening on the chosen port, tell the user the URL and stop. Do not start a second copy.

---

## Step 1: Start the server

From the repo root:

```bash
python3 tools/tracker_ui.py --port 8765
```

The process binds **127.0.0.1 only**. It must not bind `0.0.0.0`. If start fails, show the error and stop.

Tell the user:

> **Tracker UI:** http://127.0.0.1:8765/
>
> Local cockpit over `job_scraper/seen_jobs.json` and `job_search_tracker.csv`.
> Open a posting in the browser and apply yourself. Status buttons only update files in this repo.

Leave the server running. Do not scrape, rank, or draft CVs unless the user asked.

---

## What the UI does

- **Inbox** — jobs with status `new` / `ranked` / `evaluated`
- **Pipeline** — rows from `job_search_tracker.csv` (applied → interview → offer → hired / closed)
- **Skip / restore** — writes `seen_jobs.json` only
- **I applied** — adds a tracker row and sets the inbox entry to `applied`. Does not POST to a job portal
- **Open posting** — the live URL, in a new tab

`/html-report` remains the printable offline dashboard. This UI is the live working list.

---

## What it must not do

- Auto-fill or submit any application form
- Log into LinkedIn / Naukri / company ATS
- Mix another person's jobs into this workspace's files (keep a separate clone for a second candidate)
- Bind a public interface or suggest deploying this UI with CV files on the internet

---

## Design Principles

- **Localhost only.** Personal job lists and drafted CVs stay on this machine.
- **Human apply.** The tracker records what you did; it does not do the applying.
- **Same system of record.** No parallel database. CSV + `seen_jobs.json` remain canonical.
