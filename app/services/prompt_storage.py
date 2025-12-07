"""
提示词库存储管理服务
负责提示词的文件存储、索引管理、并发控制等底层操作
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from functools import lru_cache
import fcntl

from app.config import config
from app.logger import logger


class PromptNotFoundError(Exception):
    """提示词不存在"""
    pass


class PromptConflictError(Exception):
    """提示词版本冲突"""
    pass


class PromptStorage:
    """提示词存储管理服务"""

    def __init__(self, storage_dir: Optional[Path] = None):
        """
        初始化存储服务

        Args:
            storage_dir: 存储目录路径，如果为None则使用默认路径
        """
        if storage_dir is None:
            self.storage_dir = config.workspace_root / "prompt_library"
        else:
            self.storage_dir = storage_dir

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.prompts_dir = self.storage_dir / "prompts"
        self.prompts_dir.mkdir(parents=True, exist_ok=True)

        self.index_file = self.storage_dir / "index.json"
        self.lock_file = self.storage_dir / ".index.lock"

        # 确保索引文件存在
        self._ensure_index_file()

        # 推荐模板路径
        self.recommended_file = Path("assets/prompts/recommended.json")

    def _ensure_index_file(self) -> None:
        """确保索引文件存在"""
        if not self.index_file.exists():
            self._save_index({"prompts": {}, "owners": {}})

    def _load_index(self) -> Dict[str, Any]:
        """加载索引文件（带文件锁）"""
        try:
            with open(self.lock_file, 'a') as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_SH)  # 共享锁（读）
                try:
                    with open(self.index_file, "r", encoding="utf-8") as f:
                        return json.load(f)
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except FileNotFoundError:
            logger.warning("Index file not found, creating new one")
            return {"prompts": {}, "owners": {}}
        except Exception as e:
            logger.error(f"Failed to load index file: {str(e)}")
            return {"prompts": {}, "owners": {}}

    def _save_index(self, index_data: Dict[str, Any]) -> bool:
        """保存索引文件（原子写入 + 排他锁）"""
        try:
            with open(self.lock_file, 'a') as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)  # 排他锁（写）
                try:
                    # 写入临时文件
                    temp_file = self.index_file.with_suffix('.tmp')
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        json.dump(index_data, f, ensure_ascii=False, indent=2)

                    # 原子替换
                    os.replace(temp_file, self.index_file)
                    return True
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            logger.error(f"Failed to save index file: {str(e)}")
            return False

    @lru_cache(maxsize=1)
    def _load_recommended_prompts(self) -> List[Dict[str, Any]]:
        """加载推荐模板（缓存）"""
        try:
            if not self.recommended_file.exists():
                logger.warning("Recommended prompts file not found")
                return []

            with open(self.recommended_file, 'r', encoding='utf-8') as f:
                prompts = json.load(f)
                logger.info(f"Loaded {len(prompts)} recommended prompts")
                return prompts
        except Exception as e:
            logger.error(f"Failed to load recommended prompts: {str(e)}")
            return []

    def _load_prompt_content(self, prompt_id: str) -> Optional[str]:
        """加载提示词内容文件"""
        content_file = self.prompts_dir / f"{prompt_id}.json"
        try:
            with open(content_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("prompt")
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Failed to load prompt content {prompt_id}: {str(e)}")
            return None

    def _save_prompt_content(self, prompt_id: str, prompt: str) -> bool:
        """保存提示词内容文件"""
        content_file = self.prompts_dir / f"{prompt_id}.json"
        try:
            with open(content_file, 'w', encoding='utf-8') as f:
                json.dump({"prompt": prompt}, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save prompt content {prompt_id}: {str(e)}")
            return False

    def _delete_prompt_content(self, prompt_id: str) -> bool:
        """删除提示词内容文件"""
        content_file = self.prompts_dir / f"{prompt_id}.json"
        try:
            if content_file.exists():
                content_file.unlink()
            return True
        except Exception as e:
            logger.error(f"Failed to delete prompt content {prompt_id}: {str(e)}")
            return False

    def create(
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
        """
        prompt_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()

        # 构建提示词元数据
        prompt_meta = {
            "id": prompt_id,
            "name": name,
            "description": description,
            "ownerId": owner_id,
            "file": f"prompts/{prompt_id}.json",
            "version": 1,
            "createdAt": created_at,
            "updatedAt": created_at
        }

        # 保存内容文件
        if not self._save_prompt_content(prompt_id, prompt):
            raise Exception("Failed to save prompt content")

        # 更新索引
        index_data = self._load_index()
        index_data["prompts"][prompt_id] = prompt_meta

        # 更新 owners 索引
        if owner_id not in index_data["owners"]:
            index_data["owners"][owner_id] = []
        index_data["owners"][owner_id].append(prompt_id)

        if not self._save_index(index_data):
            # 回滚：删除内容文件
            self._delete_prompt_content(prompt_id)
            raise Exception("Failed to save index")

        logger.info(f"Created prompt {prompt_id} for owner {owner_id}")
        return {
            **prompt_meta,
            "prompt": prompt
        }

    def get(self, prompt_id: str, owner_id: Optional[str] = None) -> Dict[str, Any]:
        """
        获取个人提示词详情

        Args:
            prompt_id: 提示词ID
            owner_id: 所有者ID（用于权限校验）

        Returns:
            提示词完整信息

        Raises:
            PromptNotFoundError: 提示词不存在
            PermissionError: 无权限访问
        """
        index_data = self._load_index()
        prompt_meta = index_data["prompts"].get(prompt_id)

        if not prompt_meta:
            raise PromptNotFoundError(f"Prompt {prompt_id} not found")

        # 权限校验
        if owner_id and prompt_meta["ownerId"] != owner_id:
            raise PermissionError(f"No permission to access prompt {prompt_id}")

        # 加载内容
        prompt_content = self._load_prompt_content(prompt_id)
        if prompt_content is None:
            raise PromptNotFoundError(f"Prompt content {prompt_id} not found")

        return {
            **prompt_meta,
            "prompt": prompt_content
        }

    def update(
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
            PromptNotFoundError: 提示词不存在
            PromptConflictError: 版本冲突
            PermissionError: 无权限
        """
        index_data = self._load_index()
        prompt_meta = index_data["prompts"].get(prompt_id)

        if not prompt_meta:
            raise PromptNotFoundError(f"Prompt {prompt_id} not found")

        # 权限校验
        if prompt_meta["ownerId"] != owner_id:
            raise PermissionError(f"No permission to update prompt {prompt_id}")

        # 版本并发控制
        if version is not None and prompt_meta["version"] != version:
            raise PromptConflictError(
                f"Version conflict: expected {version}, got {prompt_meta['version']}"
            )

        # 更新字段
        if name is not None:
            prompt_meta["name"] = name
        if description is not None:
            prompt_meta["description"] = description

        prompt_meta["version"] += 1
        prompt_meta["updatedAt"] = datetime.now().isoformat()

        # 更新内容文件
        if prompt is not None:
            if not self._save_prompt_content(prompt_id, prompt):
                raise Exception("Failed to update prompt content")

        # 保存索引
        index_data["prompts"][prompt_id] = prompt_meta
        if not self._save_index(index_data):
            raise Exception("Failed to save index")

        # 获取最新内容
        current_prompt = self._load_prompt_content(prompt_id) if prompt is None else prompt

        logger.info(f"Updated prompt {prompt_id}, new version {prompt_meta['version']}")
        return {
            **prompt_meta,
            "prompt": current_prompt
        }

    def delete(self, prompt_id: str, owner_id: str) -> bool:
        """
        删除个人提示词（硬删除）

        Args:
            prompt_id: 提示词ID
            owner_id: 所有者ID

        Returns:
            是否删除成功

        Raises:
            PromptNotFoundError: 提示词不存在
            PermissionError: 无权限
        """
        index_data = self._load_index()
        prompt_meta = index_data["prompts"].get(prompt_id)

        if not prompt_meta:
            raise PromptNotFoundError(f"Prompt {prompt_id} not found")

        # 权限校验
        if prompt_meta["ownerId"] != owner_id:
            raise PermissionError(f"No permission to delete prompt {prompt_id}")

        # 删除内容文件
        self._delete_prompt_content(prompt_id)

        # 更新索引
        del index_data["prompts"][prompt_id]

        # 更新 owners 索引
        if owner_id in index_data["owners"]:
            index_data["owners"][owner_id] = [
                pid for pid in index_data["owners"][owner_id] if pid != prompt_id
            ]

        if not self._save_index(index_data):
            raise Exception("Failed to save index after deletion")

        logger.info(f"Deleted prompt {prompt_id}")
        return True

    def list_personal(
        self,
        owner_id: str,
        name_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """
        列出个人提示词（分页 + 搜索）

        Args:
            owner_id: 所有者ID
            name_filter: 名称模糊搜索（可选）
            page: 页码（从1开始）
            page_size: 每页数量

        Returns:
            分页结果 { items, total, page, pageSize }
        """
        index_data = self._load_index()
        owner_prompt_ids = index_data["owners"].get(owner_id, [])

        # 获取所有个人提示词（不含内容）
        prompts = []
        for prompt_id in owner_prompt_ids:
            prompt_meta = index_data["prompts"].get(prompt_id)
            if prompt_meta:
                prompts.append(prompt_meta)

        # 名称过滤（不区分大小写）
        if name_filter:
            name_lower = name_filter.lower()
            prompts = [
                p for p in prompts
                if name_lower in p["name"].lower()
            ]

        # 排序（按更新时间倒序）
        prompts.sort(key=lambda x: x["updatedAt"], reverse=True)

        # 分页
        total = len(prompts)
        start = (page - 1) * page_size
        end = start + page_size
        items = prompts[start:end]

        return {
            "items": items,
            "total": total,
            "page": page,
            "pageSize": page_size
        }

    def list_recommended(
        self,
        name_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """
        列出推荐模板（分页 + 搜索）

        Args:
            name_filter: 名称模糊搜索（可选）
            page: 页码（从1开始）
            page_size: 每页数量

        Returns:
            分页结果 { items, total, page, pageSize }
        """
        prompts = self._load_recommended_prompts()

        # 名称过滤（不区分大小写）
        if name_filter:
            name_lower = name_filter.lower()
            prompts = [
                p for p in prompts
                if name_lower in p["name"].lower()
            ]

        # 分页
        total = len(prompts)
        start = (page - 1) * page_size
        end = start + page_size
        items = prompts[start:end]

        # 移除 prompt 字段（列表中不返回完整内容）
        items_without_content = [
            {k: v for k, v in item.items() if k != "prompt"}
            for item in items
        ]

        return {
            "items": items_without_content,
            "total": total,
            "page": page,
            "pageSize": page_size
        }

    def get_recommended(self, prompt_id: str) -> Dict[str, Any]:
        """
        获取推荐模板详情

        Args:
            prompt_id: 模板ID

        Returns:
            模板完整信息

        Raises:
            PromptNotFoundError: 模板不存在
        """
        prompts = self._load_recommended_prompts()

        for prompt in prompts:
            if prompt["id"] == prompt_id:
                return prompt

        raise PromptNotFoundError(f"Recommended prompt {prompt_id} not found")

    def check_name_uniqueness(self, owner_id: str, name: str, exclude_id: Optional[str] = None) -> bool:
        """
        检查名称唯一性（同一 owner 下）

        Args:
            owner_id: 所有者ID
            name: 提示词名称
            exclude_id: 排除的提示词ID（用于更新场景）

        Returns:
            True: 名称唯一；False: 名称已存在
        """
        index_data = self._load_index()
        owner_prompt_ids = index_data["owners"].get(owner_id, [])

        for prompt_id in owner_prompt_ids:
            if exclude_id and prompt_id == exclude_id:
                continue

            prompt_meta = index_data["prompts"].get(prompt_id)
            if prompt_meta and prompt_meta["name"] == name:
                return False

        return True
