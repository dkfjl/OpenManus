import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import aiohttp
from aiohttp import ClientError
from pydantic import BaseModel, Field

from app.config import config
from app.logger import logger


class DifyRetrievalRequest(BaseModel):
    """Request model for Dify knowledge base retrieval"""

    query: str = Field(..., description="Search query")
    score_threshold: float = Field(0.5, description="Score threshold")
    top_k: int = Field(3, description="Number of results")
    # Optional and flexible: allow either dict or string (to be normalized later)
    retrieval_model: Optional[Any] = Field(
        default=None, description="Retrieval model configuration (dict or string)"
    )


class DifyRetrievalResponse(BaseModel):
    """Response model for Dify knowledge base retrieval"""

    records: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = Field(0, description="Total number of records")
    query: str = Field(..., description="Original query")


class DifyClient:
    """Client for interacting with Dify knowledge base API"""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    def _setup_session(self):
        """Setup aiohttp session with proper configuration"""
        if not self.session:
            timeout = aiohttp.ClientTimeout(
                total=config.dify.timeout if config.dify else 5
            )
            self.session = aiohttp.ClientSession(timeout=timeout)

    async def __aenter__(self):
        self._setup_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def retrieve_knowledge(
        self,
        query: str,
        dataset_id: Optional[str] = None,
        retrieval_model: Optional[Union[str, Dict[str, Any]]] = None,
        score_threshold: float = 0.5,
        top_k: int = 3,
    ) -> DifyRetrievalResponse:
        """
        Retrieve knowledge from Dify knowledge base

        Args:
            query: Search query
            dataset_id: Dataset ID (optional)
            retrieval_model: Retrieval model
            score_threshold: Minimum relevance score
            top_k: Number of top results

        Returns:
            DifyRetrievalResponse with retrieved records
        """
        if not config.dify or not config.dify.api_key:
            raise ValueError("Dify configuration not properly set")

        # Build base payload (omit retrieval_model for now)
        request_data = DifyRetrievalRequest(
            query=query,
            score_threshold=score_threshold,
            top_k=top_k,
        )

        # Determine dataset ID
        target_dataset_id = dataset_id or config.dify.dataset_id
        if not target_dataset_id:
            raise ValueError("Dataset ID is required")

        # Build API URL
        api_base = config.dify.api_base.rstrip("/")
        url = f"{api_base}/datasets/{target_dataset_id}/retrieve"

        # Build headers
        headers = {
            "Authorization": f"Bearer {config.dify.api_key}",
            "Content-Type": "application/json",
        }

        logger.info(f"Retrieving knowledge from Dify: {query}")

        # Ensure session is setup before using it
        self._setup_session()

        try:
            data, status, error_text = await self._post_with_retries(
                url=url,
                headers=headers,
                json=self._build_payload(request_data, retrieval_model),
                timeout_sec=(config.dify.timeout if config.dify else 5),
                max_retries=(config.dify.max_retries if config.dify else 0),
            )

            if status == 200 and isinstance(data, dict):
                return DifyRetrievalResponse(
                    records=data.get("records", []),
                    total=data.get("total", 0),
                    query=query,
                )

            logger.error(f"Dify API error {status}: {error_text}")
            raise Exception(f"Dify API error {status}: {error_text}")

        except asyncio.TimeoutError:
            logger.error("Dify API request timed out")
            raise Exception("Connection to knowledge base timed out")
        except Exception as e:
            logger.error(f"Error calling Dify API: {str(e)}")
            raise Exception(f"Failed to retrieve knowledge: {str(e)}")

    async def close(self):
        """Close the HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None

    # ---------------------------------
    # Internal helpers
    # ---------------------------------
    def _build_payload(
        self,
        base: DifyRetrievalRequest,
        retrieval_model: Optional[Union[str, Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Construct request payload with backward-compatible retrieval_model handling.

        Rules:
        - If retrieval_model is None: omit the field (server default).
        - If it's a string: send as {"name": <string>}.
        - If it's a dict: pass through as-is.
        - Otherwise: omit and warn.
        """
        # Prefer Pydantic v2 API if available
        try:
            payload: Dict[str, Any] = base.model_dump(exclude_none=True)  # type: ignore[attr-defined]
        except Exception:
            payload = base.dict(exclude_none=True)

        # Extract top-level knobs; these are expected inside retrieval_model per docs.
        top_k_val = payload.pop("top_k", None)
        score_threshold_val = payload.pop("score_threshold", None)

        # If no retrieval_model provided, just return minimal payload with query only.
        # The server will apply its defaults. We keep backward compatibility by
        # not forcing a retrieval_model unless caller supplied one.
        if retrieval_model is None:
            return payload

        # Normalize retrieval_model
        rm: Dict[str, Any]
        if isinstance(retrieval_model, str):
            # Map legacy short names to official search_method enum.
            name = retrieval_model.strip().lower()
            mapping = {
                "search": "hybrid_search",
                "hybrid": "hybrid_search",
                "hybrid_search": "hybrid_search",
                "semantic": "semantic_search",
                "semantic_search": "semantic_search",
                "keyword": "keyword_search",
                "keyword_search": "keyword_search",
                "full_text": "full_text_search",
                "full_text_search": "full_text_search",
                "fulltext": "full_text_search",
            }
            rm = {"search_method": mapping.get(name, "hybrid_search")}
        elif isinstance(retrieval_model, dict):
            rm = dict(retrieval_model)  # shallow copy
        else:
            logger.warning(
                "Unsupported retrieval_model type %r, omitting field.", type(retrieval_model)
            )
            return payload

        # Fill in top_k and score_threshold knobs if caller provided at top-level
        if top_k_val is not None and "top_k" not in rm:
            rm["top_k"] = top_k_val

        # Always include expected flags to avoid server-side KeyError
        if score_threshold_val is not None:
            rm["score_threshold_enabled"] = True
            rm["score_threshold"] = score_threshold_val
        else:
            rm["score_threshold_enabled"] = rm.get("score_threshold_enabled", False)
            # Do not set score_threshold when disabled

        # Ensure reranking flag is present; default to False unless explicitly provided
        if "reranking_enable" not in rm:
            rm["reranking_enable"] = False

        # Attach normalized retrieval_model
        payload["retrieval_model"] = rm
        return payload

    async def _post_with_retries(
        self,
        url: str,
        headers: Dict[str, str],
        json: Dict[str, Any],
        timeout_sec: int,
        max_retries: int,
    ) -> tuple[Optional[Dict[str, Any]], int, str]:
        """POST with basic retry/backoff on transient failures and timeouts.

        Returns: (json_data | None, status_code, error_text)
        """
        attempts = max(0, int(max_retries)) + 1
        backoff = 0.5
        last_error_text = ""
        last_status = 0

        # Build per-request timeout to override session default if needed
        req_timeout = aiohttp.ClientTimeout(total=timeout_sec)

        for attempt in range(1, attempts + 1):
            try:
                assert self.session is not None
                async with self.session.post(
                    url, headers=headers, json=json, timeout=req_timeout
                ) as resp:
                    last_status = resp.status
                    text = await resp.text()
                    last_error_text = text

                    # 2xx fast path
                    if 200 <= resp.status < 300:
                        try:
                            return await resp.json(), resp.status, ""
                        except Exception:
                            # If JSON decode fails, still return text
                            return None, resp.status, text

                    # Retry on 408, 429, and 5xx
                    if resp.status in (408, 429) or 500 <= resp.status < 600:
                        if attempt < attempts:
                            await asyncio.sleep(backoff)
                            backoff = min(backoff * 2, 8.0)
                            continue
                    # Non-retryable error
                    return None, resp.status, text

            except asyncio.TimeoutError:
                last_error_text = "request timed out"
                last_status = 0
                if attempt < attempts:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                    continue
                raise
            except ClientError as e:
                # Network/client error; retry some
                last_error_text = str(e)
                last_status = 0
                if attempt < attempts:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                    continue
                return None, 0, last_error_text

        return None, last_status, last_error_text


# Global client instance
dify_client = DifyClient()
