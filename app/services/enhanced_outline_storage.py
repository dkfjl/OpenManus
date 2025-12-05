"""
增强版PPT大纲存储管理服务
负责管理增强版大纲的存储、检索和状态管理
"""

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import config
from app.enhanced_schema import (
    EnhancedOutlineInfo,
    EnhancedOutlineStatus,
    EnhancedSlideItem,
)
from app.logger import logger


class EnhancedOutlineStorage:
    """增强版PPT大纲存储管理服务"""

    def __init__(self, storage_dir: Optional[Path] = None):
        """
        初始化存储服务

        Args:
            storage_dir: 存储目录路径，如果为None则使用默认路径
        """
        if storage_dir is None:
            self.storage_dir = config.workspace_root / "enhanced_outlines"
        else:
            self.storage_dir = storage_dir

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.storage_dir / "index.json"

        # 确保索引文件存在
        self._ensure_index_file()

    def _ensure_index_file(self) -> None:
        """确保索引文件存在"""
        if not self.index_file.exists():
            self._save_index({"outlines": {}})

    def _load_index(self) -> Dict[str, Any]:
        """加载索引文件"""
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load index file: {str(e)}")
            return {"outlines": {}}

    def _save_index(self, index_data: Dict[str, Any]) -> bool:
        """保存索引文件"""
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save index file: {str(e)}")
            return False

    async def create_outline_record(
        self, topic: str, language: str, reference_sources: List[str]
    ) -> str:
        """
        创建增强版大纲记录（初始状态）

        Args:
            topic: PPT主题
            language: 输出语言
            reference_sources: 参考文件源列表

        Returns:
            生成的UUID
        """
        outline_uuid = str(uuid.uuid4())
        created_at = datetime.now().isoformat()

        # 构建大纲信息
        outline_info = EnhancedOutlineInfo(
            uuid=outline_uuid,
            topic=topic,
            language=language,
            status=EnhancedOutlineStatus.PENDING,
            created_at=created_at,
            updated_at=created_at,
            file_path=f"{outline_uuid}.json",
            reference_sources=reference_sources,
        )

        # 更新索引
        index_data = self._load_index()
        index_data["outlines"][outline_uuid] = outline_info.model_dump()

        if self._save_index(index_data):
            logger.info(f"Created enhanced outline record with UUID: {outline_uuid}")
            return outline_uuid
        else:
            raise Exception("Failed to create outline record")

    async def save_outline(
        self,
        outline: List[EnhancedSlideItem],
        topic: str,
        language: str,
        reference_sources: List[str],
        uuid: Optional[str] = None,
        status: EnhancedOutlineStatus = EnhancedOutlineStatus.COMPLETED,
    ) -> str:
        """
        保存增强版大纲

        Args:
            outline: 增强版大纲内容
            topic: PPT主题
            language: 输出语言
            reference_sources: 参考文件源列表
            uuid: 大纲UUID，如果为None则生成新的
            status: 大纲状态

        Returns:
            大纲UUID
        """
        if uuid is None:
            uuid = str(uuid.uuid4())

        updated_at = datetime.now().isoformat()
        outline_file = self.storage_dir / f"{uuid}.json"

        try:
            # 保存大纲内容到文件
            outline_data = [item.model_dump() for item in outline]
            with open(outline_file, "w", encoding="utf-8") as f:
                json.dump(outline_data, f, ensure_ascii=False, indent=2)

            # 更新索引
            index_data = self._load_index()

            if uuid in index_data["outlines"]:
                # 更新现有记录
                index_data["outlines"][uuid].update(
                    {
                        "status": status,
                        "updated_at": updated_at,
                        "topic": topic,
                        "language": language,
                        "reference_sources": reference_sources,
                    }
                )
            else:
                # 创建新记录
                outline_info = EnhancedOutlineInfo(
                    uuid=uuid,
                    topic=topic,
                    language=language,
                    status=status,
                    created_at=updated_at,
                    updated_at=updated_at,
                    file_path=f"{uuid}.json",
                    reference_sources=reference_sources,
                )
                index_data["outlines"][uuid] = outline_info.model_dump()

            if self._save_index(index_data):
                logger.info(f"Saved enhanced outline with UUID: {uuid}")
                return uuid
            else:
                raise Exception("Failed to update index")

        except Exception as e:
            logger.error(f"Failed to save enhanced outline {uuid}: {str(e)}")
            raise

    async def get_outline(self, uuid: str) -> Optional[List[EnhancedSlideItem]]:
        """
        根据UUID获取增强版大纲

        Args:
            uuid: 大纲UUID

        Returns:
            增强版大纲内容，如果找不到则返回None
        """
        try:
            # 检查索引中是否存在
            index_data = self._load_index()
            if uuid not in index_data["outlines"]:
                logger.warning(f"Enhanced outline not found in index: {uuid}")
                return None

            outline_info = index_data["outlines"][uuid]

            # 检查状态
            if outline_info["status"] != EnhancedOutlineStatus.COMPLETED:
                logger.info(
                    f"Enhanced outline not completed, status: {outline_info['status']}"
                )
                return None

            # 读取大纲文件
            outline_file = self.storage_dir / outline_info["file_path"]
            if not outline_file.exists():
                logger.error(f"Enhanced outline file not found: {outline_file}")
                return None

            with open(outline_file, "r", encoding="utf-8") as f:
                outline_data = json.load(f)

            # 转换为EnhancedSlideItem对象
            enhanced_outline = [
                EnhancedSlideItem.model_validate(item) for item in outline_data
            ]

            logger.info(f"Successfully loaded enhanced outline: {uuid}")
            return enhanced_outline

        except Exception as e:
            logger.error(f"Failed to get enhanced outline {uuid}: {str(e)}")
            return None

    async def get_outline_info(self, uuid: str) -> Optional[Dict[str, Any]]:
        """
        获取大纲信息（不包含内容）

        Args:
            uuid: 大纲UUID

        Returns:
            大纲信息，如果找不到则返回None
        """
        try:
            index_data = self._load_index()
            if uuid not in index_data["outlines"]:
                return None

            return index_data["outlines"][uuid].copy()

        except Exception as e:
            logger.error(f"Failed to get outline info for {uuid}: {str(e)}")
            return None

    async def update_outline_status(
        self,
        uuid: str,
        status: EnhancedOutlineStatus,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        更新大纲状态

        Args:
            uuid: 大纲UUID
            status: 新状态
            error_message: 错误信息（如果状态为failed）

        Returns:
            是否更新成功
        """
        try:
            index_data = self._load_index()

            if uuid not in index_data["outlines"]:
                logger.warning(f"Outline not found for status update: {uuid}")
                return False

            updated_at = datetime.now().isoformat()
            index_data["outlines"][uuid].update(
                {
                    "status": status,
                    "updated_at": updated_at,
                    "error_message": error_message,
                }
            )

            if self._save_index(index_data):
                logger.info(f"Updated outline status: {uuid} -> {status}")
                return True
            else:
                return False

        except Exception as e:
            logger.error(f"Failed to update outline status for {uuid}: {str(e)}")
            return False

    def get_all_outlines(self) -> List[Dict[str, Any]]:
        """
        获取所有大纲信息

        Returns:
            所有大纲信息列表
        """
        try:
            index_data = self._load_index()
            return list(index_data["outlines"].values())
        except Exception as e:
            logger.error(f"Failed to get all outlines: {str(e)}")
            return []

    def get_outlines_by_status(
        self, status: EnhancedOutlineStatus
    ) -> List[Dict[str, Any]]:
        """
        根据状态获取大纲信息

        Args:
            status: 大纲状态

        Returns:
            符合条件的大纲信息列表
        """
        try:
            index_data = self._load_index()
            return [
                info
                for info in index_data["outlines"].values()
                if info["status"] == status
            ]
        except Exception as e:
            logger.error(f"Failed to get outlines by status {status}: {str(e)}")
            return []

    async def delete_outline(self, uuid: str) -> bool:
        """
        删除大纲

        Args:
            uuid: 大纲UUID

        Returns:
            是否删除成功
        """
        try:
            index_data = self._load_index()

            if uuid not in index_data["outlines"]:
                logger.warning(f"Outline not found for deletion: {uuid}")
                return False

            outline_info = index_data["outlines"][uuid]
            outline_file = self.storage_dir / outline_info["file_path"]

            # 删除文件
            if outline_file.exists():
                outline_file.unlink()

            # 从索引中移除
            del index_data["outlines"][uuid]

            if self._save_index(index_data):
                logger.info(f"Deleted enhanced outline: {uuid}")
                return True
            else:
                return False

        except Exception as e:
            logger.error(f"Failed to delete outline {uuid}: {str(e)}")
            return False

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        获取存储统计信息

        Returns:
            存储统计信息
        """
        try:
            index_data = self._load_index()
            outlines = index_data["outlines"]

            total_count = len(outlines)
            status_counts = {
                status: sum(1 for info in outlines.values() if info["status"] == status)
                for status in EnhancedOutlineStatus
            }

            # 计算存储大小
            total_size = 0
            for info in outlines.values():
                outline_file = self.storage_dir / info["file_path"]
                if outline_file.exists():
                    total_size += outline_file.stat().st_size

            return {
                "total_outlines": total_count,
                "status_counts": status_counts,
                "total_storage_size": total_size,
                "storage_directory": str(self.storage_dir),
                "index_file_size": (
                    self.index_file.stat().st_size if self.index_file.exists() else 0
                ),
            }

        except Exception as e:
            logger.error(f"Failed to get storage stats: {str(e)}")
            return {
                "total_outlines": 0,
                "status_counts": {},
                "total_storage_size": 0,
                "storage_directory": str(self.storage_dir),
                "index_file_size": 0,
            }


# 全局存储服务实例
enhanced_outline_storage = EnhancedOutlineStorage()


# 存储清理函数
async def cleanup_old_outlines(days_to_keep: int = 30) -> int:
    """
    清理过期的大纲文件

    Args:
        days_to_keep: 保留天数

    Returns:
        清理的数量
    """
    try:
        storage = enhanced_outline_storage
        current_time = datetime.now()
        cleaned_count = 0

        all_outlines = storage.get_all_outlines()

        for outline_info in all_outlines:
            try:
                # 解析创建时间
                created_at = datetime.fromisoformat(outline_info["created_at"])
                age_days = (current_time - created_at).days

                # 如果超过保留天数且状态为completed，则删除
                if (
                    age_days > days_to_keep
                    and outline_info["status"] == EnhancedOutlineStatus.COMPLETED
                ):
                    if await storage.delete_outline(outline_info["uuid"]):
                        cleaned_count += 1

            except Exception as e:
                logger.warning(
                    f"Failed to process outline for cleanup: {outline_info.get('uuid', 'unknown')}"
                )
                continue

        logger.info(f"Cleaned up {cleaned_count} old outlines")
        return cleaned_count

    except Exception as e:
        logger.error(f"Failed to cleanup old outlines: {str(e)}")
        return 0


# 存储健康检查函数
async def check_storage_health() -> Dict[str, Any]:
    """
    检查存储健康状况

    Returns:
        健康状况信息
    """
    try:
        storage = enhanced_outline_storage

        # 基本检查
        health_info = {
            "storage_directory_exists": storage.storage_dir.exists(),
            "index_file_exists": storage.index_file.exists(),
            "can_read_index": False,
            "can_write_index": False,
            "broken_references": 0,
            "status": "healthy",
        }

        # 检查索引文件读写
        try:
            index_data = storage._load_index()
            health_info["can_read_index"] = True

            # 测试写入
            test_index = index_data.copy()
            storage._save_index(test_index)
            health_info["can_write_index"] = True

            # 检查文件引用完整性
            for outline_info in index_data["outlines"].values():
                outline_file = storage.storage_dir / outline_info["file_path"]
                if (
                    outline_info["status"] == EnhancedOutlineStatus.COMPLETED
                    and not outline_file.exists()
                ):
                    health_info["broken_references"] += 1

        except Exception as e:
            health_info["status"] = "unhealthy"
            health_info["error"] = str(e)

        # 确定整体状态
        if (
            health_info["storage_directory_exists"]
            and health_info["index_file_exists"]
            and health_info["can_read_index"]
            and health_info["can_write_index"]
            and health_info["broken_references"] == 0
        ):
            health_info["status"] = "healthy"
        else:
            health_info["status"] = "degraded"

        return health_info

    except Exception as e:
        logger.error(f"Failed to check storage health: {str(e)}")
        return {
            "storage_directory_exists": False,
            "index_file_exists": False,
            "can_read_index": False,
            "can_write_index": False,
            "broken_references": 0,
            "status": "unhealthy",
            "error": str(e),
        }
