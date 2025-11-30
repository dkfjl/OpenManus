from typing import List

from duckduckgo_search import DDGS
from app.config import config
import requests

from app.tool.search.base import SearchItem, WebSearchEngine


class DuckDuckGoSearchEngine(WebSearchEngine):
    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """
        DuckDuckGo search engine.

        Returns results formatted according to SearchItem model.
        """
        # External API mode (optional)
        scfg = getattr(config, "search_config", None)
        use_api = bool(getattr(scfg, "ddg_use_api", False)) if scfg else False
        if use_api and getattr(scfg, "ddg_api_key", None):
            api_items = self._search_api(query, num_results=num_results)
            if api_items:
                return api_items[:num_results]

        # Pull optional DDG params from config for built-in backends
        region = getattr(config.search_config, "ddg_region", None) if config.search_config else None
        safesearch = getattr(config.search_config, "ddg_safesearch", None) if config.search_config else None
        timelimit = getattr(config.search_config, "ddg_timelimit", None) if config.search_config else None
        backend = getattr(config.search_config, "ddg_backend", "api") if config.search_config else "api"

        kwargs = {"max_results": num_results, "backend": backend}
        if region:
            kwargs["region"] = region
        if safesearch:
            kwargs["safesearch"] = safesearch
        if timelimit:
            kwargs["timelimit"] = timelimit

        try:
            with DDGS() as ddgs:
                raw_results = list(ddgs.text(query, **kwargs))
        except Exception:
            return []

        results = []
        for i, item in enumerate(raw_results):
            if isinstance(item, str):
                # If it's just a URL
                results.append(
                    SearchItem(
                        title=f"DuckDuckGo Result {i + 1}", url=item, description=None
                    )
                )
            elif isinstance(item, dict):
                # Extract data from the dictionary
                results.append(
                    SearchItem(
                        title=item.get("title", f"DuckDuckGo Result {i + 1}"),
                        url=item.get("href", ""),
                        description=item.get("body", None),
                    )
                )
            else:
                # Try to extract attributes directly
                try:
                    results.append(
                        SearchItem(
                            title=getattr(item, "title", f"DuckDuckGo Result {i + 1}"),
                            url=getattr(item, "href", ""),
                            description=getattr(item, "body", None),
                        )
                    )
                except Exception:
                    # Fallback
                    results.append(
                        SearchItem(
                            title=f"DuckDuckGo Result {i + 1}",
                            url=str(item),
                            description=None,
                        )
                    )

        return results

    def _search_api(self, query: str, num_results: int = 10) -> List[SearchItem]:
        scfg = getattr(config, "search_config", None)
        if not scfg or not getattr(scfg, "ddg_api_key", None):
            return []
        endpoint = getattr(scfg, "ddg_api_endpoint", None) or "https://duckduckgo10.p.rapidapi.com/search"
        params = {"q": query}
        headers = {}
        # RapidAPI style headers
        host = getattr(scfg, "ddg_api_host", None)
        if host:
            headers["X-RapidAPI-Host"] = host
        headers["X-RapidAPI-Key"] = scfg.ddg_api_key

        try:
            r = requests.get(endpoint, params=params, headers=headers, timeout=12)
            if r.status_code != 200:
                return []
            data = r.json()
            # Attempt to locate a list of results generically
            candidates = []
            for key in ("results", "data", "organic_results", "items"):
                v = data.get(key)
                if isinstance(v, list) and v:
                    candidates = v
                    break
            if not candidates:
                # try flatten list in JSON
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        candidates = v
                        break
            out: List[SearchItem] = []
            for i, item in enumerate(candidates):
                title = (
                    item.get("title")
                    or item.get("name")
                    or item.get("heading")
                    or f"DuckDuckGo Result {i+1}"
                )
                url = item.get("url") or item.get("link") or item.get("href") or ""
                desc = item.get("description") or item.get("snippet") or item.get("abstract") or ""
                if url:
                    out.append(SearchItem(title=title, url=url, description=desc))
                if len(out) >= num_results:
                    break
            return out
        except Exception:
            return []
