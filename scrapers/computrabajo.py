import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from filters import SEARCH_KEYWORDS

logger = logging.getLogger(__name__)

BASE_URL   = "https://www.computrabajo.com.pe"
SEARCH_URL = f"{BASE_URL}/ofertas-de-trabajo/"

_DATE_RE = re.compile(
    r'Hace\s+\d+\s+(?:día|días|semana|semanas|mes|meses|hora|horas)'
    r'|Publicado\s+hace\s+\S+',
    re.IGNORECASE,
)


class ComputrabajoScraper(BaseScraper):

    def scrape(self):
        jobs = []
        seen_urls: set = set()

        for keyword in SEARCH_KEYWORDS:
            try:
                found = self._scrape_keyword(keyword, seen_urls)
                logger.info(f"Computrabajo '{keyword}': {len(found)} jobs")
                jobs.extend(found)
            except Exception as e:
                logger.warning(f"Computrabajo failed for '{keyword}': {e}")

        return jobs

    def _scrape_keyword(self, keyword: str, seen_urls: set) -> list:
        jobs = []

        for page in range(1, 6):  # up to 5 pages
            params = {"q": keyword, "l": "Lima"}
            if page > 1:
                params["p"] = page

            try:
                resp = self.get(SEARCH_URL, params=params)
                soup = BeautifulSoup(resp.text, "lxml")

                listings = self._find_listings(soup)
                if not listings:
                    break

                for item in listings:
                    job = self._parse_listing(item)
                    if job and job["url"] not in seen_urls:
                        seen_urls.add(job["url"])
                        jobs.append(job)

                # Check for next page link
                has_next = bool(
                    soup.find("a", attrs={"aria-label": lambda v: v and "siguiente" in v.lower()})
                    or soup.find("a", class_=lambda c: c and "next" in (c or "").lower())
                    or soup.find("a", string=lambda s: s and str(page + 1) in s)
                )
                if not has_next and page > 1:
                    break

            except Exception as e:
                logger.warning(f"Computrabajo error (page={page}, keyword='{keyword}'): {e}")
                break

        return jobs

    def _find_listings(self, soup) -> list:
        for selector in [
            lambda s: s.find_all("article", class_=lambda c: c and "box_offer" in (c or "")),
            lambda s: s.find_all("article", attrs={"data-id": True}),
            lambda s: s.find_all("div", attrs={"data-id": True}),
            lambda s: s.find_all("div", class_=lambda c: c and "offer" in (c or "").lower()),
            lambda s: s.find_all("li", class_=lambda c: c and "offer" in (c or "").lower()),
        ]:
            results = selector(soup)
            if results:
                return results
        return []

    def _parse_listing(self, item) -> dict | None:
        try:
            # Title — prefer the anchor text inside h2 to avoid status badges
            title = ""
            title_el = (
                item.find("h2")
                or item.find(class_=lambda c: c and "title" in (c or "").lower())
                or item.find("a", href=lambda h: h and "oferta" in (h or ""))
            )
            if title_el:
                # Use the <a> link text if available to avoid embedded badge text
                link_el = title_el.find("a") if title_el.name != "a" else title_el
                title = (link_el.get_text(strip=True) if link_el else title_el.get_text(strip=True))
                # Strip common UI badge suffixes
                for badge in ("Postulado", "Vista", "Nuevo", "Destacado", "Urgente"):
                    title = title.replace(badge, "").strip()
            if not title:
                return None

            # URL
            url = ""
            link = (
                item.find("a", href=lambda h: h and "oferta" in (h or ""))
                or item.find("a", href=lambda h: h and "empleo" in (h or ""))
                or (title_el.find("a") if title_el else None)
            )
            if link:
                href = link.get("href", "")
                url = href if href.startswith("http") else urljoin(BASE_URL, href)
            if not url:
                return None

            # Company
            company = ""
            company_el = (
                item.find(class_=lambda c: c and any(
                    x in (c or "").lower() for x in ["dnom", "company", "empresa"]
                ))
                or item.find("a", href=lambda h: h and "/empresa/" in (h or ""))
            )
            if company_el:
                company = company_el.get_text(strip=True)

            # Location
            location = "Lima"
            loc_el = (
                item.find("li", class_=lambda c: c and "upost" in (c or "").lower())
                or item.find(class_=lambda c: c and any(
                    x in (c or "").lower() for x in ["upost", "location", "ciudad", "localidad"]
                ))
            )
            if loc_el:
                location = loc_el.get_text(strip=True)

            # Date — try structured elements, then full-text regex fallback
            date_posted = ""
            date_el = (
                item.find("time")
                or item.find("span", class_=lambda c: c and "fs13" in (c or ""))
                or item.find("li", class_=lambda c: c and "fpost" in (c or "").lower())
                or item.find(class_=lambda c: c and any(
                    x in (c or "").lower()
                    for x in ["fpost", "date", "fecha", "publicado"]
                ))
            )
            if date_el:
                date_posted = (
                    date_el.get("datetime", "").strip()
                    or date_el.get_text(strip=True)
                )
            if not date_posted:
                m = _DATE_RE.search(item.get_text(" ", strip=True))
                if m:
                    date_posted = m.group(0)

            # Salary (Computrabajo sometimes shows it)
            salary = ""
            salary_el = item.find(class_=lambda c: c and "salary" in (c or "").lower())
            if salary_el:
                salary = salary_el.get_text(strip=True)

            return {
                "title": title,
                "company": company,
                "location": location,
                "salary": salary,
                "date_posted": date_posted,
                "url": url,
                "source": "Computrabajo",
            }
        except Exception as e:
            logger.debug(f"Computrabajo parse error: {e}")
            return None
