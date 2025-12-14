"""
提示词库 API 路由
提供提示词的 CRUD、列表查询、详情查询等 HTTP 接口
"""

import os
from pathlib import Path as FSPath
from typing import Literal, Optional
from fastapi import APIRouter, Depends, Query, Path, status

from app.api.deps.auth import get_current_user, get_optional_user
from app.schemas.prompt import (
    PromptCreate,
    PromptUpdate,
    PromptCreateResponse,
    PromptUpdateResponse,
    PromptDeleteResponse,
    PromptOverviewResponse,
    PromptDetailResponse,
)
from app.services.prompt_service import PromptService
from app.services.prompt_storage import PromptStorage
from app.services.prompt_sqlite_storage import PromptSQLiteStorage
from app.config import config
from app.logger import logger


# 创建路由器
router = APIRouter(
    prefix="/console/api",
    tags=["prompts"]
)

# 创建服务实例（单例）
_prompt_service = None


def get_prompt_service() -> PromptService:
    """获取提示词服务实例（依赖注入）"""
    global _prompt_service
    if _prompt_service is None:
        # Env first, then config
        backend = os.getenv("PROMPT_STORAGE_BACKEND") or config.prompt_storage.backend
        backend = (backend or "fs").lower()
        sqlite_path_env = os.getenv("PROMPT_SQLITE_PATH") or config.prompt_storage.sqlite_path
        storage_dir = os.getenv("PROMPT_STORAGE_DIR")

        try:
            if backend == "sqlite":
                # 默认放在 db/prompt_library.db（项目根目录下的 db 目录）
                if sqlite_path_env:
                    db_path = FSPath(sqlite_path_env)
                else:
                    db_path = (config.root_path / "db" / "prompt_library.db").resolve()
                storage = PromptSQLiteStorage(db_path=db_path)
                logger = __import__("app.logger", fromlist=["logger"]).logger
                logger.info(f"[PromptRouter] Using SQLite storage at: {storage.paths.db_file}")
                _prompt_service = PromptService(storage=storage)
            else:
                if storage_dir:
                    storage = PromptStorage(storage_dir=FSPath(storage_dir))
                    logger = __import__("app.logger", fromlist=["logger"]).logger
                    logger.info(f"[PromptRouter] Using custom FS storage dir: {storage.storage_dir}")
                    _prompt_service = PromptService(storage=storage)
                else:
                    logger = __import__("app.logger", fromlist=["logger"]).logger
                    logger.info("[PromptRouter] Using default FS storage dir from config")
                    _prompt_service = PromptService()
        except Exception as e:
            logger = __import__("app.logger", fromlist=["logger"]).logger
            logger.warning(f"[PromptRouter] Failed to init requested storage backend: {e}. Falling back to FS")
            _prompt_service = PromptService()
    return _prompt_service


@router.get(
    "/prompt/overview",
    response_model=PromptOverviewResponse,
    summary="获取提示词列表",
    description="支持推荐模板和个人提示词的分页查询，可按名称模糊搜索"
)
async def get_prompt_overview(
    type: Literal["recommended", "personal"] = Query(..., description="提示词类型"),
    name: Optional[str] = Query(None, description="名称模糊搜索（可选）"),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    pageSize: int = Query(20, ge=1, le=100, description="每页数量，最大100"),
    current_user: Optional[str] = Depends(get_optional_user),
    service: PromptService = Depends(get_prompt_service)
):
    """
    获取提示词列表

    - **推荐模板**: 无需认证，所有用户可见
    - **个人提示词**: 需要认证，仅返回当前用户的提示词
    """
    # 个人提示词需要认证
    if type == "personal" and not current_user:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="访问个人提示词需要认证"
        )

    logger.info(f"List prompts: type={type}, user={current_user}, name={name}, page={page}")

    result = service.list_prompts(
        prompt_type=type,
        owner_id=current_user,
        name_filter=name,
        page=page,
        page_size=pageSize
    )

    return PromptOverviewResponse(**result)


@router.get(
    "/prompt/detail",
    response_model=PromptDetailResponse,
    summary="获取提示词详情",
    description="获取推荐模板或个人提示词的完整信息（包含 prompt 内容）"
)
async def get_prompt_detail(
    type: Literal["recommended", "personal"] = Query(..., description="提示词类型"),
    id: str = Query(..., description="提示词ID"),
    current_user: Optional[str] = Depends(get_optional_user),
    service: PromptService = Depends(get_prompt_service)
):
    """
    获取提示词详情

    - **推荐模板**: 无需认证，所有用户可见
    - **个人提示词**: 需要认证，仅能访问自己的提示词
    """
    # 个人提示词需要认证
    if type == "personal" and not current_user:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="访问个人提示词需要认证"
        )

    logger.info(f"Get prompt detail: type={type}, id={id}, user={current_user}")

    prompt_data = service.get_prompt_detail(
        prompt_type=type,
        prompt_id=id,
        owner_id=current_user
    )

    return PromptDetailResponse(data=prompt_data)


@router.post(
    "/prompts",
    response_model=PromptCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建个人提示词",
    description="创建新的个人提示词，需要认证"
)
async def create_prompt(
    request: PromptCreate,
    current_user: str = Depends(get_current_user),
    service: PromptService = Depends(get_prompt_service)
):
    """
    创建个人提示词

    **权限校验**:
    - 请求体中的 ownerId 必须与当前用户一致
    - 同一用户下 name 不能重复

    **字段限制**:
    - name: 最长 20 字符
    - description: 最长 50 字符
    - prompt: 必填
    """
    # 权限校验：ownerId 必须与当前用户一致
    if request.ownerId != current_user:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能创建属于自己的提示词（ownerId 必须与当前用户一致）"
        )

    logger.info(f"Create prompt: name={request.name}, user={current_user}")

    result = service.create_personal_prompt(
        name=request.name,
        prompt=request.prompt,
        owner_id=request.ownerId,
        description=request.description
    )

    return PromptCreateResponse(
        data={"id": result["id"]},
        message="创建成功"
    )


@router.put(
    "/prompts/{id}",
    response_model=PromptUpdateResponse,
    summary="更新个人提示词",
    description="更新已存在的个人提示词，需要认证且仅能更新自己的提示词"
)
async def update_prompt(
    id: str = Path(..., description="提示词ID"),
    request: PromptUpdate = ...,
    current_user: str = Depends(get_current_user),
    service: PromptService = Depends(get_prompt_service)
):
    """
    更新个人提示词

    **权限校验**:
    - 仅能更新自己创建的提示词

    **并发控制**:
    - 可选提供 version 字段进行乐观锁控制
    - 版本不匹配时返回 409 CONFLICT

    **字段限制**:
    - 至少提供一个更新字段
    - name: 最长 20 字符
    - description: 最长 50 字符
    """
    logger.info(f"Update prompt: id={id}, user={current_user}, version={request.version}")

    result = service.update_personal_prompt(
        prompt_id=id,
        owner_id=current_user,
        name=request.name,
        prompt=request.prompt,
        description=request.description,
        version=request.version
    )

    return PromptUpdateResponse(
        data={"id": result["id"]},
        message="更新成功"
    )


@router.delete(
    "/prompts/{id}",
    response_model=PromptDeleteResponse,
    summary="删除个人提示词",
    description="删除个人提示词（硬删除），需要认证且仅能删除自己的提示词"
)
async def delete_prompt(
    id: str = Path(..., description="提示词ID"),
    current_user: str = Depends(get_current_user),
    service: PromptService = Depends(get_prompt_service)
):
    """
    删除个人提示词

    **权限校验**:
    - 仅能删除自己创建的提示词

    **注意**:
    - 当前为硬删除，无法恢复
    - 建议在前端添加二次确认
    """
    logger.info(f"Delete prompt: id={id}, user={current_user}")

    service.delete_personal_prompt(
        prompt_id=id,
        owner_id=current_user
    )

    return PromptDeleteResponse(
        data={"id": id},
        message="删除成功"
    )
