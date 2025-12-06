"""
Lightweight service package initializer.

This file intentionally avoids importing submodules at import time to
prevent circular import issues. Instead, it exposes a small lazy loader
so that attributes can still be imported from `app.services` while
deferring the actual submodule imports until first access.
"""

from importlib import import_module
from typing import Dict, Tuple

# Public API re-exports (lazy)
__all__ = [
    "run_manus_flow",
    "run_manus_flow_sync",
    "create_structured_document_task",
    "get_structured_document_task",
    "DocumentParserService",
    "DocumentSummaryService",
    "generate_report_from_steps",
]

_ATTR_MAP: Dict[str, Tuple[str, str]] = {
    # manus runner
    "run_manus_flow": ("app.services.manus_runner", "run_manus_flow"),
    "run_manus_flow_sync": ("app.services.manus_runner", "run_manus_flow_sync"),
    # structured document service
    "create_structured_document_task": (
        "app.services.document_service",
        "create_structured_document_task",
    ),
    "get_structured_document_task": (
        "app.services.document_service",
        "get_structured_document_task",
    ),
    # document helpers
    "DocumentParserService": (
        "app.services.document_parser_service",
        "DocumentParserService",
    ),
    "DocumentSummaryService": (
        "app.services.document_summary_service",
        "DocumentSummaryService",
    ),
    # report generation
    "generate_report_from_steps": (
        "app.services.report_generation_service",
        "generate_report_from_steps",
    ),
}


def __getattr__(name: str):
    if name not in _ATTR_MAP:
        raise AttributeError(f"module {__name__!s} has no attribute {name!s}")
    module_path, attr_name = _ATTR_MAP[name]
    module = import_module(module_path)
    return getattr(module, attr_name)


def __dir__():  # pragma: no cover - tiny convenience
    return sorted(list(globals().keys()) + __all__)
