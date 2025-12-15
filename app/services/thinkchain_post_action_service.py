from __future__ import annotations

import asyncio
import json
from typing import Dict, List, Optional

import httpx

from app.logger import logger
from app.services.thinkchain_analysis_service import thinkchain_analysis_service
from app.services.thinkchain_log_service import thinkchain_log_service


class ThinkchainPostActionService:
    async def _http_post(self, url: str, data: Dict[str, str]) -> Dict:
        # Import app lazily to avoid circular imports during startup
        from httpx import ASGITransport
        from app.app import app as fastapi_app

        transport = ASGITransport(app=fastapi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://local") as client:
            r = await client.post(url, data=data, timeout=300)
            r.raise_for_status()
            return r.json()

    async def generate_report(
        self,
        *,
        chain_id: str,
        session_id: str,
        topic: str,
        language: str,
        reference_file_uuids: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        try:
            # Prepare digest file and compose file_uuids
            digest_uuid = thinkchain_analysis_service.create_digest_upload_file(
                chain_id=chain_id, session_id=session_id
            )
            # Only pass the digest UUID; it already contains the referenced file context.
            file_uuids = digest_uuid
            payload = {
                "topic": topic or "",
                "language": language or "zh",
                "file_uuids": file_uuids,
                "user_id": "thinkchain_auto",
            }
            res = await self._http_post("/api/docx/generate", data=payload)
            try:
                thinkchain_log_service.log_event(
                    chain_id=chain_id,
                    session_id=session_id,
                    event="post_action_report",
                    data={"request": payload, "result": res},
                )
            except Exception:
                pass
            return res
        except Exception as e:
            logger.error(f"Auto report generation failed: {e}")
            try:
                thinkchain_log_service.log_event(
                    chain_id=chain_id,
                    session_id=session_id,
                    event="post_action_report_failed",
                    data={"error": str(e)},
                )
            except Exception:
                pass
            return None

    async def generate_ppt(
        self,
        *,
        chain_id: str,
        session_id: str,
        topic: str,
        language: str,
        reference_file_uuids: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        try:
            digest_uuid = thinkchain_analysis_service.create_digest_upload_file(
                chain_id=chain_id, session_id=session_id
            )
            # Only pass the digest UUID; it already contains the referenced file context.
            file_uuids = digest_uuid
            payload = {
                "topic": topic or "",
                "language": language or "zh",
                "file_uuids": file_uuids,
            }
            res = await self._http_post("/api/ppt-outline/generate", data=payload)
            try:
                thinkchain_log_service.log_event(
                    chain_id=chain_id,
                    session_id=session_id,
                    event="post_action_ppt",
                    data={"request": payload, "result": res},
                )
            except Exception:
                pass
            return res
        except Exception as e:
            logger.error(f"Auto ppt generation failed: {e}")
            try:
                thinkchain_log_service.log_event(
                    chain_id=chain_id,
                    session_id=session_id,
                    event="post_action_ppt_failed",
                    data={"error": str(e)},
                )
            except Exception:
                pass
            return None

    async def run_post_actions(
        self,
        *,
        task_type: str,
        chain_id: str,
        session_id: str,
        topic: str,
        language: str,
        reference_file_uuids: Optional[List[str]] = None,
    ) -> Dict[str, Optional[Dict]]:
        results: Dict[str, Optional[Dict]] = {}
        if task_type == "report":
            results["report"] = await self.generate_report(
                chain_id=chain_id,
                session_id=session_id,
                topic=topic,
                language=language,
                reference_file_uuids=reference_file_uuids,
            )
        elif task_type == "ppt":
            results["ppt"] = await self.generate_ppt(
                chain_id=chain_id,
                session_id=session_id,
                topic=topic,
                language=language,
                reference_file_uuids=reference_file_uuids,
            )
        else:
            # nothing
            pass
        return results


thinkchain_post_action_service = ThinkchainPostActionService()
