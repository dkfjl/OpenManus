"""
统一错误处理器
将业务异常映射为标准的 HTTP 错误响应
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from fastapi.exceptions import RequestValidationError

from app.services.prompt_storage import (
    PromptNotFoundError,
    PromptConflictError
)
from app.services.prompt_service import ValidationError
from app.logger import logger


class PromptLibraryException(Exception):
    """提示词库基础异常"""
    def __init__(self, code: str, message: str, status_code: int = 500, details: any = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def create_error_response(code: str, message: str, details: any = None) -> dict:
    """
    创建标准错误响应

    Args:
        code: 错误码
        message: 错误消息
        details: 详细信息（可选）

    Returns:
        错误响应字典
    """
    error_dict = {
        "error": {
            "code": code,
            "message": message
        }
    }

    if details is not None:
        error_dict["error"]["details"] = details

    return error_dict


async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """处理数据验证错误（业务层）"""
    logger.warning(f"Validation error: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=create_error_response(
            code="VALIDATION_ERROR",
            message=str(exc)
        )
    )


async def pydantic_validation_error_handler(request: Request, exc: PydanticValidationError) -> JSONResponse:
    """处理 Pydantic 数据验证错误"""
    logger.warning(f"Pydantic validation error: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=create_error_response(
            code="VALIDATION_ERROR",
            message="请求数据格式错误",
            details=exc.errors()
        )
    )


async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """处理 FastAPI 层的请求体验证错误 (数据进入路由前)

    约定:
    - Body 字段格式错误等返回 400
    - 缺少必填字段 或 非 body 参数(query/path)错误 返回 422
    """
    errors = exc.errors()
    logger.warning(f"Request validation error: {errors}")

    status_code = status.HTTP_400_BAD_REQUEST
    for err in errors:
        loc = err.get("loc", ())
        err_type = err.get("type", "")
        # 缺失字段或非 body 参数 → 422
        if err_type == "missing" or (loc and loc[0] != "body"):
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
            break

    return JSONResponse(
        status_code=status_code,
        content=create_error_response(
            code="VALIDATION_ERROR",
            message="请求数据格式错误",
            details=errors,
        ),
    )


async def prompt_not_found_handler(request: Request, exc: PromptNotFoundError) -> JSONResponse:
    """处理提示词不存在错误"""
    logger.warning(f"Prompt not found: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=create_error_response(
            code="NOT_FOUND",
            message=str(exc)
        )
    )


async def prompt_conflict_handler(request: Request, exc: PromptConflictError) -> JSONResponse:
    """处理版本冲突错误"""
    logger.warning(f"Prompt conflict: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=create_error_response(
            code="CONFLICT",
            message=str(exc)
        )
    )


async def permission_error_handler(request: Request, exc: PermissionError) -> JSONResponse:
    """处理权限错误"""
    logger.warning(f"Permission denied: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content=create_error_response(
            code="FORBIDDEN",
            message=str(exc)
        )
    )


async def prompt_library_exception_handler(request: Request, exc: PromptLibraryException) -> JSONResponse:
    """处理提示词库自定义异常"""
    logger.error(f"Prompt library error [{exc.code}]: {exc.message}")
    return JSONResponse(
        status_code=exc.status_code,
        content=create_error_response(
            code=exc.code,
            message=exc.message,
            details=exc.details
        )
    )


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """处理未捕获的通用异常"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=create_error_response(
            code="INTERNAL_SERVER_ERROR",
            message="服务器内部错误"
        )
    )


def register_error_handlers(app):
    """
    注册所有错误处理器到 FastAPI 应用

    Args:
        app: FastAPI 应用实例
    """
    app.add_exception_handler(ValidationError, validation_error_handler)
    app.add_exception_handler(PydanticValidationError, pydantic_validation_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(PromptNotFoundError, prompt_not_found_handler)
    app.add_exception_handler(PromptConflictError, prompt_conflict_handler)
    app.add_exception_handler(PermissionError, permission_error_handler)
    app.add_exception_handler(PromptLibraryException, prompt_library_exception_handler)
    # 通用异常处理器应该最后注册，作为兜底
    # app.add_exception_handler(Exception, generic_error_handler)  # 可选：根据需要启用

    logger.info("Registered prompt library error handlers")
