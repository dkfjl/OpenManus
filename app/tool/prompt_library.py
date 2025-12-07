"""
提示词库工具 - 为 Agent 提供提示词管理功能
"""

import os
from typing import Any, Dict, Optional, Literal

from app.tool.base import BaseTool, ToolResult
from app.services.prompt_service import (
    PromptService,
    ValidationError,
)
from app.services.prompt_storage import (
    PromptNotFoundError,
    PromptConflictError
)
from app.logger import logger


class PromptLibraryTool(BaseTool):
    """提示词库工具，支持查询、创建、更新、删除提示词"""

    name: str = "prompt_library"
    description: str = """管理和检索提示词模板。支持以下操作：
1. get_prompt - 获取提示词详情
2. list_personal - 列出个人提示词
3. list_recommended - 列出推荐模板
4. create_personal - 创建个人提示词
5. update_personal - 更新个人提示词
6. delete_personal - 删除个人提示词
"""
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "get_prompt",
                    "list_personal",
                    "list_recommended",
                    "create_personal",
                    "update_personal",
                    "delete_personal"
                ],
                "description": "要执行的操作"
            },
            "prompt_type": {
                "type": "string",
                "enum": ["recommended", "personal"],
                "description": "提示词类型（获取详情时必需）"
            },
            "prompt_id": {
                "type": "string",
                "description": "提示词ID（获取详情、更新、删除时必需）"
            },
            "name": {
                "type": "string",
                "description": "提示词名称（创建、更新、搜索时使用）"
            },
            "prompt": {
                "type": "string",
                "description": "提示词内容（创建、更新时使用）"
            },
            "description": {
                "type": "string",
                "description": "提示词描述（创建、更新时使用）"
            },
            "version": {
                "type": "integer",
                "description": "版本号（更新时用于并发控制）"
            },
            "page": {
                "type": "integer",
                "description": "页码（列表查询时使用，默认1）",
                "default": 1
            },
            "page_size": {
                "type": "integer",
                "description": "每页数量（列表查询时使用，默认20）",
                "default": 20
            }
        },
        "required": ["action"]
    }

    def _get_service(self) -> PromptService:
        """获取 PromptService 实例"""
        return PromptService()

    def _get_owner_id(self) -> str:
        """
        从环境变量或上下文获取当前用户ID

        Returns:
            当前用户的 owner_id
        """
        # 优先从环境变量获取（可由调用方设置）
        owner_id = os.getenv("CURRENT_USER_ID", "default_user")
        return owner_id

    async def execute(self, action: str, **kwargs) -> ToolResult:
        """
        执行工具操作

        Args:
            action: 操作类型
            **kwargs: 其他参数

        Returns:
            ToolResult
        """
        service = self._get_service()

        try:
            # 根据 action 分发到不同的处理方法
            if action == "get_prompt":
                return await self._get_prompt(service, **kwargs)
            elif action == "list_personal":
                return await self._list_personal(service, **kwargs)
            elif action == "list_recommended":
                return await self._list_recommended(service, **kwargs)
            elif action == "create_personal":
                return await self._create_personal(service, **kwargs)
            elif action == "update_personal":
                return await self._update_personal(service, **kwargs)
            elif action == "delete_personal":
                return await self._delete_personal(service, **kwargs)
            else:
                return self.fail_response(f"Unknown action: {action}")

        except ValidationError as e:
            logger.warning(f"Validation error in prompt_library tool: {str(e)}")
            return self.fail_response(f"Validation error: {str(e)}")
        except PromptNotFoundError as e:
            logger.warning(f"Prompt not found: {str(e)}")
            return self.fail_response(f"Prompt not found: {str(e)}")
        except PromptConflictError as e:
            logger.warning(f"Prompt conflict: {str(e)}")
            return self.fail_response(f"Conflict: {str(e)}")
        except PermissionError as e:
            logger.warning(f"Permission denied: {str(e)}")
            return self.fail_response(f"Permission denied: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in prompt_library tool: {str(e)}", exc_info=True)
            return self.fail_response(f"Internal error: {str(e)}")

    async def _get_prompt(
        self,
        service: PromptService,
        prompt_type: Literal["recommended", "personal"],
        prompt_id: str,
        **kwargs
    ) -> ToolResult:
        """获取提示词详情"""
        owner_id = self._get_owner_id() if prompt_type == "personal" else None

        result = service.get_prompt_detail(
            prompt_type=prompt_type,
            prompt_id=prompt_id,
            owner_id=owner_id
        )

        return self.success_response({
            "action": "get_prompt",
            "data": result
        })

    async def _list_personal(
        self,
        service: PromptService,
        name: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        **kwargs
    ) -> ToolResult:
        """列出个人提示词"""
        owner_id = self._get_owner_id()

        result = service.list_prompts(
            prompt_type="personal",
            owner_id=owner_id,
            name_filter=name,
            page=page,
            page_size=page_size
        )

        return self.success_response({
            "action": "list_personal",
            "data": result
        })

    async def _list_recommended(
        self,
        service: PromptService,
        name: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        **kwargs
    ) -> ToolResult:
        """列出推荐模板"""
        result = service.list_prompts(
            prompt_type="recommended",
            name_filter=name,
            page=page,
            page_size=page_size
        )

        return self.success_response({
            "action": "list_recommended",
            "data": result
        })

    async def _create_personal(
        self,
        service: PromptService,
        name: str,
        prompt: str,
        description: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """创建个人提示词"""
        owner_id = self._get_owner_id()

        result = service.create_personal_prompt(
            name=name,
            prompt=prompt,
            owner_id=owner_id,
            description=description
        )

        return self.success_response({
            "action": "create_personal",
            "data": {
                "id": result["id"],
                "name": result["name"],
                "message": "Prompt created successfully"
            }
        })

    async def _update_personal(
        self,
        service: PromptService,
        prompt_id: str,
        name: Optional[str] = None,
        prompt: Optional[str] = None,
        description: Optional[str] = None,
        version: Optional[int] = None,
        **kwargs
    ) -> ToolResult:
        """更新个人提示词"""
        owner_id = self._get_owner_id()

        result = service.update_personal_prompt(
            prompt_id=prompt_id,
            owner_id=owner_id,
            name=name,
            prompt=prompt,
            description=description,
            version=version
        )

        return self.success_response({
            "action": "update_personal",
            "data": {
                "id": result["id"],
                "version": result["version"],
                "message": "Prompt updated successfully"
            }
        })

    async def _delete_personal(
        self,
        service: PromptService,
        prompt_id: str,
        **kwargs
    ) -> ToolResult:
        """删除个人提示词"""
        owner_id = self._get_owner_id()

        service.delete_personal_prompt(
            prompt_id=prompt_id,
            owner_id=owner_id
        )

        return self.success_response({
            "action": "delete_personal",
            "data": {
                "id": prompt_id,
                "message": "Prompt deleted successfully"
            }
        })
