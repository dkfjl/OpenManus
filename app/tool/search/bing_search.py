from typing import List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from app.logger import logger
from app.config import config
from urllib.parse import urlencode
from app.tool.search.base import SearchItem, WebSearchEngine


ABSTRACT_MAX_LENGTH = 300

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Ubuntu Chromium/49.0.2623.108 Chrome/49.0.2623.108 Safari/537.36",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; pt-BR) AppleWebKit/533.3 (KHTML, like Gecko) QtWeb Internet Browser/3.7 http://www.QtWeb.net",
    "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US) AppleWebKit/532.2 (KHTML, like Gecko) ChromePlus/4.0.222.3 Chrome/4.0.222.3 Safari/532.2",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.4pre) Gecko/20070404 K-Ninja/2.1.3",
    "Mozilla/5.0 (Future Star Technologies Corp.; Star-Blade OS; x86_64; U; en-US) iNet Browser 4.7",
    "Mozilla/5.0 (Windows; U; Windows NT 6.1; rv:2.2) Gecko/20110201",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.13) Gecko/20080414 Firefox/2.0.0.13 Pogo/2.0.0.13.6866",
]

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": USER_AGENTS[0],
    "Referer": "https://www.bing.com/",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

BING_HOST_URL = "https://www.bing.com"
BING_SEARCH_URL = "https://www.bing.com/search?q="


class BingSearchEngine(WebSearchEngine):
    session: Optional[requests.Session] = None

    def __init__(self, **data):
        """Initialize the BingSearch tool with a requests session."""
        super().__init__(**data)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _build_search_url(self, query: str) -> str:
        # Read optional settings
        scfg = getattr(config, "search_config", None)
        mkt = getattr(scfg, "bing_mkt", None) if scfg else None
        cc = getattr(scfg, "bing_cc", None) if scfg else None
        lang = getattr(scfg, "bing_lang", None) if scfg else None
        adlt = getattr(scfg, "bing_safesearch", None) if scfg else None

        params = {"q": query}
        if mkt:
            params["mkt"] = mkt
            params["setmkt"] = mkt
        if lang:
            params["setlang"] = lang
        if cc:
            params["cc"] = cc
        if adlt:
            params["adlt"] = adlt  # off|moderate|strict
        return f"{BING_HOST_URL}/search?{urlencode(params)}"

    def _search_sync(self, query: str, num_results: int = 10) -> List[SearchItem]:
        """
        Synchronous Bing search implementation to retrieve search results.

        Args:
            query (str): The search query to submit to Bing.
            num_results (int, optional): Maximum number of results to return. Defaults to 10.

        Returns:
            List[SearchItem]: A list of search items with title, URL, and description.
        """
        if not query:
            return []

        # Prefer official Bing Web Search API if configured
        scfg = getattr(config, "search_config", None)
        use_api = bool(getattr(scfg, "bing_use_api", False)) if scfg else False
        if use_api and getattr(scfg, "bing_api_key", None):
            api_results = self._search_api(query, num_results=num_results)
            if api_results:
                return api_results[:num_results]

        list_result = []
        first = 1
        next_url = self._build_search_url(query)

        while len(list_result) < num_results:
            data, next_url = self._parse_html(
                next_url, rank_start=len(list_result), first=first
            )
            if data:
                list_result.extend(data)
            if not next_url:
                break
            first += 10

        return list_result[:num_results]

    def _search_api(self, query: str, num_results: int = 10) -> List[SearchItem]:
        scfg = getattr(config, "search_config", None)
        if not scfg or not getattr(scfg, "bing_api_key", None):
            return []
        endpoint = getattr(scfg, "bing_api_endpoint", None) or "https://api.bing.microsoft.com/v7.0/search"
        params = {"q": query, "count": min(50, max(1, num_results))}
        # Locale/safety
        if getattr(scfg, "bing_mkt", None):
            params["mkt"] = scfg.bing_mkt
        if getattr(scfg, "bing_safesearch", None):
            params["safeSearch"] = scfg.bing_safesearch  # Off|Moderate|Strict
        headers = {"Ocp-Apim-Subscription-Key": scfg.bing_api_key}
        try:
            r = self.session.get(endpoint, params=params, headers=headers, timeout=12)
            if r.status_code != 200:
                logger.warning(f"Bing API non-200: {r.status_code} {r.text[:200]}")
                return []
            data = r.json()
            values = (data.get("webPages") or {}).get("value") or []
            out: List[SearchItem] = []
            for i, v in enumerate(values):
                name = v.get("name") or f"Bing Result {i+1}"
                url = v.get("url") or ""
                snippet = v.get("snippet") or ""
                out.append(SearchItem(title=name, url=url, description=snippet))
                if len(out) >= num_results:
                    break
            return out
        except Exception as e:
            logger.warning(f"Bing API failed: {e}")
            return []

    def _parse_html(
        self, url: str, rank_start: int = 0, first: int = 1
    ) -> Tuple[List[SearchItem], str]:
        """
        Parse Bing search result HTML to extract search results and the next page URL.

        Returns:
            tuple: (List of SearchItem objects, next page URL or None)
        """
        try:
            # Update Accept-Language from config if present
            scfg = getattr(config, "search_config", None)
            if scfg and getattr(scfg, "lang", None):
                lang = scfg.lang
                country = getattr(scfg, "country", "")
                self.session.headers["Accept-Language"] = f"{lang}-{country},{lang};q=0.9"
            res = self.session.get(url=url)
            res.encoding = "utf-8"
            root = BeautifulSoup(res.text, "lxml")

            list_data = []
            ol_results = root.find("ol", id="b_results")
            if not ol_results:
                return [], None

            for li in ol_results.find_all("li", class_="b_algo"):
                title = ""
                url = ""
                abstract = ""
                try:
                    h2 = li.find("h2")
                    if h2:
                        title = h2.text.strip()
                        url = h2.a["href"].strip()

                    p = li.find("p")
                    if p:
                        abstract = p.text.strip()

                    if ABSTRACT_MAX_LENGTH and len(abstract) > ABSTRACT_MAX_LENGTH:
                        abstract = abstract[:ABSTRACT_MAX_LENGTH]

                    rank_start += 1

                    # Create a SearchItem object
                    list_data.append(
                        SearchItem(
                            title=title or f"Bing Result {rank_start}",
                            url=url,
                            description=abstract,
                        )
                    )
                except Exception:
                    continue

            next_btn = root.find("a", title="Next page")
            if not next_btn:
                return list_data, None

            next_url = BING_HOST_URL + next_btn["href"]
            return list_data, next_url
        except Exception as e:
            logger.warning(f"Error parsing HTML: {e}")
            return [], None

    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """
        Bing search engine.

        Returns results formatted according to SearchItem model.
        """
        return self._search_sync(query, num_results=num_results)
