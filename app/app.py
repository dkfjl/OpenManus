import asyncio
from typing import Optional

from fastapi import FastAPI

from app.logger import logger
from app.api.routes.health import router as health_router
from app.api.routes.run import router as run_router
from app.api.routes.report import router as report_router
from app.api.routes.ppt_outline import router as ppt_router
from app.api.routes.files import router as files_router
from app.utils.async_tasks import start_periodic_cleanup


def create_app() -> FastAPI:
    app = FastAPI(title="OpenManus Service", version="1.0.0")

    @app.on_event("startup")
    async def initialize_services():
        # global service lock for /run endpoint
        app.state.service_lock: Optional[asyncio.Lock] = asyncio.Lock()
        cleanup_task = await start_periodic_cleanup()
        if cleanup_task:
            logger.info("Started periodic cleanup task for enhanced outlines")
        logger.info("OpenManus service started, ready to accept requests.")

    # Routers
    app.include_router(health_router)
    app.include_router(run_router)
    app.include_router(report_router)
    app.include_router(ppt_router)
    app.include_router(files_router)
    return app


# Module-level app for uvicorn
app = create_app()

