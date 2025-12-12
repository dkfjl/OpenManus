import asyncio
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.error_handlers import register_error_handlers
from app.api.routes.health import router as health_router
from app.api.routes.prompt import router as prompt_router
from app.logger import logger
from app.utils.async_tasks import start_periodic_cleanup


def create_app() -> FastAPI:
    app = FastAPI(title="OpenManus Service", version="1.0.0")

    # Configure CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allow all origins for development
        allow_credentials=True,
        allow_methods=["*"],  # Allow all HTTP methods
        allow_headers=["*"],  # Allow all headers
    )

    # Register error handlers for prompt library
    register_error_handlers(app)

    @app.on_event("startup")
    async def initialize_services():
        # global service lock for /run endpoint
        app.state.service_lock: Optional[asyncio.Lock] = asyncio.Lock()
        cleanup_task = await start_periodic_cleanup()
        if cleanup_task:
            logger.info("Started periodic cleanup task for enhanced outlines")

        # Initialize report storage database
        try:
            from app.report_storage_db.session import init_db
            await init_db()
            logger.info("Report storage database initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize report storage database: {e}")

        logger.info("OpenManus service started, ready to accept requests.")

    # Routers
    app.include_router(health_router)
    app.include_router(prompt_router)
    try:
        from app.api.routes.knowledge import router as kb_router  # type: ignore

        app.include_router(kb_router)
    except Exception as e:  # pragma: no cover
        logger.warning(f"Optional knowledge router not loaded: {e}")

    # Lazily import optional routers to avoid heavy/development-only deps
    # This keeps the app importable when optional packages are missing
    try:
        from app.api.routes.run import router as run_router  # type: ignore

        app.include_router(run_router)
    except Exception as e:  # pragma: no cover
        logger.warning(f"Optional run router not loaded: {e}")

    try:
        from app.api.routes.report import router as report_router  # type: ignore

        app.include_router(report_router)
    except Exception as e:  # pragma: no cover
        logger.warning(f"Optional report router not loaded: {e}")

    try:
        from app.api.routes.ppt_outline import router as ppt_router  # type: ignore

        app.include_router(ppt_router)
    except Exception as e:  # pragma: no cover
        logger.warning(f"Optional ppt router not loaded: {e}")

    try:
        from app.api.routes.files import router as files_router  # type: ignore

        app.include_router(files_router)
    except Exception as e:  # pragma: no cover
        logger.warning(f"Optional files router not loaded: {e}")

    # Chat data insertion API
    try:
        from app.api.routes.chat import router as chat_router  # type: ignore

        app.include_router(chat_router)
    except Exception as e:  # pragma: no cover
        logger.warning(f"Optional chat router not loaded: {e}")

    # Report file storage API removed; /api/docx/generate now returns presigned URLs directly

    return app


# Module-level app for uvicorn
app = create_app()
