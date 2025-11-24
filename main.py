import argparse
import asyncio
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.logger import logger
from app.services import generate_structured_document, run_manus_flow

app = FastAPI(title="OpenManus Service", version="1.0.0")
_service_lock: Optional[asyncio.Lock] = None


class RunRequest(BaseModel):
    prompt: str = Field(..., description="任务提示内容")
    allow_interactive_fallback: bool = Field(
        default=False, description="是否在缺少 prompt 时回退到交互输入（HTTP 接口默认关闭）"
    )


class RunResponse(BaseModel):
    status: str
    result: Optional[str] = None


class DocumentRequest(BaseModel):
    topic: str = Field(..., description="文档主题或题目")
    filepath: Optional[str] = Field(
        default=None, description="可选的存储路径（默认存到 workspace 下）"
    )
    language: Optional[str] = Field(
        default=None, description="输出语言，默认从配置 document.default_language 读取"
    )


class DocumentResponse(BaseModel):
    status: str
    filepath: str
    sections: list[str]
    title: str


@app.on_event("startup")
async def initialize_lock():
    global _service_lock
    _service_lock = asyncio.Lock()
    logger.info("OpenManus service started, ready to accept requests.")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/run", response_model=RunResponse)
async def run_manus_endpoint(payload: RunRequest) -> RunResponse:
    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt must not be empty.")

    if _service_lock is None:
        raise HTTPException(
            status_code=503, detail="Service is initializing, please retry."
        )

    if _service_lock.locked():
        raise HTTPException(
            status_code=409, detail="Agent is already processing another request."
        )

    async with _service_lock:
        result = await run_manus_flow(
            prompt=prompt,
            allow_interactive_fallback=payload.allow_interactive_fallback,
        )
        return RunResponse(status="completed", result=result)


@app.post("/documents/structured", response_model=DocumentResponse)
async def structured_document_endpoint(
    payload: DocumentRequest,
) -> DocumentResponse:
    topic = payload.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic must not be empty.")

    if _service_lock is None:
        raise HTTPException(
            status_code=503, detail="Service is initializing, please retry."
        )

    if _service_lock.locked():
        raise HTTPException(
            status_code=409, detail="Agent is already processing another request."
        )

    async with _service_lock:
        doc_info = await generate_structured_document(
            topic=topic,
            filepath=payload.filepath,
            language=payload.language,
        )
        return DocumentResponse(status="completed", **doc_info)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Manus once via CLI or start the HTTP service."
    )
    parser.add_argument("--prompt", type=str, help="Run once with the given prompt.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Server host.")
    parser.add_argument("--port", type=int, default=8000, help="Server port.")
    return parser.parse_args()


def start_server(host: str, port: int):
    logger.info(f"Starting OpenManus HTTP service on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


def main():
    args = parse_args()

    if args.prompt:
        asyncio.run(
            run_manus_flow(prompt=args.prompt, allow_interactive_fallback=False)
        )
    else:
        start_server(args.host, args.port)


if __name__ == "__main__":
    main()
