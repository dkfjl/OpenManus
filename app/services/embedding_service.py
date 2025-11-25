import asyncio
import math
from typing import List, Sequence

from openai import AsyncAzureOpenAI, AsyncOpenAI, OpenAIError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_fixed

from app.config import EmbeddingSettings, config
from app.logger import logger


class EmbeddingService:
    """Async helper for generating embeddings used by the vector knowledge base."""

    def __init__(self, settings: EmbeddingSettings | None = None):
        self.settings = settings or config.knowledge_base_config.embedding
        self._llm_settings = self._resolve_llm_settings(self.settings.profile_name)
        self._client = self._build_client()
        self._client_lock = asyncio.Lock()

    def _resolve_llm_settings(self, profile_name: str):
        profiles = config.llm
        if profile_name in profiles:
            return profiles[profile_name]
        if "default" in profiles:
            return profiles["default"]
        raise ValueError("LLM configuration is missing a default profile")

    def _build_client(self):
        api_type = (self._llm_settings.api_type or "").lower()
        if api_type == "azure":
            return AsyncAzureOpenAI(
                api_key=self._llm_settings.api_key,
                azure_endpoint=self._llm_settings.base_url,
                api_version=self._llm_settings.api_version,
                timeout=self.settings.request_timeout,
            )
        return AsyncOpenAI(
            api_key=self._llm_settings.api_key,
            base_url=self._llm_settings.base_url,
            timeout=self.settings.request_timeout,
        )

    async def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        """Embed a batch of texts, preserving order and skipping empty strings."""

        normalized_inputs = [text.strip() for text in texts if text and text.strip()]
        if not normalized_inputs:
            return []

        embeddings: List[List[float]] = []
        batch_size = max(1, self.settings.batch_size)

        for start in range(0, len(normalized_inputs), batch_size):
            batch = normalized_inputs[start : start + batch_size]
            batch_embeddings = await self._embed_batch(batch)
            embeddings.extend(batch_embeddings)

        return embeddings

    async def embed_query(self, query: str) -> List[float]:
        vectors = await self.embed_texts([query])
        return vectors[0] if vectors else []

    async def _embed_batch(self, batch: Sequence[str]) -> List[List[float]]:
        async with self._client_lock:
            async for attempt in AsyncRetrying(
                reraise=True,
                stop=stop_after_attempt(self.settings.max_retries),
                wait=wait_fixed(1),
                retry=retry_if_exception_type(OpenAIError),
            ):
                with attempt:
                    response = await self._client.embeddings.create(
                        model=self.settings.model or self._llm_settings.model,
                        input=list(batch),
                    )
                    vectors = [self._normalize(data.embedding) for data in response.data]
                    logger.debug("Embedded %d texts via %s", len(batch), self.settings.model)
                    return vectors

    def _normalize(self, vector: Sequence[float]) -> List[float]:
        if not self.settings.normalize:
            return [float(v) for v in vector]
        norm = math.sqrt(sum(float(x) ** 2 for x in vector)) or 1.0
        return [float(x) / norm for x in vector]
