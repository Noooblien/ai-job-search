---
framework_version: 1.0.0
---

# Agent Guidelines: AI Job Search (Grok Build)

This workspace is structured to manage job search activities, scraper tools, CVs, cover letters, and interview preparation.

**Runtime:** [Grok Build](https://grok.x.ai/) is the primary agent harness for this fork. Claude Code is not required.

## Thin-Pointer Design (Single Source of Truth)

To prevent duplication and configuration drift, this workspace uses a unified thin-pointer design. Load the canonical specifications and candidate profile from:

1. **Personal Candidate Profile:**
   - The candidate profile, contact details, education, and target preferences are defined in [CLAUDE.md](CLAUDE.md) (filename kept for Grok auto-load compatibility; content is the profile, not the Claude product) and the methodology files under [.grok/skills/job-application-assistant/](.grok/skills/job-application-assistant/) (`01-*.md` etc.).
2. **Canonical Workflow Specifications:**
   - Step-by-step instructions and triggers (setup, scrape, rank, apply, upskill, interview, …) live under [.grok/](.grok/) — specifically `.grok/skills/` and `.grok/commands/`.
   - Do not duplicate these rules. Treat `.grok/` as the single source of truth.
3. **Portal Search Skills:**
   - Job-portal search CLIs live under [.agents/skills/](.agents/skills/) in the portable Agent Skills format (`SKILL.md` per portal). Grok discovers them automatically; the `/scrape` skill in `.grok/skills/job-scraper/` orchestrates them.

## Slash commands (Grok)

| Command | Purpose |
|---------|---------|
| `/setup` | Onboard / update profile |
| `/scrape` | Search portals for matching jobs |
| `/rank` | Batch-score scraped jobs |
| `/apply` | Fit eval + tailored CV + cover letter |
| `/interview` | Interview prep for a tracked application |
| `/outcome` | Record application outcomes |
| `/upskill` | Skill-gap analysis and learning plan |
| `/expand`, `/gmail-sync`, `/notion-sync`, `/html-report`, `/add-portal`, `/add-template`, `/reset` | Supporting workflows |

## Grok tool mapping

Workflow specs name Grok tools: `web_fetch` / `open_page`, `web_search`, `spawn_subagent`, `ask_user_question`, `run_terminal_command`, `read_file`, `write`, `search_replace`, `grep`.

Trailing text after a slash command is the command argument (historically `$ARGUMENTS` in the markdown specs).
