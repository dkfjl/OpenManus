from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple
from urllib.parse import urlparse

import httpx
from app.config import config
from app.llm import LLM
from app.schema import Message
from app.logger import logger
from app.services.execution_log_service import log_execution_event


@dataclass
class ImageCandidate:
    url: str
    source: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None


def _is_probably_image_url(u: str) -> bool:
    low = (u or "").lower()
    if not low.startswith("http"):
        return False
    if any(x in low for x in ["qr", "qrcode", "barcode", "logo", "sprite", "icon", "placeholder"]):
        return False
    return any(low.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]) or \
        any(ext in low for ext in [".jpg?", ".jpeg?", ".png?", ".webp?"])


async def _http_head(client: httpx.AsyncClient, url: str) -> Tuple[Optional[str], Optional[int]]:
    try:
        r = await client.head(url, follow_redirects=True, timeout=8)
        if r.status_code >= 200 and r.status_code < 400:
            return r.headers.get("content-type"), int(r.headers.get("content-length") or 0)
    except Exception:
        pass
    # Fallback small GET for servers not supporting HEAD
    try:
        r = await client.get(url, follow_redirects=True, timeout=10, headers={"Range": "bytes=0-0"})
        if r.status_code in (200, 206):
            return r.headers.get("content-type"), int(r.headers.get("content-length") or 0)
    except Exception:
        pass
    return None, None


class GoogleImageSearchProvider:
    """Google Custom Search JSON API (image search via CSE).

    Requires `google_api_key` and `google_cx` in [image_search] config.
    """

    def __init__(self):
        cfg = getattr(config, "image_search_config", None)
        self.api_key = None
        self.cx = None
        self.endpoint = "https://www.googleapis.com/customsearch/v1"
        self.safe = "medium"
        self.gl = None  # country code
        self.lr = None  # language restrict
        if cfg:
            self.api_key = getattr(cfg, "google_api_key", None)
            self.cx = getattr(cfg, "google_cx", None)
            self.endpoint = getattr(cfg, "google_endpoint", None) or self.endpoint
            self.safe = getattr(cfg, "google_safe", "medium")
        # borrow from general search config when present
        scfg = getattr(config, "search_config", None)
        if scfg:
            self.gl = getattr(scfg, "country", None)
            lang = getattr(scfg, "lang", None)
            if lang:
                # Google lr format like 'lang_en', 'lang_zh-CN'
                self.lr = f"lang_{lang}"

    def available(self) -> bool:
        return bool(self.api_key and self.cx)

    async def search(self, query: str, count: int = 10) -> List[ImageCandidate]:
        if not self.available():
            return []
        params = {
            "key": self.api_key,
            "cx": self.cx,
            "q": query,
            "num": min(max(count, 1), 10),  # Google max per page is 10
            "searchType": "image",
            "safe": self.safe,  # off|medium|high
        }
        if self.gl:
            params["gl"] = self.gl
        if self.lr:
            params["lr"] = self.lr

        async with httpx.AsyncClient(timeout=15) as client:
            try:
                r = await client.get(self.endpoint, params=params)
                if r.status_code != 200:
                    logger.warning(f"Google CSE non-200: {r.status_code} {r.text[:200]}")
                    return []
                data = r.json()
                items = data.get("items") or []
                out: List[ImageCandidate] = []
                for it in items:
                    link = it.get("link")  # direct image url
                    img = it.get("image") or {}
                    ctx = img.get("contextLink") or it.get("displayLink")
                    if not link:
                        continue
                    out.append(ImageCandidate(url=link, source=ctx))
                return out
            except Exception as e:
                logger.warning(f"Google CSE failed: {e}")
                return []


async def _playwright_collect_images_from_page(page, collected: Set[str]) -> None:
    # Capture network responses for images (catches dynamic requests)
    def _on_response(response):
        try:
            ct = response.headers.get("content-type", "").lower()
            url = response.url
            if url and ct.startswith("image/"):
                collected.add(url)
        except Exception:
            pass

    page.on("response", _on_response)

    # Extract from DOM: img/src, data-src, srcset, picture>source, inline styles
    script = """
    () => {
      const urls = new Set();
      const push = (u) => { try { if (u && typeof u === 'string') urls.add(u); } catch(e){} };

      const abs = (u) => {
        try { return new URL(u, location.href).href; } catch(e) { return null; }
      };

      // <img> tags
      document.querySelectorAll('img').forEach(img => {
        const cands = [img.getAttribute('src'), img.getAttribute('data-src')];
        cands.forEach(u => { const a = abs(u); if (a) push(a); });
        const srcset = img.getAttribute('srcset') || img.getAttribute('data-srcset');
        if (srcset) {
          srcset.split(',').forEach(part => {
            const u = part.trim().split(' ')[0];
            const a = abs(u); if (a) push(a);
          });
        }
      });

      // <picture><source>
      document.querySelectorAll('picture source').forEach(s => {
        const srcset = s.getAttribute('srcset') || s.getAttribute('data-srcset');
        if (srcset) {
          srcset.split(',').forEach(part => { const u = part.trim().split(' ')[0]; const a = abs(u); if (a) push(a); });
        }
      });

      // Inline style background-image
      document.querySelectorAll('*').forEach(el => {
        const bg = getComputedStyle(el).backgroundImage;
        if (bg && bg !== 'none') {
          const m = bg.match(/url\(("|')?(.*?)("|')?\)/);
          if (m && m[2]) { const a = abs(m[2]); if (a) push(a); }
        }
      });

      return Array.from(urls);
    }
    """
    try:
        urls = await page.evaluate(script)
        for u in urls:
            collected.add(u)
    except Exception:
        pass


async def _playwright_fetch_images_from_urls(urls: List[str], max_pages: int = 3) -> List[ImageCandidate]:
    from playwright.async_api import async_playwright

    browser_cfg = getattr(config, "browser_config", None)
    headless = True if browser_cfg is None else bool(getattr(browser_cfg, "headless", True))
    timeout_ms = 20_000

    collected: Set[str] = set()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=getattr(browser_cfg, "extra_chromium_args", []) or [])
        page = await browser.new_page()
        # Simple UA to reduce blocks
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        })

        for url in urls[:max_pages]:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                # allow async loads
                try:
                    await page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    pass
                await _playwright_collect_images_from_page(page, collected)
            except Exception:
                continue
        await browser.close()

    # Normalize to candidates
    out = []
    for u in collected:
        if _is_probably_image_url(u):
            out.append(ImageCandidate(url=u))
    return out


async def _discover_with_playwright_fallback(query: str, count: int = 8) -> List[ImageCandidate]:
    """Fallback strategy:
    - Use existing WebSearch tool to get a few top pages
    - Visit them with Playwright and extract images after JS render
    """
    from app.tool.web_search import WebSearch

    ws = WebSearch()
    res = await ws.execute(query=query, num_results=5, fetch_content=False)
    seed_urls = [r.url for r in (res.results or []) if r.url]
    if not seed_urls:
        return []
    cands = await _playwright_fetch_images_from_urls(seed_urls, max_pages=min(5, len(seed_urls)))
    # De-dup and limit
    seen: Set[str] = set()
    out: List[ImageCandidate] = []
    for c in cands:
        if c.url not in seen:
            seen.add(c.url)
            out.append(c)
        if len(out) >= count:
            break
    return out


async def _verify_candidates(cands: List[ImageCandidate], max_items: int) -> List[ImageCandidate]:
    """HEAD-verify candidates and keep images with valid content-type and size.
    """
    verified: List[ImageCandidate] = []
    async with httpx.AsyncClient(timeout=10) as client:
        tasks = [
            _http_head(client, c.url) for c in cands[: max_items * 2]  # probe extra to compensate drops
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for c, res in zip(cands, results):
            if isinstance(res, Exception):
                continue
            ctype, size = res
            if not ctype or not ctype.lower().startswith("image/"):
                # allow when URL is strongly indicative of image type
                if not _is_probably_image_url(c.url):
                    continue
            c.content_type = ctype
            c.size_bytes = size
            verified.append(c)
            if len(verified) >= max_items:
                break
    return verified


async def discover_image_urls(query: str, max_images: int = 4) -> List[str]:
    """High-reliability image discovery pipeline.

    1) Try official Bing Image Search API if configured
    2) Fallback to Playwright: search pages and extract rendered images
    3) Verify by HEAD/GET, normalize and return direct URLs
    """
    log_execution_event("image_discovery", "start", {"query": query, "max": max_images})

    # Stage 1: API providers according to priority
    candidates: List[ImageCandidate] = []
    priority = ["google_cse", "playwright"]
    cfg = getattr(config, "image_search_config", None)
    if cfg and getattr(cfg, "provider_priority", None):
        priority = list(cfg.provider_priority)

    for provider in priority:
        if provider == "google_cse":
            g = GoogleImageSearchProvider()
            if g.available():
                try:
                    candidates = await g.search(query, count=max_images * 3)
                except Exception as e:
                    logger.warning(f"Google CSE error: {e}")
        elif provider == "playwright":
            candidates = await _discover_with_playwright_fallback(query, count=max_images * 3)
        # stop at first that yields results
        if candidates:
            break

    if not candidates:
        log_execution_event("image_discovery", "no_candidates", {"query": query})
        return []

    # Stage 3: Verify & normalize
    verified = await _verify_candidates(candidates, max_images)
    urls = [c.url for c in verified]
    log_execution_event("image_discovery", "done", {"found": len(urls)})
    return urls


async def refine_image_queries(
    *, topic: str, section: str, point: str, language: Optional[str] = None, max_variants: int = 3, temperature: float = 0.2
) -> List[str]:
    lang = (language or "zh").lower()
    is_zh = lang.startswith("zh")
    ask = (
        "请针对图像搜索生成1-3个更精准的短检索词，避免品牌/Logo/二维码等，并有助于找到可直接访问的图片。只返回JSON数组（字符串）。"
        if is_zh
        else "Generate 1-3 concise image-search queries to find directly accessible images; avoid brand/logos/QR codes. Return a JSON array of strings only."
    )
    hints = (
        "可以适度加入主题关键词、关键名词、语义限定与同义词。不必包含引号或文件后缀。"
        if is_zh
        else "Use essential topic keywords and semantic qualifiers; no quotes or file suffixes needed."
    )
    base = f"topic: {topic}\nsection: {section}\npoint: {point}"
    prompt = f"{ask}\n{base}\n{hints}"
    llm = LLM()
    try:
        resp = await llm.ask([Message.user_message(prompt)], stream=False, temperature=temperature)
        import json as _json, re as _re
        arr = None
        try:
            arr = _json.loads(resp)
        except Exception:
            m = _re.search(r"\[.*\]", resp, _re.DOTALL)
            if m:
                arr = _json.loads(m.group(0))
        out: List[str] = []
        if isinstance(arr, list):
            for s in arr:
                try:
                    q = str(s).strip()
                    if q and q not in out:
                        out.append(q)
                except Exception:
                    continue
                if len(out) >= max_variants:
                    break
        return out
    except Exception:
        return []


async def discover_image_urls_with_refine(
    *, topic: str, section: str, point: str, language: Optional[str] = None, desired: int = 2, max_attempts: int = 3
) -> List[str]:
    base_query = " ".join(x for x in [topic, section, point] if x)
    seen: Set[str] = set()
    results: List[str] = []
    temps = [0.2, 0.4, 0.7]
    for attempt in range(max_attempts):
        temp = temps[attempt] if attempt < len(temps) else temps[-1]
        refined = await refine_image_queries(
            topic=topic, section=section, point=point, language=language, max_variants=3, temperature=temp
        )
        queries = refined + [base_query]
        for q in queries:
            urls = await discover_image_urls(q, max_images=max(desired * 2, 4))
            for u in urls:
                if u not in seen:
                    seen.add(u)
                    results.append(u)
            if len(results) >= desired * 2:
                break
        if len(results) >= desired:  # got at least enough to try selection
            break
    return results
