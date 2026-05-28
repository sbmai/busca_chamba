import logging

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Bumeran disabled — strong bot detection, requires browser automation.
#
# Investigation (2026-05-27):
#   - JSON API (/api/candidato/avisos/busqueda/…)  → HTTP 403 on all requests
#   - HTML search pages (/empleos-busqueda-*.html) → HTTP 200 but is a pure
#     JS/React shell (body text = 51 chars, zero static job content)
#   - RSS feed (/rss/empleos-*.xml)                → HTTP 404 (URL doesn't exist)
#
# Re-enable options when ready:
#   1. Selenium + headless Chrome (add selenium, webdriver-manager to requirements.txt)
#   2. Playwright (lighter than Selenium, pip install playwright)
#   3. Bumeran official partner/API access
#
# To re-enable: replace the scrape() body with actual logic and update scraper.py.


class BumeranScraper(BaseScraper):

    def scrape(self) -> list:
        logger.info("Bumeran scraper disabled (bot detection — JS-rendered site). Skipping.")
        return []
