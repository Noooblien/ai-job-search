"""Local job-search tracker UI.

Binds to 127.0.0.1 only. Reads and writes the repo's existing state files
(`job_scraper/seen_jobs.json`, `job_search_tracker.csv`). Never submits
applications to job portals.
"""
