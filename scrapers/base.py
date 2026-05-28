import random
import time
import logging
import requests
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]


class BaseScraper(ABC):
    def __init__(self, delay_range=(1.5, 3.5), max_retries=3):
        self.delay_range = delay_range
        self.max_retries = max_retries
        self.session = requests.Session()
        self.logger = logging.getLogger(self.__class__.__name__)

    def get_headers(self):
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def get(self, url, **kwargs):
        for attempt in range(self.max_retries):
            try:
                time.sleep(random.uniform(*self.delay_range))
                headers = kwargs.pop("headers", self.get_headers())
                response = self.session.get(url, headers=headers, timeout=20, **kwargs)
                response.raise_for_status()
                return response
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code in (403, 429):
                    wait = (attempt + 1) * random.uniform(5, 10)
                    self.logger.warning(f"Rate limited ({e.response.status_code}), waiting {wait:.1f}s")
                    time.sleep(wait)
                else:
                    self.logger.warning(f"HTTP error attempt {attempt+1}/{self.max_retries} for {url}: {e}")
                if attempt == self.max_retries - 1:
                    raise
            except requests.exceptions.ConnectionError as e:
                # DNS / connection failures won't improve with retries — bail immediately
                self.logger.warning(f"Request error attempt {attempt+1}/{self.max_retries} for {url}: {e}")
                raise
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"Request error attempt {attempt+1}/{self.max_retries} for {url}: {e}")
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(random.uniform(2, 5))
        return None

    @abstractmethod
    def scrape(self):
        """Return a list of job dicts with keys: title, company, location, salary, date_posted, url, source"""
        pass
