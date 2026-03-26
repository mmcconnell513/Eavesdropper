# Job Board Monitor

Job Board Monitor is a Python automation tool that scans JavaScript-rendered career sites with Playwright, filters openings by target role keywords, tracks newly discovered postings over time, and generates a delta-only report.

It is designed for practical monitoring of modern employer job boards that do not expose reliable static HTML or clean feeds.

---

## What It Does

* Opens live career pages in headless Chromium
* Extracts job title, URL, and location from rendered DOM content
* Supports board-specific selectors and pagination behavior
* Filters roles using a configurable keyword list
* Tracks first-seen job postings in a local state file
* Reports only jobs first detected within the last 24 hours
* Optionally sends the report by email via SMTP

---

## Why This Exists

Many enterprise job boards are JavaScript-heavy, structurally inconsistent, and difficult to monitor with simple requests-based scraping.

This project uses a real browser plus board-specific scraping configuration to make job discovery more resilient across heterogeneous career sites.

---

## Core Features

* **Real browser automation** via Playwright
* **Board-specific scraping configs** for selectors and pagination
* **Keyword filtering** for targeted role discovery
* **First-seen tracking** using persistent local state
* **Delta-only reporting** to reduce noise
* **Optional email delivery** for daily summaries

---

## Supported Scraping Patterns

The monitor currently supports multiple site behaviors:

* No pagination
* Next-page navigation
* Load-more buttons
* Scroll-based content loading
* Frame-aware scraping where needed

---

## Configuration Model

Each monitored board is defined as a configuration object containing fields such as:

* board name
* enabled flag
* URL
* job card selector
* title selector
* link selector
* location selector
* wait-for selector
* scroll attempts
* pagination mode
* pagination selector
* pagination safety caps

This keeps the scraper extensible without rewriting the core scraping logic for each new site. The current script uses this model across multiple companies and pagination types.

---

## How Matching Works

The script currently matches jobs by checking whether the job title contains one of the configured target keywords. Location is extracted for reporting but is not used for filtering in the present version. It also stores a first-seen timestamp per job URL so reports can focus on newly detected jobs rather than every live job on every run.

---

## Tech Stack

* Python
* Playwright
* python-dateutil
* SMTP for optional email notifications

---

## Quick Start

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd job-board-monitor
```

### 2. Create and activate a virtual environment

#### Windows

```bash
py -m venv .venv
.venv\Scripts\activate
```

#### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
playwright install
```

### 4. Configure optional email settings

Create a local `.env` file or set environment variables manually.

Expected variables:

* `JOB_MONITOR_EMAIL_FROM`
* `JOB_MONITOR_EMAIL_TO`
* `JOB_MONITOR_SMTP_HOST`
* `JOB_MONITOR_SMTP_PORT`
* `JOB_MONITOR_SMTP_USER`
* `JOB_MONITOR_SMTP_PASS`

If these are not configured, the script will still run and print the report locally. The current code checks for these environment variables before attempting email delivery.

### 5. Run the monitor

```bash
python src/job_monitor.py
```

---

## Example Output

```text
Job Monitor Report – 2026-03-26 09:00 UTC
Window (first-seen): 2026-03-25 09:00 UTC to 2026-03-26 09:00 UTC

Note: Location filtering is disabled. Matches are based on title keywords only.

=== Dell ===
- Product Marketing Manager (Austin, TX)
  https://jobs.example.com/job/123

=== Apple ===
- Content Strategist
  https://jobs.example.com/job/456
```

---

## Recommended Project Structure

```text
job-board-monitor/
├─ README.md
├─ requirements.txt
├─ .gitignore
├─ .env.example
├─ LICENSE
├─ src/
│  └─ job_monitor.py
└─ data/
   └─ .gitkeep
```

---

## Notes

* This project relies on DOM selectors for third-party career sites, so some board configs will require periodic maintenance if site markup changes.
* Some sites use overlays, cookie banners, or dynamic containers that require site-specific handling.
* “New” jobs are based on when the monitor first detects a posting, not the employer’s posted date.

---

## Roadmap

Potential improvements:

* move board configs into JSON or YAML
* add CLI arguments for board subsets or run windows
* reintroduce optional location filtering
* export results to CSV or SQLite
* add scheduled execution via cron, Task Scheduler, or GitHub Actions
* generate HTML email reports

---

## License

MIT License
