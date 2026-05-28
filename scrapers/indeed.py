import logging
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from filters import SEARCH_KEYWORDS

logger = logging.getLogger(__name__)

BASE_URL = "https://pe.indeed.com"


class IndeedScraper(BaseScraper):
    """
    Indeed Peru scraper. Indeed has strong bot detection; results may be
    limited depending on their current defenses. Uses realistic headers and
    session cookies to improve success rate.
    """

    def scrape(self):
        # Warm up session with a homepage visit
        try:
            self.session.get(
                BASE_URL,
                headers=self.get_headers(),
                timeout=15,
                allow_redirects=True,
            )
        except Exception:
            pass

        jobs = []
        seen_urls: set = set()

        for keyword in SEARCH_KEYWORDS:
            try:
                found = self._scrape_keyword(keyword, seen_urls)
                logger.info(f"Indeed '{keyword}': {len(found)} jobs")
                jobs.extend(found)
            except Exception as e:
                logger.warning(f"Indeed failed for '{keyword}': {e}")

        return jobs

    def _scrape_keyword(self, keyword: str, seen_urls: set) -> list:
        jobs = []

        for start in range(0, 100, 10):  # up to 10 pages × 10 results
            params = {
                "q": keyword,
                "l": "Lima",
                "sort": "date",
                "start": start,
            }
            headers = self.get_headers()
            headers.update({
                "Referer": f"{BASE_URL}/jobs?q={keyword}&l=Lima",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
                "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            })

            try:
                resp = self.session.get(
                    f"{BASE_URL}/jobs",
                    params=params,
                    headers=headers,
                    timeout=20,
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"Indeed HTTP {resp.status_code} for '{keyword}' start={start} "
                        f"url={resp.url} snippet={resp.text[:300]!r}"
                    )
                    break
                resp.raise_for_status()
            except Exception as e:
                logger.warning(f"Indeed request error '{keyword}' start={start}: {type(e).__name__}: {e}")
                break

            soup = BeautifulSoup(resp.text, "lxml")
            listings = self._find_listings(soup)

            if not listings:
                if "captcha" in resp.url.lower() or "loginRedirect" in resp.url:
                    logger.warning(f"Indeed captcha/login redirect for '{keyword}': {resp.url}")
                    break
                # Log a snippet to help debug structure changes
                logger.warning(
                    f"Indeed '{keyword}' start={start}: no listings found — "
                    f"title={soup.title.string if soup.title else 'N/A'!r} "
                    f"url={resp.url}"
                )
                break

            new_in_page = 0
            for item in listings:
                job = self._parse_listing(item)
                if job and job["url"] not in seen_urls:
                    seen_urls.add(job["url"])
                    jobs.append(job)
                    new_in_page += 1

            if len(listings) < 10:
                break

        return jobs

    def _find_listings(self, soup) -> list:
        for selector in [
            lambda s: s.find_all("div", class_="job_seen_beacon"),
            lambda s: s.find_all("div", attrs={"data-jk": True}),
            lambda s: s.find_all("li", class_=lambda c: c and "result" in (c or "").lower()),
            lambda s: s.find_all("div", class_=lambda c: c and "slider_item" in (c or "").lower()),
        ]:
            results = selector(soup)
            if results:
                return results
        return []

    def _parse_listing(self, item) -> dict | None:
        try:
            # Title
            title = ""
            title_el = item.find(["h2", "h3"], class_=lambda c: c and "jobTitle" in (c or ""))
            if title_el:
                span = title_el.find("span", attrs={"title": True})
                title = span.get("title", "") or title_el.get_text(strip=True)
            if not title:
                return None

            # Company
            company = ""
            comp_el = (
                item.find(class_=lambda c: c and "companyName" in (c or ""))
                or item.find(attrs={"data-testid": "company-name"})
            )
            if comp_el:
                company = comp_el.get_text(strip=True)

            # Location
            location = "Lima"
            loc_el = (
                item.find(class_=lambda c: c and "companyLocation" in (c or ""))
                or item.find(attrs={"data-testid": "text-location"})
            )
            if loc_el:
                location = loc_el.get_text(strip=True)

            # Salary
            salary = ""
            sal_el = item.find(class_=lambda c: c and "salary" in (c or "").lower())
            if sal_el:
                salary = sal_el.get_text(strip=True)

            # Date
            date_posted = ""
            date_el = item.find(class_=lambda c: c and "date" in (c or "").lower())
            if date_el:
                date_posted = date_el.get_text(strip=True)

            # URL — prefer direct job link, fall back to data-jk
            url = ""
            link = item.find("a", href=lambda h: h and "/rc/clk" in (h or ""))
            if not link:
                link = item.find("a", class_=lambda c: c and "jcs-JobTitle" in (c or ""))
            if not link:
                link = item.find("a", href=lambda h: h and h.startswith("/"))
            if link:
                href = link.get("href", "")
                url = href if href.startswith("http") else BASE_URL + href
            if not url:
                jk = item.get("data-jk", "")
                if jk:
                    url = f"{BASE_URL}/rc/clk?jk={jk}"
                else:
                    return None

            return {
                "title": title,
                "company": company,
                "location": location,
                "salary": salary,
                "date_posted": date_posted,
                "url": url,
                "source": "Indeed",
            }
        except Exception as e:
            logger.debug(f"Indeed parse error: {e}")
            return None
