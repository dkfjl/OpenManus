from typing import Optional

from fastapi import APIRouter, HTTPException, Depends

from app.api.deps.auth import get_optional_user
from app.logger import logger
from app.schemas.knowledge import (
    KnowledgeAnswerRequest,
    KnowledgeAnswerResponse,
    KnowledgeRecord,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.services.execution_log_service import (
    end_execution_log,
    log_execution_event,
    start_execution_log,
)
from app.services.knowledge_service import (
    KnowledgeDependencyError,
    KnowledgeService,
    KnowledgeValidationError,
)


router = APIRouter()


@router.post("/api/kb/retrieve", response_model=KnowledgeSearchResponse)
async def kb_retrieve(
    body: KnowledgeSearchRequest,
    user_id: Optional[str] = Depends(get_optional_user),
):
    service = KnowledgeService()
    session = start_execution_log(
        flow_type="kb_search",
        metadata={"entrypoint": "http.kb.retrieve", "user_id": user_id},
    )
    closed = False
    try:
        log_execution_event(
            "http_request",
            "Received /api/kb/retrieve",
            {"query_preview": body.query[:120], "user": user_id},
        )
        items, total, expansion = await service.retrieve(
            query=body.query,
            dataset_id=body.dataset_id,
            top_k=body.topK,
            score_threshold=body.scoreThreshold,
            override_api_key=body.api_key,
            strategy=body.strategy or "fast",
            max_paraphrases=(body.maxParaphrases or 2),
            max_keywords=(body.maxKeywords or 5),
            return_expansion=(body.returnExpansion if body.returnExpansion is not None else True),
        )
        resp = KnowledgeSearchResponse(items=items, total=total, query=body.query, expansion=expansion)
        end_execution_log(status="completed", details={"total": total})
        closed = True
        return resp
    except KnowledgeValidationError as e:
        log_execution_event("error", "kb_retrieve validation error", {"error": str(e)})
        end_execution_log(status="failed", details={"error": str(e)})
        closed = True
        raise HTTPException(status_code=400, detail=str(e))
    except KnowledgeDependencyError as e:
        log_execution_event("error", "kb_retrieve dependency error", {"error": str(e)})
        end_execution_log(status="failed", details={"error": str(e)})
        closed = True
        raise HTTPException(status_code=503, detail="知识库服务暂时不可用")
    except Exception as e:
        logger.error(f"/api/kb/retrieve unexpected error: {e}")
        if not closed:
            end_execution_log(status="failed", details={"error": str(e)})
            closed = True
        raise
    finally:
        if not closed:
            session.deactivate()


@router.post("/api/kb/answer", response_model=KnowledgeAnswerResponse)
async def kb_answer(
    body: KnowledgeAnswerRequest,
    user_id: Optional[str] = Depends(get_optional_user),
):
    service = KnowledgeService()
    session = start_execution_log(
        flow_type="kb_answer",
        metadata={"entrypoint": "http.kb.answer", "user_id": user_id},
    )
    closed = False
    try:
        log_execution_event(
            "http_request",
            "Received /api/kb/answer",
            {"query_preview": body.query[:120], "user": user_id},
        )

        data = await service.answer(
            question=body.query,
            dataset_id=body.dataset_id,
            top_k=body.topK,
            score_threshold=body.scoreThreshold,
            answer_style=body.answerStyle or "concise",
            return_citations=body.returnCitations if body.returnCitations is not None else True,
            return_conflicts=body.returnConflicts if body.returnConflicts is not None else True,
            override_api_key=body.api_key,
            strategy=body.strategy or "fast",
            max_paraphrases=(body.maxParaphrases or 2),
            max_keywords=(body.maxKeywords or 5),
        )

        resp = KnowledgeAnswerResponse(
            answer=data.get("answer", ""),
            citations=data.get("citations"),
            usedRecords=data.get("usedRecords"),
            conflicts=data.get("conflicts"),
            decisionBasis=data.get("decisionBasis"),
            expansion=data.get("expansion"),
        )
        end_execution_log(status="completed", details={"citations": len(resp.citations or [])})
        closed = True
        return resp
    except KnowledgeValidationError as e:
        log_execution_event("error", "kb_answer validation error", {"error": str(e)})
        end_execution_log(status="failed", details={"error": str(e)})
        closed = True
        raise HTTPException(status_code=400, detail=str(e))
    except KnowledgeDependencyError as e:
        log_execution_event("error", "kb_answer dependency error", {"error": str(e)})
        end_execution_log(status="failed", details={"error": str(e)})
        closed = True
        raise HTTPException(status_code=503, detail="知识库服务暂时不可用")
    except Exception as e:
        logger.error(f"/api/kb/answer unexpected error: {e}")
        if not closed:
            end_execution_log(status="failed", details={"error": str(e)})
            closed = True
        raise
    finally:
        if not closed:
            session.deactivate()
