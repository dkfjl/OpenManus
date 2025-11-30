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


def _referer_for(url: str, source: Optional[str]) -> str:
    try:
        if source:
            # use the actual host page as referer when available
            sp = urlparse(source)
            if sp.scheme and sp.netloc:
                return f"{sp.scheme}://{sp.netloc}/"
    except Exception:
        pass
    try:
        up = urlparse(url)
        if up.scheme and up.netloc:
            return f"{up.scheme}://{up.netloc}/"
    except Exception:
        pass
    return ""


async def _http_head(client: httpx.AsyncClient, url: str, source: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        ref = _referer_for(url, source)
        if ref:
            headers["Referer"] = ref
        r = await client.head(url, headers=headers, follow_redirects=True, timeout=8)
        if r.status_code >= 200 and r.status_code < 400:
            return r.headers.get("content-type"), int(r.headers.get("content-length") or 0)
    except Exception:
        pass
    # Fallback small GET for servers not supporting HEAD
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Range": "bytes=0-0",
        }
        ref = _referer_for(url, source)
        if ref:
            headers["Referer"] = ref
        r = await client.get(url, headers=headers, follow_redirects=True, timeout=10)
        if r.status_code in (200, 206):
            return r.headers.get("content-type"), int(r.headers.get("content-length") or 0)
    except Exception:
        pass
    return None, None


"""Image retrieval utilities used by PPT media enrichment.

This module previously relied on a dedicated [image_search] configuration
with Google CSE/Bing providers. The new approach intentionally routes all
web discovery through the generic WebSearch tool, whose engine order is
driven by [search] in config.toml (e.g., Bocha → Google). We then visit a
few top result pages and extract actual image URLs, verifying them via HEAD.
"""


async def _playwright_collect_images_from_page(page, collected: Set[str], source_map: dict) -> None:
    # Capture network responses for images (catches dynamic requests)
    def _on_response(response):
        try:
            ct = response.headers.get("content-type", "").lower()
            url = response.url
            if url and ct.startswith("image/"):
                collected.add(url)
                try:
                    if url not in source_map:
                        source_map[url] = page.url
                except Exception:
                    pass
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
            try:
                if u not in source_map:
                    source_map[u] = page.url
            except Exception:
                pass
    except Exception:
        pass


async def _playwright_fetch_images_from_urls(urls: List[str], max_pages: int = 10) -> List[ImageCandidate]:
    from playwright.async_api import async_playwright

    browser_cfg = getattr(config, "browser_config", None)
    headless = True if browser_cfg is None else bool(getattr(browser_cfg, "headless", True))
    timeout_ms = 20_000

    collected: Set[str] = set()
    source_map: dict[str, str] = {}
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
                await _playwright_collect_images_from_page(page, collected, source_map)
            except Exception:
                continue
        await browser.close()

    # Normalize to candidates
    out = []
    for u in collected:
        if _is_probably_image_url(u):
            out.append(ImageCandidate(url=u, source=source_map.get(u)))
    return out


async def _simple_fetch_images_from_urls(urls: List[str], max_pages: int = 10) -> List[ImageCandidate]:
    """Lightweight fallback when Playwright is unavailable.

    Fetch a few pages via requests and extract og:image and <img> URLs.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }
    out: List[ImageCandidate] = []
    seen: Set[str] = set()
    for url in urls[:max_pages]:
        try:
            r = await asyncio.get_event_loop().run_in_executor(
                None, lambda: httpx.get(url, headers=headers, timeout=10)
            )
            if r.status_code != 200 or not r.text:
                continue
            from bs4 import BeautifulSoup  # local import to avoid hard dep

            soup = BeautifulSoup(r.text, "html.parser")
            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                u = og.get("content")
                try:
                    u = httpx.URL(u, base=url).human_repr()
                except Exception:
                    pass
                if _is_probably_image_url(u) and u not in seen:
                    seen.add(u)
                    out.append(ImageCandidate(url=u, source=url))
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src")
                if not src:
                    continue
                try:
                    u = httpx.URL(src, base=url).human_repr()
                except Exception:
                    u = src
                if _is_probably_image_url(u) and u not in seen:
                    seen.add(u)
                    out.append(ImageCandidate(url=u, source=url))
                # do not prematurely cut; collect broadly then rank later
        except Exception:
            continue
    return out


async def _discover_with_playwright_fallback(query: str, count: int = 24) -> List[ImageCandidate]:
    """Discovery strategy powered by generic WebSearch + page extraction.

    - Use WebSearch (engine order from [search]) to get top result pages
    - Visit them with Playwright to capture dynamically loaded images
    - If Playwright is unavailable, fall back to simple HTML extraction
    """
    from app.tool.web_search import WebSearch

    ws = WebSearch()
    # Fetch more seed pages to improve coverage/quality
    # 限制单次检索最大 10 条（Bocha 也已在底层强制 ≤10），保持与需求一致
    res = await ws.execute(query=query, num_results=10, fetch_content=False)
    seed_urls = [r.url for r in (res.results or []) if r.url]
    # 同一条内容（URL）只处理一次
    seen_pages: Set[str] = set()
    uniq_seed_urls: List[str] = []
    for u in seed_urls:
        if u not in seen_pages:
            seen_pages.add(u)
            uniq_seed_urls.append(u)
    seed_urls = uniq_seed_urls
    if not seed_urls:
        return []
    # Try Playwright first; gracefully fall back to simple parser
    try:
        cands = await _playwright_fetch_images_from_urls(
            seed_urls, max_pages=min(20, len(seed_urls))
        )
    except Exception as e:
        logger.info(f"Playwright not available, using simple extractor: {e}")
        cands = await _simple_fetch_images_from_urls(
            seed_urls, max_pages=min(20, len(seed_urls))
        )
    # De-dup only; do NOT limit here. We'll verify, score, then pick.
    seen: Set[str] = set()
    out: List[ImageCandidate] = []
    for c in cands:
        if c.url not in seen:
            seen.add(c.url)
            out.append(c)
    return out


def _domain_quality_score(url: str) -> int:
    try:
        netloc = urlparse(url).netloc.lower()
    except Exception:
        return 0
    good = [
        "wikipedia.org",
        "wikimedia.org",
        "gov.cn",
        "gov",
        "edu",
        "reuters.com",
        "bbc.co.uk",
        "nytimes.com",
        "nature.com",
        "sohu.com",
        "thepaper.cn",
        "alibabagroup.com",
    ]
    bad = ["pinimg.com", "pinterest.com", "fbcdn.net", "facebook.com", "x.com"]
    score = 0
    if any(netloc.endswith(d) for d in good):
        score += 3
    if any(netloc.endswith(d) for d in bad):
        score -= 2
    return score


def _rank_candidates(cands: List[ImageCandidate], query: str, limit: int) -> List[ImageCandidate]:
    # Tokenize query for overlap scoring
    q_tokens = [t.lower() for t in re.split(r"[^\w\u4e00-\u9fa5]+", query) if t]

    def score(c: ImageCandidate) -> float:
        s = 0.0
        low = c.url.lower()
        # prefer larger files (>30KB), penalize tiny files
        size = c.size_bytes or 0
        if size >= 200_000:
            s += 3
        elif size >= 80_000:
            s += 2
        elif size >= 30_000:
            s += 1
        else:
            s -= 1
        # prefer jpeg/png over webp slightly
        if low.endswith((".jpg", ".jpeg")):
            s += 1.2
        elif low.endswith(".png"):
            s += 1.0
        elif low.endswith(".webp"):
            s += 0.3
        # penalize thumbnails and sprites
        if any(h in low for h in ["thumbnail", "thumb", "sprite", "icon", "avatar", "logo", "qrcode", "qr", "placeholder"]):
            s -= 2.5
        # domain quality
        s += _domain_quality_score(c.url)
        # simple token overlap
        for t in q_tokens:
            if t and t in low:
                s += 0.6
        return s

    ranked = sorted(cands, key=score, reverse=True)
    return ranked[:limit]


async def _verify_candidates(cands: List[ImageCandidate], want: int) -> List[ImageCandidate]:
    """HEAD-verify a broader pool, then return verified candidates with metadata.
    """
    verified: List[ImageCandidate] = []
    # verify up to 60 items to get enough size info for ranking
    probe_n = min(60, max(want * 6, len(cands)))
    async with httpx.AsyncClient(timeout=10) as client:
        # First pass: test with domain-root referer only (best for downstream fetch)
        tasks1 = [_http_head(client, c.url, source=None) for c in cands[:probe_n]]
        results1 = await asyncio.gather(*tasks1, return_exceptions=True)
        remaining: List[ImageCandidate] = []
        for c, res in zip(cands[:probe_n], results1):
            if isinstance(res, Exception):
                remaining.append(c)
                continue
            ctype, size = res
            if not ctype or not ctype.lower().startswith("image/"):
                if not _is_probably_image_url(c.url):
                    remaining.append(c)
                    continue
            c.content_type = ctype
            c.size_bytes = size
            verified.append(c)

        # Optional second pass: with source referer for sites that require it
        # We do NOT include these by default to avoid later PPT download failures.
        # Keep only if we still lack enough items and have no other choice.
        if len(verified) < want and remaining:
            tasks2 = [_http_head(client, c.url, source=c.source) for c in remaining]
            results2 = await asyncio.gather(*tasks2, return_exceptions=True)
            for c, res in zip(remaining, results2):
                if isinstance(res, Exception):
                    continue
                ctype, size = res
                if not ctype or not ctype.lower().startswith("image/"):
                    if not _is_probably_image_url(c.url):
                        continue
                c.content_type = ctype
                c.size_bytes = size
                verified.append(c)
    return verified


async def discover_image_urls(query: str, max_images: int = 4) -> List[str]:
    """Image discovery via generic WebSearch + page extraction.

    Uses the [search] engine order from config.toml (e.g., Bocha → Google)
    to find relevant pages, extracts candidate image URLs, verifies them with
    HEAD, and returns direct image links.
    """
    log_execution_event(
        "image_discovery",
        "start",
        {"query": query, "max": max_images, "engine": getattr(getattr(config, "search_config", None), "engine", "")},
    )

    candidates: List[ImageCandidate] = await _discover_with_playwright_fallback(
        query, count=max_images * 6
    )

    if not candidates:
        log_execution_event("image_discovery", "no_candidates", {"query": query})
        return []

    # Verify many, then rank and pick best
    verified = await _verify_candidates(candidates, max_images)
    if not verified:
        log_execution_event("image_discovery", "verified_empty", {"query": query})
        return []
    picked = _rank_candidates(verified, query=query, limit=max_images)
    urls = [c.url for c in picked]
    log_execution_event("image_discovery", "done", {"found": len(urls)})
    return urls


async def discover_image_assets(query: str, max_images: int = 4) -> List[ImageCandidate]:
    """Like discover_image_urls but returns ImageCandidate objects with source info.

    Used when downstream needs per-URL referer (to bypass hotlinking).
    """
    log_execution_event(
        "image_discovery",
        "start_assets",
        {"query": query, "max": max_images},
    )
    candidates: List[ImageCandidate] = await _discover_with_playwright_fallback(
        query, count=max_images * 6
    )
    if not candidates:
        log_execution_event("image_discovery", "no_candidates_assets", {"query": query})
        return []
    verified = await _verify_candidates(candidates, max_images)
    if not verified:
        return []
    picked = _rank_candidates(verified, query=query, limit=max_images)
    return picked


async def discover_image_assets_with_refine(
    *, topic: str, section: str, point: str, language: Optional[str] = None, desired: int = 2, max_attempts: int = 3
) -> List[ImageCandidate]:
    base_query = " ".join(x for x in [topic, section, point] if x)
    seen: Set[str] = set()
    results: List[ImageCandidate] = []
    temps = [0.2, 0.4, 0.7]
    for attempt in range(max_attempts):
        temp = temps[attempt] if attempt < len(temps) else temps[-1]
        refined = await refine_image_queries(
            topic=topic, section=section, point=point, language=language, max_variants=3, temperature=temp
        )
        queries = refined + [base_query]
        for q in queries:
            assets = await discover_image_assets(q, max_images=max(desired * 2, 4))
            for c in assets:
                if c.url not in seen:
                    seen.add(c.url)
                    results.append(c)
            if len(results) >= desired * 2:
                break
        if len(results) >= desired:
            break
    return results


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
