#!/usr/bin/env python3
"""
Job Board Monitor (Playwright version)

- Uses a real browser (Playwright) so JS-rendered job boards work.
- For each configured board:
    * Open the URL in headless Chromium
    * Optionally paginate (load more / next page) per-board config
    * Extract title, link, location from the live DOM
- Then applies:
    * Job-title keyword filter
    * First-seen timestamp logic (24h window by appearance)
- Optionally emails a daily report.

You must:
- Install Playwright + browsers: `pip install playwright` then `playwright install`
- Fill per-board selectors and (optionally) pagination config in JOB_BOARDS.
"""

import json
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Dict, List, Optional
from urllib.parse import urljoin

from dateutil import parser as date_parser
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ===================== USER CONFIG =====================

JOB_KEYWORDS: List[str] = [
    "Product Marketing Manager",
    "E-Commerce",
    "eCommerce",
    "Merchandising",
    "Digital Experience",
    "Digital Commerce",
    "Ecommerce Experience",
    "Content Strategist",
    "Online Retail",
    "GTM",
    "Go-to-Market",
    "Growth Marketing",
    "ABM",
    "Account-based Marketing",
    "Product Owner",
    "Customer Success",
    "Sales Enablement",
    "Channel Marketing",
    "Lifecycle Marketing",
    "Business Planning",
    "Performance Analytics",
    "Marketing Operations",
    "Business Operations",
    "Partner Marketing",
    "Customer Experience",
    "Personalization",
    "Portfolio Operations",
    "Digital Merchandising",
    "E-Commerce Strategist",
    "Client Success",
    "Brand Strategy",
    "Campaign Manager",
    "Marketing Lead",
    "Content Marketing",
    "Portfolio Messaging",
    "E-Business",
    "Vertical Marketing",
    "Vertical Strategist",
    "Commerce",
    "Integrated Marketing",
]

TARGET_LOCATION_NOTE = """
Note: Location filtering is disabled. Matches are based on title keywords only.
"""

STATE_FILE = "seen_jobs.json"

EMAIL_FROM = os.environ.get("JOB_MONITOR_EMAIL_FROM", "")
EMAIL_TO = os.environ.get("JOB_MONITOR_EMAIL_TO", "")
SMTP_HOST = os.environ.get("JOB_MONITOR_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("JOB_MONITOR_SMTP_PORT", "587") or "587")
SMTP_USER = os.environ.get("JOB_MONITOR_SMTP_USER", "")
SMTP_PASS = os.environ.get("JOB_MONITOR_SMTP_PASS", "")

# Each board:
# - name
# - enabled
# - url
# - job_selector: CSS for each job card in the rendered DOM
# - title_selector: CSS (relative) for title
# - link_selector: CSS (relative) for the anchor href
# - location_selector: CSS (relative) for location text; may be empty
# - wait_for_selector: what to wait for before scraping (usually same as job_selector)
# - scroll_attempts: how many times to scroll down to load more jobs
# - pagination_mode: "none" (default), "load_more", or "next_button"
# - pagination_selector: CSS selector for load-more or next button
# - pagination_clicks: optional safety cap for load_more (if 0/None, defaults to 50)
# - pagination_pages: optional safety cap for next_button (if 0/None, defaults to 50)
# - frame_selector: OPTIONAL CSS selector pointing to an iframe that contains the job list
JOB_BOARDS: List[Dict] = [
    {
        "name": "Dell",
        "enabled": True,
        "url": "https://jobs.dell.com/en/search-jobs",
        "job_selector": "a[data-job-id]",
        "title_selector": "a[data-job-id] > h2",
        "link_selector": "a[data-job-id]",
        "location_selector": "span.job-info.job-location",
        "wait_for_selector": "a[data-job-id]",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "div.pagination-paging a.next",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "AMD",
        "enabled": True,
        "url": "https://careers.amd.com/careers-home/jobs",
        "job_selector": "mat-expansion-panel.search-result-item",
        "title_selector": "mat-panel-title.mat-expansion-panel-header-title",
        "link_selector": "a.job-title-link",
        "location_selector": "div.job-card-result-container",
        "wait_for_selector": "mat-expansion-panel.search-result-item",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "button.mat-paginator-navigation-next",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "Apple",
        "enabled": True,
        "url": "https://jobs.apple.com/en-us/search?location=united-states-USA",
        "job_selector": "div.job-title",
        "title_selector": "div.d-flex",
        "link_selector": "a.link-inline",
        "location_selector": "div.column",
        "wait_for_selector": "div.job-title",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "button[data-analytics-pagination='next']",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "Intel",
        "enabled": True,
        "url": "https://intel.wd1.myworkdayjobs.com/External?locations=1e4a4eb3adf1016541777876bf8111cf",
        "job_selector": "li.css-1q2dra3",
        "title_selector": "h3",
        "link_selector": "a.css-19uc56f",
        "location_selector": "div.css-k008qs",
        "wait_for_selector": "li.css-1q2dra3",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "button[data-uxi-element-id='next']",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "Visa (Austin URL)",
        "enabled": True,
        "url": "https://corporate.visa.com/en/jobs/?cities=Austin",
        "job_selector": "li.vs-underline",
        "title_selector": "h2.vs-h4",
        "link_selector": "a.vs-h3",
        "location_selector": "",
        "wait_for_selector": "li.vs-underline",
        "scroll_attempts": 3,
        "pagination_mode": "none",
        "pagination_selector": "",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "Google",
        "enabled": True,
        "url": "https://www.google.com/about/careers/applications/jobs/results?location=United%20States",
        "job_selector": "div.sMn82b",
        "title_selector": "h2.VfPpkd-MlC99b",
        "link_selector": "h2.VfPpkd-MlC99b",
        "location_selector": "",
        "wait_for_selector": "div.sMn82b",
        "scroll_attempts": 6,
        "pagination_mode": "next_button",
        "pagination_selector": "a[aria-label='Go to next page']",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "HP",
        "enabled": True,
        "url": "https://apply.hp.com/careers",
        "job_selector": "div.cardContainer-GcY1a",
        "title_selector": "div.title-1aNJK",
        "link_selector": "div.title-1aNJK",
        "location_selector": "",
        "wait_for_selector": "div.cardContainer-GcY1a",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "button.pagination-module_pagination-next__OHCf9",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "Meta",
        "enabled": True,
        "url": "https://www.metacareers.com/jobsearch",
        "job_selector": "a.x1i10hfl",
        "title_selector": "h3.x16g9bbj",
        "link_selector": "h3.x16g9bbj",
        "location_selector": "",
        "wait_for_selector": "a.x1i10hfl",
        "scroll_attempts": 6,
        "pagination_mode": "next_button",
        "pagination_selector": "div[role='button'][aria-label='Button to select next week']",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "YETI",
        "enabled": True,
        "url": "https://yeticoolers.wd5.myworkdayjobs.com/YETI",
        "job_selector": "li.css-1q2dra3",
        "title_selector": "h3",
        "link_selector": "a.css-19uc56f",
        "location_selector": "div.css-k008qs",
        "wait_for_selector": "li.css-1q2dra3",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "button[data-uxi-element-id='next']",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "Amazon",
        "enabled": True,
        "url": "https://amazon.jobs/en/search",
        "job_selector": "div.job-tile",
        "title_selector": "h3.job-title",
        "link_selector": "a.job-link",
        "location_selector": "p.location-and-id",
        "wait_for_selector": "div.job-tile",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "button.btn.circle.right[aria-label='Next page']",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "Microsoft",
        "enabled": True,
        "url": "https://apply.careers.microsoft.com/careers?start=0&location=united+states&pid=1970393556620581&sort_by=distance&filter_include_remote=1",
        "job_selector": "div.cardlist-8kM5_ div.stack-module_vertical__ZyU6e.stack-module_gap-s__snYAO",
        "title_selector": ".title-1aNJK",
        "link_selector": "",
        "location_selector": ".fieldValue-3kEar",
        "wait_for_selector": "div.cardlist-8kM5_ div.stack-module_vertical__ZyU6e.stack-module_gap-s__snYAO",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "button.pagination-module_pagination-next__OHCf9",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "Cisco",
        "enabled": True,
        "url": "https://careers.cisco.com/global/en/search-results",
        "job_selector": "[data-ph-at-id='jobs-list']",
        "title_selector": "a[data-ph-at-id='job-link']",
        "link_selector": "a[data-ph-at-id='job-link']",
        "location_selector": "",
        "wait_for_selector": "[data-ph-at-id='jobs-list']",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "a[data-ph-at-id='pagination-next-link']",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "TP (Teleperformance)",
        "enabled": True,
        "url": "https://www.tp.com/en-us/locations/united-states/careers/?page=0",
        "job_selector": "div.col-12",
        "title_selector": "a.phs-link",
        "link_selector": "a.phs-link",
        "location_selector": "",
        "wait_for_selector": "div.col-12",
        "scroll_attempts": 3,
        "pagination_mode": "load_more",
        "pagination_selector": "svg.svgSeeMore",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "American Express",
        "enabled": True,
        "url": "https://aexp.eightfold.ai/careers?hl=en",
        "job_selector": "div.card.position-card.pointer",
        "title_selector": "div.title",
        "link_selector": "a.position-title",
        "location_selector": "p.position-location",
        "wait_for_selector": "div.card.position-card.pointer",
        "scroll_attempts": 0,
        "pagination_mode": "load_more",
        "pagination_selector": "button.show-more-positions",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "Johnson & Johnson",
        "enabled": True,
        "url": "https://www.careers.jnj.com/en/jobs/?orderby=0&pagesize=20&page=1&radius=100&country=United%20States%20of%20America",
        "job_selector": "li.PageList-items-item",
        "title_selector": "h3.PagePromo-title",
        "link_selector": "a.PagePromo-link",
        "location_selector": "address.PagePromo-location",
        "wait_for_selector": "li.PageList-items-item",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "li.page-item.next a.page-link[aria-label='Next page']",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "GE Aerospace",
        "enabled": True,
        "url": "https://careers.geaerospace.com/global/en/search-results",
        "job_selector": "[data-ph-at-id='jobs-list-item']",
        "title_selector": "a[data-ph-at-id='job-link']",
        "link_selector": "a[data-ph-at-id='job-link']",
        "location_selector": "div[data-ph-at-id='job-location']",
        "wait_for_selector": "[data-ph-at-id='jobs-list-item']",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "a[data-ph-at-id='pagination-next-link']",
        "pagination_clicks": 0,
        "pagination_pages": 0,
    },
    {
        "name": "Nike",
        "enabled": True,
        "url": "https://careers.nike.com/jobs?location_name=United%20States&location_type=4",
        "job_selector": "li.results-list__item",
        "title_selector": "h3.results-list__item-title",
        "link_selector": "a.results-list__item-title--link",
        "location_selector": "",
        "wait_for_selector": "li.results-list__item",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "a[data-testid='jobs-pagination_link_next']",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "NVIDIA",
        "enabled": True,
        "url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?locationHierarchy1=2fcb99c455831013ea52fb338f2932d8",
        "job_selector": "li.css-1q2dra3",
        "title_selector": "h3",
        "link_selector": "a.css-19uc56f",
        "location_selector": "div.css-k008qs",
        "wait_for_selector": "li.css-1q2dra3",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "button[data-uxi-element-id='next']",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "CoreWeave",
        "enabled": True,
        "url": "https://www.coreweave.com/careers",
        "job_selector": "li.job",
        "title_selector": "h3.job__title",
        "link_selector": "h3.job__title",
        "location_selector": "div.job__location",
        "wait_for_selector": "li.job",
        "scroll_attempts": 3,
        "pagination_mode": "none",
        "pagination_selector": "",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "Lenovo",
        "enabled": True,
        "url": "https://jobs.lenovo.com/en_US/careers/SearchJobs/",
        "job_selector": "article.article.article--result",
        "title_selector": "h3.article_header_text_title",
        "link_selector": "a.button.button--primary",
        "location_selector": "div.article__header__text__subtitle",
        "wait_for_selector": "article.article.article--result",
        "scroll_attempts": 3,
        "pagination_mode": "next_button",
        "pagination_selector": "a.list-controls__pagination__item.paginationNextLink",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
    {
        "name": "Cloudflare",
        "enabled": True,
        "url": "https://www.cloudflare.com/careers/jobs/",
        "job_selector": "div.w-100.flex.flex-row.flex-wrap.bb.b--gray0.justify-center.pv1",
        "title_selector": "a.inline-link-style.f4.fw7.lh-title",
        "link_selector": "a.inline-link-style.f4.fw7.lh-title",
        "location_selector": "div.w-100.w-50-m.w-50-l.flex.items-center",
        "wait_for_selector": "div.w-100.flex.flex-row.flex-wrap.bb.b--gray0.justify-center.pv1",
        "scroll_attempts": 3,
        "pagination_mode": "",
        "pagination_selector": "",
        "pagination_clicks": 10,
        "pagination_pages": 10,
    },
]

# ===================== STATE HELPERS =====================

def load_seen_jobs(path: str) -> Dict[str, str]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_seen_jobs(path: str, seen: Dict[str, str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2)


def parse_date(text: str) -> Optional[datetime]:
    if not text:
        return None
    text = text.strip()
    try:
        dt = date_parser.parse(text, fuzzy=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return None


# ===================== FILTERS =====================

def job_matches_keywords(title: str) -> bool:
    t = title.lower()
    return any(kw.lower() in t for kw in JOB_KEYWORDS)


# ===================== PLAYWRIGHT SCRAPING =====================

def extract_jobs_from_dom(board: Dict, context) -> List[Dict]:
    """Extract jobs from the current DOM for a single page or frame."""
    job_sel = board["job_selector"]
    title_sel = board["title_selector"]
    link_sel = board["link_selector"]
    location_sel = board["location_selector"]

    job_elements = context.query_selector_all(job_sel)
    print(f"  Found {len(job_elements)} job card elements for {board['name']} on this page.")

    jobs: List[Dict] = []

    for job_el in job_elements:
        title_el = job_el.query_selector(title_sel)
        if not title_el:
            continue

        title = (title_el.inner_text() or "").strip()
        if not title:
            continue

        if not job_matches_keywords(title):
            continue

        link = None
        link_el = job_el.query_selector(link_sel) if link_sel else None
        if link_el:
            href = link_el.get_attribute("href")
            if href:
                if href.startswith("http"):
                    link = href
                else:
                    link = urljoin(context.url, href)

        if not link:
            continue

        location = None
        if location_sel:
            loc_el = job_el.query_selector(location_sel)
            if loc_el:
                location_text = (loc_el.inner_text() or "").strip()
                if location_text:
                    location = " ".join(location_text.split())

        jobs.append(
            {
                "company": board["name"],
                "title": title,
                "url": link,
                "location": location,
                "date_posted": None,
            }
        )

    return jobs


def resolve_board_context(page, board: Dict, wait_sel: str):
    """
    Try to find a context (page or one of its frames) that actually
    contains wait_sel. Prefer the main page; if that fails, probe iframes.
    """
    try:
        page.wait_for_selector(wait_sel, timeout=5000)
        return page
    except PlaywrightTimeoutError:
        pass

    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            frame.wait_for_selector(wait_sel, timeout=5000)
            print(f"  Using iframe context {frame.url} for {board['name']}.")
            return frame
        except PlaywrightTimeoutError:
            continue

    print(
        f"  No frame contained selector {wait_sel} for {board['name']}; "
        f"continuing with main page."
    )
    return page


def dismiss_common_overlays(page) -> None:
    """
    Try to dismiss common cookie/consent overlays that block clicks.
    Safe to call on any page; it no-ops if nothing is found.
    """
    selectors = [
        "#onetrust-reject-all-handler",
        "#onetrust-accept-btn-handler",
        "button#onetrust-pc-btn-handler",
        "button[aria-label='Close']",
        "button[aria-label='Close dialog']",
    ]

    for sel in selectors:
        try:
            btn = page.query_selector(sel)
            if btn:
                print(f"  Dismissing overlay via selector: {sel}")
                btn.click(force=True, timeout=3000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def kill_amd_overlays(page) -> None:
    """
    Hard-remove AMD's OneTrust cookie / consent overlay so it stops
    intercepting pointer events. Safe to call repeatedly.
    """
    try:
        page.evaluate(
            """
            () => {
              const ot = document.getElementById('onetrust-consent-sdk');
              if (ot) {
                ot.remove();
              }

              const classes = ['onetrust-pc-dark-filter', 'ot-sdk-row'];
              classes.forEach(cls => {
                document.querySelectorAll('.' + cls).forEach(el => el.remove());
              });
            }
            """
        )
        page.wait_for_timeout(200)
    except Exception:
        pass


def scrape_board_with_playwright(board: Dict, page) -> List[Dict]:
    """
    Given an open Playwright page, load the board URL, paginate if configured,
    scroll if requested, and extract jobs across all visited pages.
    """
    url = board["url"]
    wait_sel = board.get("wait_for_selector", board["job_selector"])
    scroll_attempts = int(board.get("scroll_attempts", 0))

    pagination_mode = board.get("pagination_mode", "none")
    pagination_selector = (board.get("pagination_selector") or "").strip()
    max_clicks_raw = int(board.get("pagination_clicks", 0) or 0)
    max_pages_raw = int(board.get("pagination_pages", 0) or 0)

    max_clicks = max_clicks_raw if max_clicks_raw > 0 else 50
    max_pages = max_pages_raw if max_pages_raw > 0 else 50

    print(f"Visiting {board['name']} at {url}...")
    try:
        page.goto(url, wait_until="load", timeout=10000)
        dismiss_common_overlays(page)

        if "careers.amd.com" in url:
            kill_amd_overlays(page)

    except PlaywrightTimeoutError as e:
        print(f"  Timeout loading {url}: {e}. Skipping this board.")
        return []
    except Exception as e:
        print(f"  Error loading {url}: {e}. Skipping this board.")
        return []

    ctx = resolve_board_context(page, board, wait_sel)

    jobs: List[Dict] = []

    def wait_for_jobs() -> bool:
        try:
            ctx.wait_for_selector(wait_sel, timeout=10000)
            return True
        except PlaywrightTimeoutError:
            print(f"  No elements matching {wait_sel} appeared for {board['name']} on this page.")
            return False

    def do_scroll(context) -> None:
        if scroll_attempts <= 0:
            return
        try:
            for _ in range(scroll_attempts):
                context.evaluate("window.scrollBy(0, 1000)")
                context.wait_for_timeout(800)
        except Exception:
            pass

    if pagination_mode == "next_button" and pagination_selector:
        pages_visited = 0

        while pages_visited < max_pages:
            if not wait_for_jobs():
                break

            do_scroll(ctx)
            page_jobs = extract_jobs_from_dom(board, ctx)
            print(
                f"  Extracted {len(page_jobs)} matches from page {pages_visited + 1} "
                f"of {board['name']}."
            )
            jobs.extend(page_jobs)
            pages_visited += 1

            next_el = ctx.query_selector(pagination_selector)
            if not next_el:
                print(
                    f"  No next-page control found for {board['name']} "
                    f"(page {pages_visited}). Stopping pagination."
                )
                break

            aria_disabled = next_el.get_attribute("aria-disabled")
            disabled_attr = next_el.get_attribute("disabled")
            if aria_disabled == "true" or disabled_attr is not None:
                print(
                    f"  Next-page control disabled for {board['name']} "
                    f"(page {pages_visited}). Stopping pagination."
                )
                break

            try:
                dismiss_common_overlays(page)

                if "careers.amd.com" in page.url:
                    kill_amd_overlays(page)

                href = next_el.get_attribute("href")
                if href:
                    next_url = urljoin(page.url, href)
                    print(f"  Navigating to next page for {board['name']}: {next_url}")
                    page.goto(next_url, wait_until="load", timeout=15000)

                    dismiss_common_overlays(page)

                    if "careers.amd.com" in next_url:
                        kill_amd_overlays(page)

                    ctx = resolve_board_context(page, board, wait_sel)
                else:
                    next_el.click(timeout=15000)
                    ctx.wait_for_timeout(1000)

                    dismiss_common_overlays(page)

                    if "careers.amd.com" in page.url:
                        kill_amd_overlays(page)

                    ctx = resolve_board_context(page, board, wait_sel)

            except PlaywrightTimeoutError as e:
                msg = str(e).lower()
                if "intercepts pointer events" in msg and "amd" in board["name"].lower():
                    print(
                        f"  Next-page control appears obstructed for {board['name']} "
                        f"(likely overlay). Stopping AMD pagination."
                    )
                else:
                    print(
                        f"  Timeout navigating to next page for {board['name']}: {e}. "
                        f"Stopping pagination."
                    )
                break
            except Exception as e:
                msg = str(e).lower()
                if "intercepts pointer events" in msg and "amd" in board["name"].lower():
                    print(
                        f"  Next-page control appears obstructed for {board['name']} "
                        f"(likely overlay). Stopping AMD pagination."
                    )
                else:
                    print(f"  Error clicking next for {board['name']}: {e}. Stopping pagination.")
                break

        print(
            f"  Filtered down to {len(jobs)} keyword matches for "
            f"{board['name']} across all pages."
        )
        return jobs

    if pagination_mode == "load_more" and pagination_selector:
        if not wait_for_jobs():
            return []

        seen_urls_local = set()

        do_scroll(ctx)
        initial_jobs = extract_jobs_from_dom(board, ctx)
        for job in initial_jobs:
            job_url = job.get("url")
            if job_url and job_url not in seen_urls_local:
                seen_urls_local.add(job_url)
                jobs.append(job)

        for i in range(max_clicks):
            btn_locator = ctx.locator(pagination_selector)

            if btn_locator.count() == 0:
                print(
                    f"  No load-more button found for {board['name']} on click {i + 1}. "
                    f"Stopping pagination."
                )
                break

            try:
                try:
                    btn_locator.first.scroll_into_view_if_needed()
                    ctx.wait_for_timeout(300)
                except Exception:
                    pass

                btn_locator.first.click(timeout=10000, force=True)
                ctx.wait_for_timeout(2000)

                do_scroll(ctx)
                new_jobs = extract_jobs_from_dom(board, ctx)
                added_this_click = 0

                for job in new_jobs:
                    job_url = job.get("url")
                    if job_url and job_url not in seen_urls_local:
                        seen_urls_local.add(job_url)
                        jobs.append(job)
                        added_this_click += 1

                print(
                    f"  After load-more click {i + 1} for {board['name']}, "
                    f"added {added_this_click} new unique jobs (total {len(seen_urls_local)})."
                )

            except Exception as e:
                msg = str(e).lower()
                if "intercepts pointer events" in msg or "outside of the viewport" in msg:
                    print(
                        f"  Load-more appears obstructed for {board['name']} "
                        f"(likely overlay / moving button). Stopping pagination."
                    )
                    break

                print(
                    f"  Error clicking load-more for {board['name']} on click {i + 1}: {e}. "
                    f"Stopping pagination."
                )
                break

        print(f"  Extracted {len(jobs)} matches for {board['name']} after load-more pagination.")
        print(
            f"  Filtered down to {len(jobs)} keyword matches for "
            f"{board['name']} across all pages."
        )
        return jobs

    if not wait_for_jobs():
        return []

    do_scroll(ctx)
    page_jobs = extract_jobs_from_dom(board, ctx)
    print(f"  Extracted {len(page_jobs)} matches for {board['name']} on current page.")
    jobs.extend(page_jobs)

    print(
        f"  Filtered down to {len(jobs)} keyword matches for "
        f"{board['name']} across all pages."
    )
    return jobs


# ===================== REPORT & EMAIL =====================

def format_report(jobs: List[Dict], since: datetime, until: datetime) -> str:
    if not jobs:
        return (
            f"Job Monitor Report – no new matching jobs.\n"
            f"Window (first-seen): {since.isoformat()} to {until.isoformat()}\n\n"
            f"{TARGET_LOCATION_NOTE.strip()}"
        )

    jobs_sorted = sorted(jobs, key=lambda j: (j.get("company", ""), j.get("title", "")))
    lines: List[str] = []

    lines.append(f"Job Monitor Report – {until.strftime('%Y-%m-%d %H:%M %Z')}")
    lines.append(
        f"Window (first-seen): {since.strftime('%Y-%m-%d %H:%M %Z')} "
        f"to {until.strftime('%Y-%m-%d %H:%M %Z')}"
    )
    lines.append("")
    lines.append(TARGET_LOCATION_NOTE.strip())
    lines.append("")

    current_company: Optional[str] = None
    for job in jobs_sorted:
        company = job.get("company", "Unknown Company")
        if company != current_company:
            current_company = company
            lines.append(f"=== {company} ===")

        title = job.get("title", "Untitled Role")
        location = job.get("location")
        loc_str = f" ({location})" if location else ""
        date_str = f" [posted {job['date_posted']}]" if job.get("date_posted") else ""

        lines.append(f"- {title}{loc_str}{date_str}")
        lines.append(f"  {job.get('url', '')}")
        lines.append("")

    return "\n".join(lines)


def send_email_report(subject: str, body: str) -> None:
    if not (EMAIL_FROM and EMAIL_TO and SMTP_HOST and SMTP_USER and SMTP_PASS):
        print("Email settings not fully configured; skipping email send.")
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print(f"Email report sent to {EMAIL_TO}.")
    except Exception as e:
        print(f"Error sending email: {e}")


# ===================== MAIN =====================

def main() -> None:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)

    seen_jobs = load_seen_jobs(STATE_FILE)
    print(f"Loaded {len(seen_jobs)} previously seen jobs.")

    all_jobs: List[Dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for board in JOB_BOARDS:
            if not board.get("enabled", False):
                print(f"Skipping {board['name']} (disabled).")
                continue

            page = browser.new_page()
            try:
                board_jobs = scrape_board_with_playwright(board, page)
                all_jobs.extend(board_jobs)
            finally:
                page.close()

        browser.close()

    new_state: Dict[str, str] = dict(seen_jobs)
    jobs_to_report: List[Dict] = []

    for job in all_jobs:
        job_url = job.get("url")
        if not job_url:
            continue

        first_seen_str = new_state.get(job_url)
        if not first_seen_str:
            first_seen = now
            new_state[job_url] = first_seen.isoformat()
        else:
            try:
                first_seen = date_parser.parse(first_seen_str)
                if first_seen.tzinfo is None:
                    first_seen = first_seen.replace(tzinfo=timezone.utc)
                else:
                    first_seen = first_seen.astimezone(timezone.utc)
            except Exception:
                first_seen = now
                new_state[job_url] = first_seen.isoformat()

        if first_seen >= since:
            jobs_to_report.append(job)

    print(f"Found {len(jobs_to_report)} jobs first seen in the last 24 hours.")

    report = format_report(jobs_to_report, since, now)
    print("\n" + "=" * 60 + "\n")
    print(report)
    print("\n" + "=" * 60 + "\n")

    subject = f"Job Monitor – {len(jobs_to_report)} new jobs (by appearance)"
    send_email_report(subject, report)

    save_seen_jobs(STATE_FILE, new_state)
    print(f"Saved {len(new_state)} job entries to {STATE_FILE}.")


if __name__ == "__main__":
    main()
