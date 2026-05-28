"""
Direct company career-page scraper for top Peru companies.

Strategy per company URL (tried in order):
  1. Follow redirects — detect known ATS (Workday, Greenhouse, Lever, SmartRecruiters)
  2. Scan HTML body for embedded ATS URLs / iframes
  3. Parse JSON-LD <script type="application/ld+json"> for JobPosting objects
  4. Generic CSS-selector HTML parse for job cards
  5. Log "requires_selenium" if page is clearly JS-rendered with no static content
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "empresa_urls.json"
TIPO_FUENTE  = "Empresa Directa"

# ATS domain → handler method name
_ATS_DOMAINS = {
    "myworkdayjobs.com":              "_scrape_workday",
    "greenhouse.io":                  "_scrape_greenhouse",
    "lever.co":                       "_scrape_lever",
    "smartrecruiters.com":            "_scrape_smartrecruiters",
    "taleo.net":                      "_scrape_taleo",
    "successfactors.com":             "_scrape_successfactors",
    "oraclecloud.com":                "_scrape_oracle_hcm",
    "hiringroom.com":                 "_scrape_hiringroom",
    "rankmi.com":                     "_scrape_rankmi",
    "csod.com":                       "_scrape_csod",
    "carrerascredicorpcapital.com":   "_scrape_credicorp_capital",
}

# Terms sent to Workday search
_WD_SEARCH_TERMS = ["finanzas gerente director", "controller", "estrategia", ""]


class EmpresasPeruScraper(BaseScraper):

    def __init__(self):
        super().__init__(delay_range=(2, 4))
        self.empresas = self._load_config()

    def _load_config(self) -> list:
        if not CONFIG_PATH.exists():
            logger.error(f"Config missing: {CONFIG_PATH}")
            return []
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        active = [e for e in data.get("empresas", []) if e.get("activo", True)]
        logger.info(f"Loaded {len(active)} active companies from empresa_urls.json")
        return active

    # ── Public entry point ────────────────────────────────────────────────────

    def scrape(self) -> list:
        jobs: list = []
        seen_urls: set = set()

        for empresa in self.empresas:
            nombre = empresa.get("nombre", "?")
            url    = empresa.get("url", "")
            if not url:
                continue
            try:
                found = self._scrape_empresa(empresa, seen_urls)
                logger.info(f"Empresa Directa '{nombre}': {len(found)} jobs")
                jobs.extend(found)
            except Exception as exc:
                logger.warning(f"Failed '{nombre}' ({url}): {exc}")

        return jobs

    # ── Per-company dispatcher ────────────────────────────────────────────────

    def _scrape_empresa(self, empresa: dict, seen_urls: set) -> list:
        nombre = empresa["nombre"]
        url    = empresa["url"]

        try:
            resp = self.get(url, allow_redirects=True)
        except Exception as exc:
            logger.info(f"  {nombre}: request failed ({exc})")
            return []

        final_url = resp.url

        # 1 — ATS detected in final redirect URL
        for domain, method in _ATS_DOMAINS.items():
            if domain in final_url:
                return getattr(self, method)(final_url, nombre, seen_urls)

        soup = BeautifulSoup(resp.text, "lxml")

        # 2 — ATS URL embedded somewhere in the HTML (href / src / script text)
        ats_result = self._detect_embedded_ats(soup, resp.text, nombre, seen_urls)
        if ats_result is not None:
            return ats_result

        # 3 — JSON-LD structured data
        ld_jobs = self._parse_json_ld(soup, final_url, nombre, seen_urls)
        if ld_jobs:
            return ld_jobs

        # 4 — Generic HTML job-card parsing
        html_jobs = self._parse_html_generic(soup, final_url, nombre, seen_urls)
        if html_jobs:
            return html_jobs

        # 5 — Diagnose why nothing was found
        if self._is_js_heavy(soup, resp.text):
            logger.info(f"  {nombre}: requires_selenium — JS-rendered page, no static job content")
        else:
            logger.info(f"  {nombre}: no job listings found in static HTML")
        return []

    # ── ATS: Workday ──────────────────────────────────────────────────────────

    def _scrape_workday(self, url: str, nombre: str, seen_urls: set) -> list:
        """
        Workday exposes a public JSON API at:
          POST /wday/cxs/{tenant}/{posting}/jobs
        Handles both portal URLs (/BCPCareers) and raw CXS API paths.
        """
        parsed = urlparse(url)
        host   = parsed.hostname or ""
        tenant = host.split(".")[0]  # e.g. "bcp"
        path   = parsed.path.strip("/")

        if path.startswith("wday/cxs/"):
            # URL is already the API path: wday/cxs/{tenant}/{posting}/jobs
            parts   = path.split("/")
            posting = parts[3] if len(parts) > 3 else tenant
        else:
            path_seg = [p for p in path.split("/") if p]
            # Skip 2-letter language-code prefix (e.g. "es" in /es/Search)
            if path_seg and len(path_seg[0]) == 2 and path_seg[0].isalpha():
                posting = path_seg[1] if len(path_seg) > 1 else tenant
            else:
                posting = path_seg[0] if path_seg else tenant

        api_url = f"https://{host}/wday/cxs/{tenant}/{posting}/jobs"
        logger.debug(f"Workday API URL for {nombre}: {api_url}")
        jobs: list = []

        for term in _WD_SEARCH_TERMS:
            try:
                headers = self.get_headers()
                headers.update({"Content-Type": "application/json", "Accept": "application/json"})
                resp = self.session.post(
                    api_url,
                    json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": term},
                    headers=headers, timeout=20,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.debug(f"Workday API error ({nombre}, term='{term}'): {exc}")
                break

            for p in data.get("jobPostings", []):
                job = self._build_workday_job(p, host, posting, nombre)
                if job and job["url"] not in seen_urls:
                    seen_urls.add(job["url"])
                    jobs.append(job)

            if not data.get("jobPostings"):
                break

        return jobs

    def _build_workday_job(self, p: dict, host: str, posting: str, nombre: str) -> dict | None:
        title    = p.get("title", "")
        ext_path = p.get("externalPath", "")
        if not title or not ext_path:
            return None
        return {
            "title":       title,
            "company":     nombre,
            "location":    p.get("locationsText", "Lima, Perú"),
            "salary":      "",
            "date_posted": p.get("postedOn", ""),
            "url":         f"https://{host}/{posting}{ext_path}",
            "source":      nombre,
            "tipo_fuente": TIPO_FUENTE,
        }

    # ── ATS: Greenhouse ───────────────────────────────────────────────────────

    def _scrape_greenhouse(self, url: str, nombre: str, seen_urls: set) -> list:
        """Greenhouse has a fully public board API."""
        path_parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
        slug = path_parts[-1] if path_parts else ""
        if not slug:
            return []

        api = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        try:
            data = self.get(api).json()
        except Exception as exc:
            logger.debug(f"Greenhouse API error ({nombre}): {exc}")
            return []

        jobs = []
        for item in data.get("jobs", []):
            title   = item.get("title", "")
            job_url = item.get("absolute_url") or item.get("url", "")
            if not title or not job_url or job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            jobs.append({
                "title":       title,
                "company":     nombre,
                "location":    item.get("location", {}).get("name", "Lima, Perú"),
                "salary":      "",
                "date_posted": (item.get("updated_at", "") or "")[:10],
                "url":         job_url,
                "source":      nombre,
                "tipo_fuente": TIPO_FUENTE,
            })
        return jobs

    # ── ATS: Lever ────────────────────────────────────────────────────────────

    def _scrape_lever(self, url: str, nombre: str, seen_urls: set) -> list:
        """Lever has a public postings API."""
        path_parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
        slug = path_parts[-1] if path_parts else ""
        if not slug:
            return []

        api = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        try:
            data = self.get(api).json()
        except Exception as exc:
            logger.debug(f"Lever API error ({nombre}): {exc}")
            return []

        jobs = []
        for item in data:
            title   = item.get("text", "")
            job_url = item.get("hostedUrl") or item.get("applyUrl", "")
            if not title or not job_url or job_url in seen_urls:
                continue
            ts = item.get("createdAt", 0)
            date_posted = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else ""
            seen_urls.add(job_url)
            jobs.append({
                "title":       title,
                "company":     nombre,
                "location":    item.get("categories", {}).get("location", "Lima, Perú"),
                "salary":      "",
                "date_posted": date_posted,
                "url":         job_url,
                "source":      nombre,
                "tipo_fuente": TIPO_FUENTE,
            })
        return jobs

    # ── ATS: SmartRecruiters ──────────────────────────────────────────────────

    def _scrape_smartrecruiters(self, url: str, nombre: str, seen_urls: set) -> list:
        """SmartRecruiters public postings API filtered to Peru."""
        path_parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
        # Company ID is always the first path segment
        # (e.g. /BoschGroup/peru → "BoschGroup", not "peru")
        company_id = path_parts[0] if path_parts else ""
        if not company_id:
            return []

        api = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings?limit=100&country=PE"
        try:
            data = self.get(api).json()
        except Exception as exc:
            logger.debug(f"SmartRecruiters API error ({nombre}): {exc}")
            return []

        jobs = []
        for item in data.get("content", []):
            title = item.get("name", "")
            ref   = item.get("refNumber", "")
            if not title or not ref:
                continue
            job_url = f"https://jobs.smartrecruiters.com/{company_id}/{ref}"
            if job_url in seen_urls:
                continue
            loc = item.get("location", {})
            location = f"{loc.get('city', 'Lima')}, Perú"
            seen_urls.add(job_url)
            jobs.append({
                "title":       title,
                "company":     nombre,
                "location":    location,
                "salary":      "",
                "date_posted": (item.get("releasedDate", "") or "")[:10],
                "url":         job_url,
                "source":      nombre,
                "tipo_fuente": TIPO_FUENTE,
            })
        return jobs

    # ── ATS: Oracle HCM Cloud ─────────────────────────────────────────────────

    def _scrape_oracle_hcm(self, url: str, nombre: str, seen_urls: set) -> list:
        """
        Oracle HCM Cloud Candidate Experience public REST API.
        URL pattern: /hcmUI/CandidateExperience/{lang}/sites/{SITE}/jobs
        REST API:    /hcmRestApi/resources/latest/recruitingCEJobRequisitions
                       ?finder=findReqs&limit=25&offset=N
        Fields: Title, PrimaryLocation, PostingStartDate, JobApplicationUrl
        """
        parsed = urlparse(url)
        host   = parsed.hostname or ""
        scheme = parsed.scheme or "https"
        api_base = f"{scheme}://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"

        jobs: list = []
        limit  = 25
        offset = 0

        while True:
            api_url = f"{api_base}?finder=findReqs&limit={limit}&offset={offset}"
            try:
                headers = self.get_headers()
                headers.update({"Accept": "application/json"})
                resp = self.session.get(api_url, headers=headers, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.debug(f"Oracle HCM API error ({nombre}, offset={offset}): {exc}")
                break

            for item in data.get("items", []):
                job = self._parse_oracle_item(item, nombre, seen_urls)
                if job:
                    jobs.append(job)

            if not data.get("hasMore", False):
                break
            offset += limit

        if not jobs:
            logger.debug(f"Oracle HCM ({nombre}): API returned 0 postings")
        return jobs

    def _parse_oracle_item(self, item: dict, nombre: str, seen_urls: set) -> dict | None:
        title   = item.get("Title", "")
        job_url = item.get("JobApplicationUrl", "")
        if not title or not job_url or job_url in seen_urls:
            return None
        seen_urls.add(job_url)
        return {
            "title":       title,
            "company":     nombre,
            "location":    item.get("PrimaryLocation", "Lima, Perú"),
            "salary":      "",
            "date_posted": (item.get("PostingStartDate", "") or "")[:10],
            "url":         job_url,
            "source":      nombre,
            "tipo_fuente": TIPO_FUENTE,
        }

    # ── ATS: Hiringroom ───────────────────────────────────────────────────────

    def _scrape_hiringroom(self, url: str, nombre: str, seen_urls: set) -> list:
        """Hiringroom ATS — try public JSON API, fall back to HTML."""
        parsed = urlparse(url)
        host   = parsed.hostname or ""

        api_url = f"https://{host}/api/v1/jobs"
        try:
            resp = self.session.get(api_url, headers=self.get_headers(), timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                jobs = self._parse_hiringroom_data(data, host, nombre, seen_urls)
                if jobs:
                    return jobs
        except Exception as exc:
            logger.debug(f"Hiringroom API failed ({nombre}): {exc}")

        # HTML fallback
        try:
            resp = self.get(url)
            soup = BeautifulSoup(resp.text, "lxml")
            html_jobs = self._parse_html_generic(soup, url, nombre, seen_urls)
            if not html_jobs and self._is_js_heavy(soup, resp.text):
                logger.info(f"  {nombre}: requires_selenium (Hiringroom JS-rendered)")
            return html_jobs
        except Exception as exc:
            logger.debug(f"Hiringroom HTML failed ({nombre}): {exc}")
        return []

    def _parse_hiringroom_data(self, data, host: str, nombre: str, seen_urls: set) -> list:
        items = data if isinstance(data, list) else data.get("jobs") or data.get("data") or []
        jobs  = []
        for item in items:
            title = item.get("title") or item.get("name", "")
            if not title:
                continue
            job_url = item.get("url") or item.get("apply_url") or item.get("link", "")
            if not job_url:
                job_id  = item.get("id", "")
                job_url = f"https://{host}/jobs/{job_id}" if job_id else ""
            if not job_url or job_url in seen_urls:
                continue
            seen_urls.add(job_url)
            jobs.append({
                "title":       title,
                "company":     nombre,
                "location":    item.get("location", "Lima, Perú"),
                "salary":      "",
                "date_posted": (item.get("published_at") or item.get("created_at") or "")[:10],
                "url":         job_url,
                "source":      nombre,
                "tipo_fuente": TIPO_FUENTE,
            })
        return jobs

    # ── ATS: Rankmi (JS-only) ─────────────────────────────────────────────────

    def _scrape_rankmi(self, url: str, nombre: str, seen_urls: set) -> list:
        """Rankmi ATS is fully JS-rendered — requires browser automation."""
        logger.info(f"  {nombre}: requires_selenium (Rankmi ATS)")
        return []

    # ── ATS: Cornerstone OnDemand / CSOD (JS-only) ───────────────────────────

    def _scrape_csod(self, url: str, nombre: str, seen_urls: set) -> list:
        """Cornerstone OnDemand ATS is fully JS-rendered — requires browser automation."""
        logger.info(f"  {nombre}: requires_selenium (Cornerstone OnDemand / CSOD)")
        return []

    # ── Custom: Credicorp Capital ─────────────────────────────────────────────

    def _scrape_credicorp_capital(self, url: str, nombre: str, seen_urls: set) -> list:
        """
        Custom HTML scraper for carrerascredicorpcapital.com/profesionales.
        Tries generic job-card patterns, then falls back to scanning all anchors
        for links that point inside the same domain.
        """
        try:
            resp = self.get(url)
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception as exc:
            logger.debug(f"Credicorp Capital request failed ({nombre}): {exc}")
            return []

        jobs = self._parse_html_generic(soup, url, nombre, seen_urls)
        if jobs:
            return jobs

        parsed_base = urlparse(url)
        base_domain = parsed_base.netloc

        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            text = a.get_text(strip=True)
            if not text or len(text) < 5 or len(text) > 150:
                continue
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            job_url = href if href.startswith("http") else urljoin(url, href)
            parsed_j = urlparse(job_url)
            if parsed_j.netloc and parsed_j.netloc != base_domain:
                continue
            if job_url in seen_urls or job_url == url:
                continue
            seen_urls.add(job_url)
            jobs.append({
                "title":       text,
                "company":     nombre,
                "location":    "Lima, Perú",
                "salary":      "",
                "date_posted": "",
                "url":         job_url,
                "source":      nombre,
                "tipo_fuente": TIPO_FUENTE,
            })

        if not jobs and self._is_js_heavy(soup, resp.text):
            logger.info(f"  {nombre}: requires_selenium (Credicorp Capital JS-rendered)")
        return jobs

    # ── ATS: SAP SuccessFactors (best-effort) ─────────────────────────────────

    def _scrape_successfactors(self, url: str, nombre: str, seen_urls: set) -> list:
        """SuccessFactors careers pages are JS-heavy; flag and skip."""
        logger.info(f"  {nombre}: requires_selenium (SAP SuccessFactors)")
        return []

    # ── ATS: Oracle Taleo (best-effort) ───────────────────────────────────────

    def _scrape_taleo(self, url: str, nombre: str, seen_urls: set) -> list:
        """Taleo portals are typically JS-heavy; flag and skip."""
        logger.info(f"  {nombre}: requires_selenium (Oracle Taleo)")
        return []

    # ── HTML helpers ──────────────────────────────────────────────────────────

    def _detect_embedded_ats(self, soup, html: str, nombre: str, seen_urls: set) -> list | None:
        """
        Scan all links (a[href], iframe[src], script text) for ATS domain URLs.
        Returns a list if an ATS is found and scraped, None if no ATS detected.
        """
        # Build a set of all URLs mentioned anywhere in the page
        candidates: list[str] = []
        for tag in soup.find_all(["a", "iframe", "frame"], href=True):
            candidates.append(tag["href"])
        for tag in soup.find_all(["a", "iframe", "frame"], src=True):
            candidates.append(tag["src"])
        # Pull URLs from raw HTML (catches JS-injected strings)
        candidates += re.findall(r'https?://[^\s"\'<>]{10,}', html)

        for candidate in candidates:
            for domain, method in _ATS_DOMAINS.items():
                if domain in candidate:
                    logger.debug(f"  {nombre}: detected {domain} → {candidate[:80]}")
                    try:
                        result = getattr(self, method)(candidate, nombre, seen_urls)
                        if result is not None:
                            return result
                    except Exception as exc:
                        logger.debug(f"  {nombre}: ATS handler failed ({exc})")
        return None

    def _parse_json_ld(self, soup, base_url: str, nombre: str, seen_urls: set) -> list:
        """Extract JobPosting entries from JSON-LD <script> blocks."""
        jobs = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data  = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") != "JobPosting":
                        continue
                    title   = item.get("title", "")
                    job_url = item.get("url", "") or base_url
                    if not title or not job_url or job_url in seen_urls:
                        continue

                    org  = item.get("hiringOrganization", {})
                    comp = (org.get("name", nombre) if isinstance(org, dict) else nombre)

                    loc_data = item.get("jobLocation", {})
                    addr     = (loc_data.get("address", {}) if isinstance(loc_data, dict) else {})
                    location = (addr.get("addressLocality", "Lima") if isinstance(addr, dict) else "Lima")

                    sal_data = item.get("baseSalary", {})
                    salary   = ""
                    if isinstance(sal_data, dict):
                        val = sal_data.get("value", {})
                        if isinstance(val, dict):
                            lo  = val.get("minValue", "")
                            hi  = val.get("maxValue", "")
                            cur = sal_data.get("currency", "")
                            salary = f"{lo} - {hi} {cur}".strip(" -")

                    seen_urls.add(job_url)
                    jobs.append({
                        "title":       title,
                        "company":     comp,
                        "location":    location,
                        "salary":      salary,
                        "date_posted": item.get("datePosted", ""),
                        "url":         job_url,
                        "source":      nombre,
                        "tipo_fuente": TIPO_FUENTE,
                    })
            except Exception:
                pass
        return jobs

    def _parse_html_generic(self, soup, base_url: str, nombre: str, seen_urls: set) -> list:
        """
        Try common CSS patterns for job listings.
        Capped at 50 items per page to avoid noise.
        """
        containers = []
        for selector_fn in [
            lambda s: s.find_all(class_=lambda c: c and any(
                kw in (c or "").lower()
                for kw in ["job-item", "job-card", "job-listing", "vacancy", "position",
                           "oferta", "puesto", "opening", "career-item"]
            )),
            lambda s: s.find_all("article", class_=lambda c: "job" in (c or "").lower()),
            lambda s: s.find_all("li", class_=lambda c: "job" in (c or "").lower()),
            lambda s: s.find_all("div", class_=lambda c: "job" in (c or "").lower() and "description" not in (c or "").lower()),
            lambda s: s.find_all(attrs={"data-job": True}),
            lambda s: s.find_all(attrs={"data-position": True}),
        ]:
            results = selector_fn(soup)
            if results:
                containers = results
                break

        jobs = []
        for item in containers[:50]:
            # Title: first meaningful heading or link text
            title = ""
            for tag in ["h2", "h3", "h4", "strong"]:
                el = item.find(tag)
                if el:
                    text = el.get_text(strip=True)
                    if len(text) > 4:
                        title = text
                        break

            if not title:
                # Fall back to first anchor text
                a = item.find("a")
                if a:
                    title = a.get_text(strip=True)
            if not title:
                continue

            link = item.find("a", href=True)
            if not link:
                continue
            href    = link["href"]
            job_url = href if href.startswith("http") else urljoin(base_url, href)
            if not job_url or job_url in seen_urls:
                continue

            seen_urls.add(job_url)
            jobs.append({
                "title":       title,
                "company":     nombre,
                "location":    "Lima, Perú",
                "salary":      "",
                "date_posted": "",
                "url":         job_url,
                "source":      nombre,
                "tipo_fuente": TIPO_FUENTE,
            })
        return jobs

    # ── JS detection heuristic ────────────────────────────────────────────────

    def _is_js_heavy(self, soup, html: str) -> bool:
        """Return True if the page relies on client-side JS to render job content."""
        script_count  = len(soup.find_all("script"))
        body_text_len = len(soup.get_text(strip=True))
        js_signals = [
            "__NEXT_DATA__"    in html,
            "window.__state"   in html,
            "ng-version"       in html,
            '"react"'          in html.lower() and body_text_len < 600,
            '<div id="root">'  in html and body_text_len < 600,
            '<div id="app">'   in html and body_text_len < 600,
        ]
        return (script_count > 8 and body_text_len < 800) or any(js_signals)
