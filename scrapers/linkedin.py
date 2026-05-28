import logging
import re
import time
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

GUEST_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
GEO_ID    = "102172786"  # Lima, Peru (most finance/strategy roles are here)

# Targeted keywords that perform well on LinkedIn's guest API
_LI_KEYWORDS = [
    "Gerente Finanzas Peru",
    "Director Financiero Peru",
    "FP&A Peru",
    "Planeamiento Financiero Peru",
    "CFO Peru",
    "Controller Peru",
    "Gerente Estrategia Peru",
    "Business Development Peru",
    "Gerente Comercial Peru",
]

# Location strings that confirm a Peru-based job
_PERU_LOC_TOKENS = ("lima", "peru", "perú", "remoto")

# Country/city names that flag a clearly non-Peru location
_FOREIGN_COUNTRY_TOKENS = (
    "colombia", "argentina", "chile", "mexico", "méxico", "españa", "spain",
    "united states", "estados unidos", "brasil", "brazil", "ecuador", "bolivia",
    "paraguay", "uruguay", "venezuela", "costa rica", "panama", "panamá",
    "miami", "bogotá", "bogota", "santiago", "buenos aires", "medellín",
    "medellin", "ciudad de mexico", "cdmx", "madrid", "barcelona", "quito",
    "guayaquil", "caracas", "asunción", "asuncion", "montevideo",
)

_REL_DATE_RE = re.compile(
    r'Hace\s+\d+\s+(?:día|días|semana|semanas|mes|meses)'
    r'|\d+\s+(?:day|days|week|weeks|month|months)\s+ago',
    re.IGNORECASE,
)


def _is_peru_location(location: str) -> bool:
    if not location:
        return True  # geoId already filters; empty = unspecified Peru job
    loc = location.lower()
    if any(tok in loc for tok in _FOREIGN_COUNTRY_TOKENS):
        return False
    return any(tok in loc for tok in _PERU_LOC_TOKENS)


def _extract_date(card) -> str:
    """Return date string from a job card: ISO datetime attr or relative text."""
    time_el = card.find("time")
    if time_el:
        dt = time_el.get("datetime", "").strip()
        if dt:
            return dt
        text = time_el.get_text(strip=True)
        if text:
            return text

    # Fallback: relative date anywhere in the card text
    full_text = card.get_text(" ", strip=True)
    m = _REL_DATE_RE.search(full_text)
    return m.group(0) if m else ""


class LinkedInScraper(BaseScraper):
    """
    Uses LinkedIn's public guest Jobs API (no login required).
    Returns HTML fragments with job cards.
    """

    def scrape(self):
        jobs      = []
        seen_urls: set = set()

        for keyword in _LI_KEYWORDS:
            try:
                found = self._scrape_keyword(keyword, seen_urls)
                logger.info(f"LinkedIn '{keyword}': {len(found)} jobs")
                jobs.extend(found)
            except Exception as e:
                logger.warning(f"LinkedIn failed for '{keyword}': {e}")
            time.sleep(2)  # courteous pause between keyword bursts

        return jobs

    def _scrape_keyword(self, keyword: str, seen_urls: set) -> list:
        jobs = []

        for start in range(0, 75, 25):  # up to 3 pages × 25
            params = {
                "keywords": keyword,
                "location": "Peru",
                "geoId":    GEO_ID,
                "start":    start,
            }
            url = f"{GUEST_API}?{urlencode(params)}"

            headers = self.get_headers()
            headers.update({
                "Referer":           "https://www.linkedin.com/jobs/",
                "X-Requested-With":  "XMLHttpRequest",
            })

            try:
                time.sleep(2)
                resp = self.session.get(url, headers=headers, timeout=20)
                if resp.status_code == 429:
                    logger.warning(f"LinkedIn rate-limited (429) — stopping for '{keyword}'")
                    break
                if resp.status_code != 200:
                    logger.warning(
                        f"LinkedIn HTTP {resp.status_code} for '{keyword}' start={start} "
                        f"url={resp.url}"
                    )
                    break
            except Exception as e:
                logger.warning(f"LinkedIn request error '{keyword}' start={start}: {e}")
                break

            soup  = BeautifulSoup(resp.text, "lxml")
            cards = (
                soup.find_all("div", class_=lambda c: c and "base-search-card" in c)
                or soup.find_all("li")
            )

            if not cards:
                logger.debug(
                    f"LinkedIn '{keyword}' start={start}: no cards "
                    f"(title={soup.title.string if soup.title else 'N/A'!r})"
                )
                break

            page_new = 0
            for card in cards:
                job = self._parse_card(card)
                if job and job["url"] not in seen_urls and _is_peru_location(job["location"]):
                    seen_urls.add(job["url"])
                    jobs.append(job)
                    page_new += 1

            if len(cards) < 25:
                break  # reached last page

        return jobs

    def _parse_card(self, card) -> dict | None:
        try:
            title_el = (
                card.find("h3", class_=lambda c: c and "base-search-card__title" in c)
                or card.find("h3")
            )
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                return None

            company_el = (
                card.find("h4", class_=lambda c: c and "base-search-card__subtitle" in c)
                or card.find("h4")
            )
            company = company_el.get_text(strip=True) if company_el else ""

            location_el = card.find(
                "span", class_=lambda c: c and "job-search-card__location" in c
            )
            location = location_el.get_text(strip=True) if location_el else ""

            date_posted = _extract_date(card)

            link = (
                card.find("a", class_=lambda c: c and "base-card__full-link" in c)
                or card.find("a", href=lambda h: h and "/jobs/view/" in h)
            )
            if not link:
                return None
            url = link.get("href", "").split("?")[0].strip()
            if not url:
                return None

            return {
                "title":       title,
                "company":     company,
                "location":    location,
                "salary":      "",
                "date_posted": date_posted,
                "url":         url,
                "source":      "LinkedIn",
            }
        except Exception as e:
            logger.debug(f"LinkedIn card parse error: {e}")
            return None
