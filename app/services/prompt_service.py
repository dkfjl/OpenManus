"""
提示词库业务逻辑服务
负责数据校验、权限控制、变量替换等业务逻辑
"""

import time
from functools import wraps
from typing import Dict, Any, Optional, Literal, Callable
from string import Formatter

from app.services.prompt_storage import (
    PromptStorage,
    PromptNotFoundError,
    PromptConflictError
)
from app.logger import logger


def log_performance(operation: str):
    """性能监控装饰器，记录操作耗时"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            start_time = time.time()
            success = False
            error_msg = None

            try:
                result = func(self, *args, **kwargs)
                success = True
                return result
            except Exception as e:
                error_msg = str(e)
                raise
            finally:
                latency_ms = (time.time() - start_time) * 1000

                # 记录性能日志
                log_data = {
                    "operation": operation,
                    "latency_ms": round(latency_ms, 2),
                    "success": success
                }

                if error_msg:
                    log_data["error"] = error_msg

                # 根据耗时级别使用不同的日志级别
                if latency_ms > 500:
                    logger.warning(f"[PromptService] Slow operation: {operation}", extra=log_data)
                elif success:
                    logger.debug(f"[PromptService] {operation} completed", extra=log_data)

        return wrapper
    return decorator


class ValidationError(Exception):
    """数据验证错误"""
    pass


class SafeDict(dict):
    """安全字典，用于变量替换时保留缺失变量的占位符"""
    def __missing__(self, key):
        return f"{{{key}}}"


class PromptService:
    """提示词业务逻辑服务"""

    # 验证规则
    MAX_NAME_LENGTH = 20
    MAX_DESCRIPTION_LENGTH = 50
    MAX_PAGE_SIZE = 100

    def __init__(self, storage: Optional[PromptStorage] = None):
        """
        初始化服务

        Args:
            storage: 存储层实例，如果为None则创建默认实例
        """
        self.storage = storage or PromptStorage()

    def _validate_name(self, name: str) -> None:
        """验证名称"""
        if not name or not name.strip():
            raise ValidationError("Name is required and cannot be empty")

        if len(name) > self.MAX_NAME_LENGTH:
            raise ValidationError(
                f"Name length exceeds maximum {self.MAX_NAME_LENGTH} characters"
            )

    def _validate_description(self, description: Optional[str]) -> None:
        """验证描述"""
        if description and len(description) > self.MAX_DESCRIPTION_LENGTH:
            raise ValidationError(
                f"Description length exceeds maximum {self.MAX_DESCRIPTION_LENGTH} characters"
            )

    def _validate_prompt(self, prompt: str) -> None:
        """验证提示词内容"""
        if not prompt or not prompt.strip():
            raise ValidationError("Prompt content is required and cannot be empty")

    def _validate_page_params(self, page: int, page_size: int) -> None:
        """验证分页参数"""
        if page < 1:
            raise ValidationError("Page must be >= 1")

        if page_size < 1:
            raise ValidationError("Page size must be >= 1")

        if page_size > self.MAX_PAGE_SIZE:
            raise ValidationError(f"Page size exceeds maximum {self.MAX_PAGE_SIZE}")

    @log_performance("create_personal_prompt")
    def create_personal_prompt(
        self,
        name: str,
        prompt: str,
        owner_id: str,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建个人提示词

        Args:
            name: 提示词名称
            prompt: 提示词内容
            owner_id: 所有者ID
            description: 描述（可选）

        Returns:
            创建的提示词信息

        Raises:
            ValidationError: 验证失败
        """
        # 数据验证
        self._validate_name(name)
        self._validate_description(description)
        self._validate_prompt(prompt)

        if not owner_id or not owner_id.strip():
            raise ValidationError("Owner ID is required")

        # 检查名称唯一性
        if not self.storage.check_name_uniqueness(owner_id, name):
            raise ValidationError(f"Prompt name '{name}' already exists for this owner")

        # 创建
        try:
            result = self.storage.create(
                name=name.strip(),
                prompt=prompt.strip(),
                owner_id=owner_id,
                description=description.strip() if description else None
            )
            logger.info(f"Created personal prompt: {result['id']}")
            return result
        except Exception as e:
            logger.error(f"Failed to create prompt: {str(e)}")
            raise

    @log_performance("update_personal_prompt")
    def update_personal_prompt(
        self,
        prompt_id: str,
        owner_id: str,
        name: Optional[str] = None,
        prompt: Optional[str] = None,
        description: Optional[str] = None,
        version: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        更新个人提示词

        Args:
            prompt_id: 提示词ID
            owner_id: 所有者ID
            name: 新名称（可选）
            prompt: 新内容（可选）
            description: 新描述（可选）
            version: 版本号（用于并发控制）

        Returns:
            更新后的提示词信息

        Raises:
            ValidationError: 验证失败
            PromptNotFoundError: 提示词不存在
            PromptConflictError: 版本冲突
            PermissionError: 无权限
        """
        # 至少提供一个更新字段
        if name is None and prompt is None and description is None:
            raise ValidationError("At least one field must be provided for update")

        # 数据验证
        if name is not None:
            self._validate_name(name)
            # 检查名称唯一性（排除当前提示词）
            if not self.storage.check_name_uniqueness(owner_id, name, exclude_id=prompt_id):
                raise ValidationError(f"Prompt name '{name}' already exists for this owner")

        if description is not None:
            self._validate_description(description)

        if prompt is not None:
            self._validate_prompt(prompt)

        # 更新
        try:
            result = self.storage.update(
                prompt_id=prompt_id,
                owner_id=owner_id,
                name=name.strip() if name else None,
                prompt=prompt.strip() if prompt else None,
                description=description.strip() if description else None,
                version=version
            )
            logger.info(f"Updated personal prompt: {prompt_id}")
            return result
        except (PromptNotFoundError, PromptConflictError, PermissionError):
            raise
        except Exception as e:
            logger.error(f"Failed to update prompt: {str(e)}")
            raise

    @log_performance("delete_personal_prompt")
    def delete_personal_prompt(self, prompt_id: str, owner_id: str) -> bool:
        """
        删除个人提示词

        Args:
            prompt_id: 提示词ID
            owner_id: 所有者ID

        Returns:
            是否删除成功

        Raises:
            PromptNotFoundError: 提示词不存在
            PermissionError: 无权限
        """
        try:
            result = self.storage.delete(prompt_id, owner_id)
            logger.info(f"Deleted personal prompt: {prompt_id}")
            return result
        except (PromptNotFoundError, PermissionError):
            raise
        except Exception as e:
            logger.error(f"Failed to delete prompt: {str(e)}")
            raise

    @log_performance("get_prompt_detail")
    def get_prompt_detail(
        self,
        prompt_type: Literal["recommended", "personal"],
        prompt_id: str,
        owner_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取提示词详情

        Args:
            prompt_type: 提示词类型
            prompt_id: 提示词ID
            owner_id: 所有者ID（个人提示词必需）

        Returns:
            提示词完整信息

        Raises:
            ValidationError: 验证失败
            PromptNotFoundError: 提示词不存在
            PermissionError: 无权限
        """
        if prompt_type == "recommended":
            try:
                return self.storage.get_recommended(prompt_id)
            except PromptNotFoundError:
                raise
            except Exception as e:
                logger.error(f"Failed to get recommended prompt: {str(e)}")
                raise

        elif prompt_type == "personal":
            if not owner_id:
                raise ValidationError("Owner ID is required for personal prompts")

            try:
                return self.storage.get(prompt_id, owner_id)
            except (PromptNotFoundError, PermissionError):
                raise
            except Exception as e:
                logger.error(f"Failed to get personal prompt: {str(e)}")
                raise
        else:
            raise ValidationError(f"Invalid prompt type: {prompt_type}")

    @log_performance("list_prompts")
    def list_prompts(
        self,
        prompt_type: Literal["recommended", "personal"],
        owner_id: Optional[str] = None,
        name_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """
        列出提示词（分页 + 搜索）

        Args:
            prompt_type: 提示词类型
            owner_id: 所有者ID（个人提示词必需）
            name_filter: 名称模糊搜索（可选）
            page: 页码（从1开始）
            page_size: 每页数量

        Returns:
            分页结果 { items, total, page, pageSize }

        Raises:
            ValidationError: 验证失败
        """
        # 验证分页参数
        self._validate_page_params(page, page_size)

        if prompt_type == "recommended":
            try:
                return self.storage.list_recommended(
                    name_filter=name_filter,
                    page=page,
                    page_size=page_size
                )
            except Exception as e:
                logger.error(f"Failed to list recommended prompts: {str(e)}")
                raise

        elif prompt_type == "personal":
            if not owner_id:
                raise ValidationError("Owner ID is required for personal prompts")

            try:
                return self.storage.list_personal(
                    owner_id=owner_id,
                    name_filter=name_filter,
                    page=page,
                    page_size=page_size
                )
            except Exception as e:
                logger.error(f"Failed to list personal prompts: {str(e)}")
                raise
        else:
            raise ValidationError(f"Invalid prompt type: {prompt_type}")

    def replace_variables(
        self,
        template: str,
        variables: Optional[Dict[str, str]] = None
    ) -> str:
        """
        替换提示词中的变量占位符

        使用 {var} 语法，缺失的变量保留原样

        Args:
            template: 模板字符串
            variables: 变量字典

        Returns:
            替换后的字符串

        Examples:
            >>> service.replace_variables("你是{role}", {"role": "助手"})
            "你是助手"

            >>> service.replace_variables("你是{role},目标{goal}", {"role": "助手"})
            "你是助手,目标{goal}"
        """
        if not variables:
            return template

        try:
            return template.format_map(SafeDict(variables))
        except Exception as e:
            logger.warning(f"Failed to replace variables: {str(e)}")
            return template

    def get_and_merge_prompt(
        self,
        prompt_type: Literal["recommended", "personal"],
        prompt_id: str,
        owner_id: Optional[str] = None,
        merge_vars: Optional[Dict[str, str]] = None,
        additional_prompt: Optional[str] = None
    ) -> str:
        """
        获取提示词并执行变量替换和合并

        Args:
            prompt_type: 提示词类型
            prompt_id: 提示词ID
            owner_id: 所有者ID（个人提示词必需）
            merge_vars: 变量字典
            additional_prompt: 附加提示词（会拼接在模板后）

        Returns:
            最终的提示词字符串

        Raises:
            ValidationError: 验证失败
            PromptNotFoundError: 提示词不存在
            PermissionError: 无权限
        """
        # 获取提示词详情
        prompt_data = self.get_prompt_detail(prompt_type, prompt_id, owner_id)
        template_prompt = prompt_data["prompt"]

        # 变量替换
        if merge_vars:
            template_prompt = self.replace_variables(template_prompt, merge_vars)

        # 合并附加提示词
        if additional_prompt:
            final_prompt = f"{template_prompt}\n\n{additional_prompt}"
        else:
            final_prompt = template_prompt

        return final_prompt
