"""Read/write the job inbox and application tracker.

System of record (same files `/scrape`, `/rank`, `/outcome` already use):

- `job_scraper/seen_jobs.json` — scraped/ranked inbox
- `job_search_tracker.csv` — applications the user has submitted

This module never talks to job portals.
"""

from __future__ import annotations

import csv
import fcntl
import json
import re
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator, TextIO

TRACKER_FIELDS = [
    "date",
    "company",
    "sector",
    "role",
    "role_type",
    "channel",
    "status",
    "contact_person",
    "fit_rating",
    "notes",
    "cv_file",
    "cover_letter_file",
    "source",
]

INBOX_STATUSES = frozenset(
    {"new", "skipped", "evaluated", "ranked", "expired", "applied"}
)
INBOX_SETTABLE = frozenset({"new", "skipped", "evaluated", "ranked", "expired"})

APPLICATION_STATUSES = frozenset(
    {
        "applied",
        "interview",
        "offer",
        "hired",
        "rejected",
        "no_response",
        "no response",
        "offer_declined",
        "interview_only",
        "withdrawn",
    }
)

STATUS_BUCKETS = {
    "applied": "active",
    "interview": "interview",
    "offer": "offer",
    "hired": "hired",
    "rejected": "closed",
    "no_response": "closed",
    "no response": "closed",
    "offer_declined": "closed",
    "interview_only": "closed",
    "withdrawn": "closed",
}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    if not path.exists():
        path.touch()
        created = True
    handle = open(path, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
        if created and path.exists() and path.stat().st_size == 0:
            path.unlink(missing_ok=True)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def pair_key(company: str, role: str) -> str:
    return f"{_norm(company)}|{_norm(role)}"


def workspace_name(root: Path) -> str:
    claude = root / "CLAUDE.md"
    if not claude.is_file():
        return "This workspace"
    text = claude.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"\*\*Name:\*\*\s*(.+)", text)
    if match:
        return match.group(1).strip()
    return "This workspace"


def bucket_for(status: str) -> str:
    return STATUS_BUCKETS.get((status or "").strip().lower(), "active")


class TrackerStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.seen_path = self.root / "job_scraper" / "seen_jobs.json"
        self.tracker_path = self.root / "job_search_tracker.csv"

    def load_seen(self) -> dict[str, Any]:
        if not self.seen_path.is_file():
            return {"seen": {}}
        try:
            data = json.loads(self.seen_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"seen": {}}
        if not isinstance(data, dict):
            return {"seen": {}}
        seen = data.get("seen", {})
        if not isinstance(seen, dict):
            seen = {}
        return {"seen": seen}

    def save_seen(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        with _locked(self.seen_path):
            _atomic_write(self.seen_path, payload)

    def load_tracker(self) -> list[dict[str, str]]:
        if not self.tracker_path.is_file():
            return []
        with self.tracker_path.open(encoding="utf-8", newline="") as handle:
            return self._read_tracker(handle)

    def _read_tracker(self, handle: TextIO) -> list[dict[str, str]]:
        reader = csv.DictReader(handle)
        rows: list[dict[str, str]] = []
        for raw in reader:
            row = {field: (raw.get(field) or "").strip() for field in TRACKER_FIELDS}
            if not row["company"] and not row["role"]:
                continue
            rows.append(row)
        return rows

    def save_tracker(self, rows: list[dict[str, str]]) -> None:
        buf: list[str] = []
        writer_file = _ListWriter(buf)
        writer = csv.DictWriter(
            writer_file,
            fieldnames=TRACKER_FIELDS,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in TRACKER_FIELDS})
        with _locked(self.tracker_path):
            _atomic_write(self.tracker_path, "".join(buf))

    def snapshot(self) -> dict[str, Any]:
        seen = self.load_seen()["seen"]
        applications = self.load_tracker()
        tracked_pairs = {pair_key(row["company"], row["role"]) for row in applications}

        jobs = []
        for key, raw in seen.items():
            if not isinstance(raw, dict):
                continue
            job = self._inbox_job(key, raw, tracked_pairs)
            jobs.append(job)

        jobs.sort(
            key=lambda item: (
                item.get("first_seen") or "",
                float(item.get("rank_score") if item.get("rank_score") is not None else -1),
                item.get("company") or "",
            ),
            reverse=True,
        )

        stats = self._stats(jobs, applications)
        return {
            "workspace": workspace_name(self.root),
            "jobs": jobs,
            "applications": applications,
            "stats": stats,
        }

    def set_inbox_status(self, key: str, status: str) -> dict[str, Any]:
        status = (status or "").strip().lower()
        if status not in INBOX_SETTABLE:
            raise ValueError(
                f"Inbox status must be one of {sorted(INBOX_SETTABLE)}; "
                "use mark_applied to record a submitted application."
            )
        with _locked(self.seen_path):
            data = self.load_seen()
            entry = data["seen"].get(key)
            if not isinstance(entry, dict):
                raise KeyError(f"Unknown inbox key: {key}")
            current = (entry.get("status") or "new").strip().lower()
            if current == "applied":
                raise ValueError("This posting is already marked applied; update it in Pipeline.")
            entry["status"] = status
            _atomic_write(
                self.seen_path,
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            )
        return self.snapshot()

    def mark_applied(
        self,
        key: str,
        *,
        notes: str = "",
        channel: str = "online",
        sector: str = "",
    ) -> dict[str, Any]:
        with _locked(self.seen_path):
            data = self.load_seen()
            entry = data["seen"].get(key)
            if not isinstance(entry, dict):
                raise KeyError(f"Unknown inbox key: {key}")
            company = str(entry.get("company") or "").strip()
            role = str(entry.get("title") or "").strip()
            url = str(entry.get("url") or key)
            fit_rating = self._fit_rating(entry)
            entry["status"] = "applied"
            _atomic_write(
                self.seen_path,
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            )

        with _locked(self.tracker_path):
            rows = self.load_tracker()
            existing = next(
                (
                    row
                    for row in rows
                    if pair_key(row["company"], row["role"]) == pair_key(company, role)
                ),
                None,
            )
            if existing is None:
                rows.append(
                    {
                        "date": date.today().isoformat(),
                        "company": company,
                        "sector": sector,
                        "role": role,
                        "role_type": "",
                        "channel": channel or "online",
                        "status": "applied",
                        "contact_person": "",
                        "fit_rating": fit_rating,
                        "notes": notes,
                        "cv_file": "",
                        "cover_letter_file": "",
                        "source": url,
                    }
                )
                _atomic_write_csv(self.tracker_path, rows)
            elif notes and notes not in existing.get("notes", ""):
                existing["notes"] = _append_note(existing.get("notes", ""), notes)
                _atomic_write_csv(self.tracker_path, rows)

        return self.snapshot()

    def set_application_status(
        self,
        company: str,
        role: str,
        status: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        status = (status or "").strip().lower()
        if status not in APPLICATION_STATUSES:
            raise ValueError(f"Unknown application status: {status}")
        target = pair_key(company, role)
        with _locked(self.tracker_path):
            rows = self.load_tracker()
            match = next(
                (row for row in rows if pair_key(row["company"], row["role"]) == target),
                None,
            )
            if match is None:
                raise KeyError(f"No tracked application for {company} / {role}")
            match["status"] = status
            if notes:
                match["notes"] = _append_note(match.get("notes", ""), notes)
            _atomic_write_csv(self.tracker_path, rows)
        return self.snapshot()

    def _inbox_job(
        self,
        key: str,
        raw: dict[str, Any],
        tracked_pairs: set[str],
    ) -> dict[str, Any]:
        company = str(raw.get("company") or "").strip()
        title = str(raw.get("title") or "").strip()
        status = str(raw.get("status") or "new").strip().lower()
        if status not in INBOX_STATUSES:
            status = "new"
        rank_score = raw.get("rank_score")
        try:
            rank_score_n = float(rank_score) if rank_score is not None else None
        except (TypeError, ValueError):
            rank_score_n = None
        tracked = pair_key(company, title) in tracked_pairs
        if tracked:
            status = "applied"
        return {
            "key": key,
            "title": title,
            "company": company,
            "url": str(raw.get("url") or key),
            "location": str(raw.get("location") or ""),
            "portal": str(raw.get("portal") or ""),
            "fit": str(raw.get("fit") or ""),
            "status": status,
            "first_seen": str(raw.get("first_seen") or ""),
            "rank_score": rank_score_n,
            "rank_verdict": str(raw.get("rank_verdict") or ""),
            "rank_date": str(raw.get("rank_date") or ""),
            "tracked": tracked,
        }

    def _fit_rating(self, entry: dict[str, Any]) -> str:
        score = entry.get("rank_score")
        try:
            if score is not None:
                return str(int(round(float(score))))
        except (TypeError, ValueError):
            pass
        return str(entry.get("fit") or "")

    def _stats(
        self,
        jobs: list[dict[str, Any]],
        applications: list[dict[str, str]],
    ) -> dict[str, int]:
        inbox = {"new": 0, "ranked": 0, "skipped": 0, "expired": 0, "applied": 0, "evaluated": 0}
        for job in jobs:
            status = job["status"]
            if status in inbox:
                inbox[status] += 1
        pipeline = {"active": 0, "interview": 0, "offer": 0, "hired": 0, "closed": 0}
        for row in applications:
            pipeline[bucket_for(row.get("status", ""))] = (
                pipeline.get(bucket_for(row.get("status", "")), 0) + 1
            )
        return {
            "inbox_total": len(jobs),
            "inbox_open": inbox["new"] + inbox["ranked"] + inbox["evaluated"],
            **{f"inbox_{k}": v for k, v in inbox.items()},
            "pipeline_total": len(applications),
            **{f"pipeline_{k}": v for k, v in pipeline.items()},
        }


class _ListWriter:
    def __init__(self, buf: list[str]) -> None:
        self.buf = buf

    def write(self, chunk: str) -> int:
        self.buf.append(chunk)
        return len(chunk)


def _atomic_write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    buf: list[str] = []
    writer = csv.DictWriter(
        _ListWriter(buf),
        fieldnames=TRACKER_FIELDS,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in TRACKER_FIELDS})
    _atomic_write(path, "".join(buf))


def _append_note(existing: str, note: str) -> str:
    note = note.strip()
    if not note:
        return existing
    stamped = f"{date.today().isoformat()} tracker-ui: {note}"
    if not existing:
        return stamped
    return f"{existing.rstrip()} | {stamped}"
