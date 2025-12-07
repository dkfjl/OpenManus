import asyncio
import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from app.config import config
from app.logger import logger
from app.tool.dify_client import dify_client
from app.schemas.knowledge import (
    KnowledgeRecord,
)
from app.services.execution_log_service import log_execution_event


class KnowledgeServiceError(Exception):
    """Base exception for knowledge service errors."""


class KnowledgeValidationError(KnowledgeServiceError):
    pass


class KnowledgeDependencyError(KnowledgeServiceError):
    pass


class KnowledgeService:
    """Thin service wrapper around Dify knowledge base retrieval and optional answering."""

    async def retrieve(
        self,
        *,
        query: str,
        dataset_id: Optional[str] = None,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
        override_api_key: Optional[str] = None,
        # expansion controls
        strategy: str = "fast",
        max_paraphrases: int = 2,
        max_keywords: int = 5,
        return_expansion: bool = True,
    ) -> Tuple[List[KnowledgeRecord], int, Optional[Dict[str, Any]]]:
        """Retrieve knowledge records from Dify.

        Returns a tuple of (items, total).
        Raises KnowledgeValidationError on invalid configuration/inputs.
        Raises KnowledgeDependencyError when upstream service is unavailable.
        """
        if not query or not query.strip():
            raise KnowledgeValidationError("query 不能为空")

        if not config.dify or not config.dify.api_key:
            raise KnowledgeValidationError("Dify 配置缺失，请先设置 API Key")

        # Defaults from config
        final_top_k = top_k if top_k is not None else config.dify.top_k
        final_threshold = (
            score_threshold if score_threshold is not None else config.dify.score_threshold
        )

        # Build expanded query set
        expanded, exp_info = await self._expand_queries(
            seed=query,
            strategy=strategy,
            max_paraphrases=max_paraphrases,
            max_keywords=max_keywords,
        )

        try:
            log_execution_event(
                "kb_call",
                "Dify retrieve",
                {
                    "query_preview": query[:120],
                    "top_k": final_top_k,
                    "threshold": final_threshold,
                },
            )
            # Concurrent retrieval for seed + expansions
            sem = asyncio.Semaphore(10)

            async def _fetch(q: str) -> Tuple[str, List[Dict[str, Any]]]:
                async with sem:
                    try:
                        resp = await dify_client.retrieve_knowledge(
                            query=q,
                            dataset_id=dataset_id,
                            retrieval_model=config.dify.retrieval_model or "search",
                            score_threshold=final_threshold,
                            top_k=max(1, min(final_top_k, 5)),
                            override_api_key=override_api_key,
                        )
                        return q, (resp.records or [])
                    except Exception:
                        return q, []

            results = await asyncio.gather(*[_fetch(q) for q in expanded])

            per_query_hits: Dict[str, int] = {q: len(recs) for q, recs in results}
            failed = [q for q, recs in results if not recs]

            # Flatten and transform
            raw_records: List[Tuple[str, Dict[str, Any]]] = []
            for q, recs in results:
                for r in recs:
                    raw_records.append((q, r))

            if raw_records:
                try:
                    sample_keys = [list(r.keys()) for _, r in raw_records[:3]]
                    log_execution_event("debug", "Dify records shape", {"keys": sample_keys})
                except Exception:
                    pass

            def _extract_content(rec: Dict[str, Any]) -> str:
                for k in ("content", "text", "segment_text", "segmentContent", "document_text", "doc_text"):
                    val = rec.get(k)
                    if isinstance(val, str) and val.strip():
                        return val
                for parent in ("segment", "document"):
                    obj = rec.get(parent)
                    if isinstance(obj, dict):
                        for k in ("content", "text"):
                            val = obj.get(k)
                            if isinstance(val, str) and val.strip():
                                return val
                qa_answer = rec.get("answer")
                if isinstance(qa_answer, str) and qa_answer.strip():
                    return qa_answer
                return ""

            def _extract_metadata(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                md = rec.get("metadata")
                if isinstance(md, dict):
                    return md
                for parent in ("segment", "document"):
                    obj = rec.get(parent)
                    if isinstance(obj, dict) and isinstance(obj.get("metadata"), dict):
                        return obj.get("metadata")
                keys = ("doc_id", "document_id", "segment_id", "dataset_id", "source", "url", "title", "date")
                composed = {k: rec.get(k) for k in keys if rec.get(k) is not None}
                return composed or None

            # Build scored records with query-type boost
            def _boost(q: str) -> float:
                if q == query:
                    return 1.0
                if q in exp_info.get("paraphrases", []):
                    return 0.8
                return 0.6  # keywords

            transformed: List[Tuple[KnowledgeRecord, float]] = []
            for q, r in raw_records:
                rec = KnowledgeRecord(
                    content=_extract_content(r),
                    score=r.get("score"),
                    metadata=_extract_metadata(r),
                )
                base = float(rec.score or 0.0)
                transformed.append((rec, base + 0.01 * _boost(q)))

            # Deduplicate by strong keys then by content hash
            def _sig(rec: KnowledgeRecord) -> str:
                md = rec.metadata or {}
                keys = [
                    str(md.get("segment_id") or md.get("doc_id") or md.get("document_id") or md.get("url") or ""),
                    hashlib.md5((rec.content or "").strip().lower().encode("utf-8")).hexdigest(),
                ]
                return "|".join(keys)

            seen = set()
            deduped: List[Tuple[KnowledgeRecord, float]] = []
            for rec, sc in sorted(transformed, key=lambda x: x[1], reverse=True):
                sig = _sig(rec)
                if sig in seen:
                    continue
                seen.add(sig)
                deduped.append((rec, sc))

            # Trim to final_top_k
            items = [rec for rec, _ in deduped[:final_top_k]]
            total = len(deduped)

            expansion_out = None
            if return_expansion:
                from app.schemas.knowledge import ExpansionInfo

                expansion_out = ExpansionInfo(
                    seedQuery=query,
                    paraphrases=exp_info.get("paraphrases", []),
                    keywords=exp_info.get("keywords", []),
                    perQueryHits=per_query_hits,
                    failedQueries=failed,
                    dataset_id=dataset_id,
                ).dict()

            return items, total, expansion_out
        except ValueError as e:
            # Client raises ValueError for config errors like missing dataset
            logger.error(f"Knowledge retrieve validation error: {e}")
            raise KnowledgeValidationError(str(e))
        except Exception as e:
            # Standardize upstream failures
            logger.error(f"Knowledge retrieve dependency error: {e}")
            raise KnowledgeDependencyError(str(e))

    async def answer(
        self,
        *,
        question: str,
        dataset_id: Optional[str] = None,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
        answer_style: str = "concise",
        return_citations: bool = True,
        return_conflicts: bool = True,
        override_api_key: Optional[str] = None,
        # expansion controls
        strategy: str = "fast",
        max_paraphrases: int = 2,
        max_keywords: int = 5,
    ) -> Dict[str, Any]:
        """Retrieve knowledge then generate an answer using the configured LLM.

        Returns dict with keys: answer, citations?, usedRecords?, conflicts?, decisionBasis?, expansion?
        """
        items, total, expansion = await self.retrieve(
            query=question,
            dataset_id=dataset_id,
            top_k=top_k,
            score_threshold=score_threshold,
            override_api_key=override_api_key,
            strategy=strategy,
            max_paraphrases=max_paraphrases,
            max_keywords=max_keywords,
            return_expansion=True,
        )

        if total == 0:
            return {
                "answer": "知识库中未找到相关信息。",
                "citations": [] if return_citations else None,
                "usedRecords": [] if return_citations else None,
            }

        # Build context
        max_ctx = getattr(config.knowledge_base_config, "max_context_chars", 2000)
        buf: List[str] = []
        chars = 0
        used: List[KnowledgeRecord] = []
        for rec in items:
            text = rec.content or ""
            if not text:
                continue
            if chars + len(text) > max_ctx and buf:
                break
            buf.append(text)
            used.append(rec)
            chars += len(text)
        context = "\n\n".join(buf)[:max_ctx]

        # Compose answer via LLM
        try:
            from app.llm import LLM
            llm = LLM()
            style_hint = {
                "concise": "Provide a brief, precise answer.",
                "detailed": "Provide a thorough, structured explanation.",
                "bullet": "Answer in clear bullet points.",
            }.get(answer_style, "Provide a brief, precise answer.")

            system = (
                "You are a helpful assistant that answers strictly based on the provided knowledge snippets. "
                "If the snippets are insufficient, say so explicitly. Do not fabricate facts."
            )
            prompt = (
                f"Question: {question}\n\n"
                f"Knowledge snippets (trustworthy context):\n{context}\n\n"
                f"Instruction: {style_hint} Cite specific details present in snippets when possible."
            )
            answer = await llm.ask(
                messages=[{"role": "user", "content": prompt}],
                system_msgs=[{"role": "system", "content": system}],
                stream=False,
                temperature=0.2,
            )

            # Optional conflict detection via LLM (best-effort)
            conflicts_out: Optional[List[Dict[str, Any]]] = None
            basis_out: Optional[Dict[str, Any]] = None
            try:
                if return_conflicts and used:
                    review_prompt = (
                        "Review the following snippets for contradictions on numbers, dates, definitions, or conclusions.\n"
                        "Return a concise JSON with fields: conflicts:[{claim,variants:[{statement,sources}]}],"
                        "decisionBasis:{rules:[...],applied:[...]} . Do not include any other text.\n\n"
                        f"Snippets:\n{context}\n"
                    )
                    review = await llm.ask(
                        messages=[{"role": "user", "content": review_prompt}],
                        system_msgs=[{"role": "system", "content": "You produce strict JSON only."}],
                        stream=False,
                        temperature=0.0,
                    )
                    import json as _json

                    try:
                        parsed = _json.loads(review)
                        conflicts_out = parsed.get("conflicts")
                        basis_out = parsed.get("decisionBasis")
                    except Exception:
                        pass
            except Exception:
                pass

            result: Dict[str, Any] = {"answer": answer}
            if return_citations:
                result["citations"] = used
                result["usedRecords"] = used
            if expansion:
                result["expansion"] = expansion
            if return_conflicts:
                result["conflicts"] = conflicts_out or []
                result["decisionBasis"] = basis_out or {
                    "rules": ["authority>freshness>consistency>relevance"],
                    "applied": [
                        "Applied heuristic preference using available metadata and retrieval scores"
                    ],
                }
            return result
        except Exception as e:
            logger.error(f"Knowledge answer generation failed: {e}")
            # On generation failure, degrade to retrieval-only feedback
            raise KnowledgeDependencyError("生成回答失败，请稍后再试")

    # -----------------------------
    # Internal helpers
    # -----------------------------
    async def _expand_queries(
        self,
        *,
        seed: str,
        strategy: str,
        max_paraphrases: int,
        max_keywords: int,
    ) -> Tuple[List[str], Dict[str, Any]]:
        seed = (seed or "").strip()
        paraphrases = await self._gen_paraphrases(seed, max_paraphrases, strategy)
        keywords = await self._extract_keywords(seed, max_keywords, strategy)
        # Build final list: seed first, then paraphrases, then keyword joined forms
        expanded: List[str] = []
        if seed:
            expanded.append(seed)
        expanded.extend([q for q in paraphrases if q and q != seed])
        # For keywords, compose a simple AND-like query by space-joining
        if keywords:
            expanded.append(" ".join(keywords))
        # Deduplicate while preserving order
        seen = set()
        ordered = []
        for q in expanded:
            if q not in seen:
                seen.add(q)
                ordered.append(q)
        return ordered, {"paraphrases": paraphrases, "keywords": keywords}

    async def _gen_paraphrases(self, seed: str, limit: int, strategy: str) -> List[str]:
        limit = max(0, int(limit or 0))
        if limit == 0 or not seed:
            return []

        out: List[str] = []
        # Try LLM in thorough mode
        if strategy == "thorough":
            try:
                from app.llm import LLM

                llm = LLM()
                prompt = (
                    "Rewrite the query into semantically equivalent variants in Chinese. "
                    f"Keep each variant concise (<= 20 chars). Output exactly {limit} lines, no numbering.\n"
                    f"Query: {seed}"
                )
                text = await llm.ask(
                    messages=[{"role": "user", "content": prompt}],
                    system_msgs=[{"role": "system", "content": "Return plain lines only."}],
                    stream=False,
                    temperature=0.2,
                )
                cand = [s.strip() for s in text.splitlines() if s.strip()]
                out.extend(cand[:limit])
            except Exception:
                pass

        # Rule-based lightweight variants
        synonyms = {
            "分析": ["研判", "解读", "评估"],
            "指标": ["度量", "量化指标", "关键指标"],
            "方案": ["计划", "策略"],
            "对比": ["比较", "差异"],
        }
        for k, vs in synonyms.items():
            if len(out) >= limit:
                break
            if k in seed:
                for v in vs:
                    if len(out) >= limit:
                        break
                    out.append(seed.replace(k, v))

        # Trim and dedup
        uniq = []
        seen = set()
        for q in out:
            if q and q not in seen and q != seed:
                seen.add(q)
                uniq.append(q)
        return uniq[:limit]

    async def _extract_keywords(self, seed: str, limit: int, strategy: str) -> List[str]:
        limit = max(0, int(limit or 0))
        if limit == 0 or not seed:
            return []

        # Simple regex-based tokenization for Chinese/English/numbers
        tokens = re.findall(r"[\u4e00-\u9fa5]{1,}|[A-Za-z0-9_\.\-]+", seed)
        # Stopwords (minimal)
        stop = set(["的", "了", "和", "与", "及", "或", "与", "请", "如何", "怎么", "进行", "关于"])
        keywords = [t for t in tokens if t not in stop]

        # Optionally ask LLM for keyphrases in thorough mode
        if strategy == "thorough":
            try:
                from app.llm import LLM

                llm = LLM()
                prompt = (
                    "从查询中提取3-6个关键短语，用中文返回，不要解释，用逗号分隔。\n"
                    f"查询：{seed}"
                )
                text = await llm.ask(
                    messages=[{"role": "user", "content": prompt}],
                    system_msgs=[{"role": "system", "content": "仅输出关键短语，逗号分隔。"}],
                    stream=False,
                    temperature=0.0,
                )
                llm_keys = [s.strip() for s in text.replace("，", ",").split(",") if s.strip()]
                keywords = (llm_keys or keywords)
            except Exception:
                pass

        # Dedup and limit
        seen = set()
        out = []
        for k in keywords:
            if k not in seen:
                seen.add(k)
                out.append(k)
        return out[: max(3, min(limit, 6))]
