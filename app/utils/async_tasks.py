"""
异步任务管理工具
管理增强版PPT大纲生成的后台任务
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from app.enhanced_schema import EnhancedOutlineStatus
from app.logger import logger
from app.services.enhanced_outline_service import process_enhanced_outline_async
from app.services.enhanced_outline_storage import enhanced_outline_storage


class AsyncTaskManager:
    """异步任务管理器"""

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}
        self._task_metadata: dict[str, dict] = {}
        self._logger = logger

    async def create_task(
        self, coro: Callable, task_id: str, metadata: Optional[dict] = None
    ) -> str:
        """
        创建异步任务

        Args:
            coro: 协程函数
            task_id: 任务ID
            metadata: 任务元数据

        Returns:
            任务ID
        """
        try:
            # 如果已存在相同ID的任务，先取消它
            if task_id in self._tasks:
                await self.cancel_task(task_id)

            # 创建新任务
            task = asyncio.create_task(coro)

            # 存储任务和元数据
            self._tasks[task_id] = task
            self._task_metadata[task_id] = {
                "created_at": datetime.now().isoformat(),
                "coro_name": coro.__name__ if hasattr(coro, "__name__") else str(coro),
                "metadata": metadata or {},
                "status": "running",
            }

            # 添加任务完成回调
            task.add_done_callback(
                lambda t, tid=task_id: self._on_task_complete(tid, t)
            )

            self._logger.info(f"Created async task: {task_id}")
            return task_id

        except Exception as e:
            self._logger.error(f"Failed to create task {task_id}: {str(e)}")
            raise

    async def cancel_task(self, task_id: str) -> bool:
        """
        取消任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功取消
        """
        try:
            if task_id not in self._tasks:
                return False

            task = self._tasks[task_id]

            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # 清理任务数据
            del self._tasks[task_id]
            if task_id in self._task_metadata:
                self._task_metadata[task_id]["status"] = "cancelled"

            self._logger.info(f"Cancelled task: {task_id}")
            return True

        except Exception as e:
            self._logger.error(f"Failed to cancel task {task_id}: {str(e)}")
            return False

    def get_task_status(self, task_id: str) -> Optional[str]:
        """
        获取任务状态

        Args:
            task_id: 任务ID

        Returns:
            任务状态，如果任务不存在则返回None
        """
        if task_id not in self._tasks:
            # 检查是否已完成但被清理
            if task_id in self._task_metadata:
                return self._task_metadata[task_id].get("status", "unknown")
            return None

        task = self._tasks[task_id]

        if task.cancelled():
            return "cancelled"
        elif task.done():
            if task.exception():
                return "failed"
            else:
                return "completed"
        else:
            return "running"

    def get_task_info(self, task_id: str) -> Optional[dict]:
        """
        获取任务信息

        Args:
            task_id: 任务ID

        Returns:
            任务信息
        """
        if task_id not in self._task_metadata:
            return None

        info = self._task_metadata[task_id].copy()
        info["task_id"] = task_id
        info["current_status"] = self.get_task_status(task_id)

        return info

    def get_all_tasks(self) -> List[dict]:
        """
        获取所有任务信息

        Returns:
            所有任务信息列表
        """
        tasks_info = []

        for task_id in list(self._tasks.keys()):
            info = self.get_task_info(task_id)
            if info:
                tasks_info.append(info)

        return tasks_info

    def get_running_tasks(self) -> List[dict]:
        """
        获取正在运行的任务

        Returns:
            正在运行的任务信息列表
        """
        return [
            info
            for info in self.get_all_tasks()
            if info.get("current_status") == "running"
        ]

    def cleanup_completed_tasks(self, max_age_hours: int = 24) -> int:
        """
        清理已完成的任务

        Args:
            max_age_hours: 最大保留时间（小时）

        Returns:
            清理的任务数量
        """
        try:
            cleaned_count = 0
            current_time = datetime.now()

            # 找出需要清理的任务
            tasks_to_cleanup = []
            for task_id, metadata in self._task_metadata.items():
                if task_id not in self._tasks:
                    continue

                task = self._tasks[task_id]
                if task.done():
                    created_at = datetime.fromisoformat(metadata["created_at"])
                    age_hours = (current_time - created_at).total_seconds() / 3600

                    if age_hours > max_age_hours:
                        tasks_to_cleanup.append(task_id)

            # 清理任务
            for task_id in tasks_to_cleanup:
                if task_id in self._tasks:
                    del self._tasks[task_id]
                if task_id in self._task_metadata:
                    del self._task_metadata[task_id]
                cleaned_count += 1

            self._logger.info(f"Cleaned up {cleaned_count} completed tasks")
            return cleaned_count

        except Exception as e:
            self._logger.error(f"Failed to cleanup completed tasks: {str(e)}")
            return 0

    async def wait_for_task(
        self, task_id: str, timeout: Optional[float] = None
    ) -> bool:
        """
        等待任务完成

        Args:
            task_id: 任务ID
            timeout: 超时时间（秒）

        Returns:
            任务是否成功完成
        """
        if task_id not in self._tasks:
            return False

        task = self._tasks[task_id]

        try:
            if timeout is not None:
                await asyncio.wait_for(task, timeout=timeout)
            else:
                await task

            # 检查任务结果
            if task.cancelled():
                return False
            elif task.exception():
                return False
            else:
                return True

        except asyncio.TimeoutError:
            self._logger.warning(f"Task {task_id} timed out")
            return False
        except Exception as e:
            self._logger.error(f"Task {task_id} failed: {str(e)}")
            return False

    def _on_task_complete(self, task_id: str, task: asyncio.Task) -> None:
        """任务完成回调"""
        try:
            if task.cancelled():
                self._logger.info(f"Task {task_id} was cancelled")
                status = "cancelled"
            elif task.exception():
                exception = task.exception()
                self._logger.error(f"Task {task_id} failed: {str(exception)}")
                status = "failed"
            else:
                self._logger.info(f"Task {task_id} completed successfully")
                status = "completed"

            # 更新元数据状态
            if task_id in self._task_metadata:
                self._task_metadata[task_id]["status"] = status
                self._task_metadata[task_id][
                    "completed_at"
                ] = datetime.now().isoformat()

        except Exception as e:
            self._logger.error(
                f"Error in task completion callback for {task_id}: {str(e)}"
            )


# 全局任务管理器实例
async_task_manager = AsyncTaskManager()


# 增强版大纲异步处理专用函数
async def create_enhanced_outline_task(
    original_outline: List[Any],
    topic: str,
    language: str,
    reference_content: Optional[str],
    reference_sources: List[str],
    enhanced_uuid: str,
) -> str:
    """
    创建增强版大纲生成的异步任务

    Args:
        original_outline: 原始大纲
        topic: PPT主题
        language: 输出语言
        reference_content: 参考内容
        reference_sources: 参考文件源
        enhanced_uuid: 增强版大纲UUID

    Returns:
        任务ID
    """
    try:
        # 创建异步任务协程
        async def task_coro():
            return await process_enhanced_outline_async(
                original_outline=original_outline,
                topic=topic,
                language=language,
                reference_content=reference_content,
                reference_sources=reference_sources,
                uuid=enhanced_uuid,
                storage_service=enhanced_outline_storage,
            )

        # 创建任务
        task_id = await async_task_manager.create_task(
            coro=task_coro(),
            task_id=f"enhanced_outline_{enhanced_uuid}",
            metadata={
                "type": "enhanced_outline",
                "topic": topic,
                "language": language,
                "enhanced_uuid": enhanced_uuid,
                "reference_count": len(reference_sources),
            },
        )

        logger.info(f"Created enhanced outline async task: {task_id}")
        return task_id

    except Exception as e:
        logger.error(f"Failed to create enhanced outline task: {str(e)}")
        raise


# 任务状态检查函数
async def check_enhanced_outline_task_status(enhanced_uuid: str) -> Optional[str]:
    """
    检查增强版大纲任务状态

    Args:
        enhanced_uuid: 增强版大纲UUID

    Returns:
        任务状态
    """
    task_id = f"enhanced_outline_{enhanced_uuid}"
    return async_task_manager.get_task_status(task_id)


# 任务信息获取函数
def get_enhanced_outline_task_info(enhanced_uuid: str) -> Optional[dict]:
    """
    获取增强版大纲任务信息

    Args:
        enhanced_uuid: 增强版大纲UUID

    Returns:
        任务信息
    """
    task_id = f"enhanced_outline_{enhanced_uuid}"
    return async_task_manager.get_task_info(task_id)


# 存储和任务状态联合检查
async def get_enhanced_outline_status(enhanced_uuid: str) -> Dict[str, Any]:
    """
    获取增强版大纲的完整状态信息

    Args:
        enhanced_uuid: 增强版大纲UUID

    Returns:
        完整状态信息
    """
    try:
        # 获取存储中的状态
        storage_info = await enhanced_outline_storage.get_outline_info(enhanced_uuid)

        # 获取任务状态
        task_status = await check_enhanced_outline_task_status(enhanced_uuid)
        task_info = get_enhanced_outline_task_info(enhanced_uuid)

        if storage_info:
            # 如果存储中已有信息，以存储状态为准
            return {
                "uuid": enhanced_uuid,
                "status": storage_info["status"],
                "topic": storage_info["topic"],
                "language": storage_info["language"],
                "created_at": storage_info["created_at"],
                "updated_at": storage_info["updated_at"],
                "reference_sources": storage_info["reference_sources"],
                "error_message": storage_info.get("error_message"),
                "task_status": task_status,
                "storage_found": True,
            }
        elif task_info:
            # 如果只有任务信息
            return {
                "uuid": enhanced_uuid,
                "status": EnhancedOutlineStatus.PROCESSING,
                "topic": task_info["metadata"].get("topic", ""),
                "language": task_info["metadata"].get("language", ""),
                "created_at": task_info["created_at"],
                "updated_at": task_info.get("completed_at", task_info["created_at"]),
                "reference_sources": [],
                "error_message": None,
                "task_status": task_status,
                "storage_found": False,
            }
        else:
            # 都没有找到
            return {
                "uuid": enhanced_uuid,
                "status": "not_found",
                "topic": "",
                "language": "",
                "created_at": "",
                "updated_at": "",
                "reference_sources": [],
                "error_message": "Enhanced outline not found",
                "task_status": None,
                "storage_found": False,
            }

    except Exception as e:
        logger.error(
            f"Failed to get enhanced outline status for {enhanced_uuid}: {str(e)}"
        )
        return {
            "uuid": enhanced_uuid,
            "status": "error",
            "topic": "",
            "language": "",
            "created_at": "",
            "updated_at": "",
            "reference_sources": [],
            "error_message": str(e),
            "task_status": None,
            "storage_found": False,
        }


# 定期清理函数
async def periodic_cleanup():
    """定期清理已完成的任务和过期的大纲"""
    try:
        while True:
            # 等待24小时
            await asyncio.sleep(24 * 3600)

            logger.info("Starting periodic cleanup")

            # 清理完成的任务
            async_task_manager.cleanup_completed_tasks(max_age_hours=24)

            # 清理过期的大纲
            from app.services.enhanced_outline_storage import cleanup_old_outlines

            await cleanup_old_outlines(days_to_keep=30)

            logger.info("Periodic cleanup completed")

    except asyncio.CancelledError:
        logger.info("Periodic cleanup task cancelled")
    except Exception as e:
        logger.error(f"Error in periodic cleanup: {str(e)}")


# 启动定期清理任务
async def start_periodic_cleanup():
    """启动定期清理任务"""
    try:
        cleanup_task = asyncio.create_task(periodic_cleanup())
        logger.info("Started periodic cleanup task")
        return cleanup_task
    except Exception as e:
        logger.error(f"Failed to start periodic cleanup: {str(e)}")
        return None
