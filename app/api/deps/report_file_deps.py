"""报告文件存储API依赖"""

from typing import Optional
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.report_storage_db.session import get_report_db_session
from app.services.storage import StorageServiceFactory, ObjectStorageService
from app.services.report_file_service import ReportFileService
from app.config import config
from app.logger import logger


# 全局存储服务实例（单例）
_storage_service_instance: Optional[ObjectStorageService] = None
_storage_service_error: Optional[str] = None


def get_storage_service() -> Optional[ObjectStorageService]:
    """获取对象存储服务实例（单例）

    如果配置不存在或初始化失败，返回None而不是抛出异常
    """
    global _storage_service_instance, _storage_service_error

    # 如果已经尝试过但失败了，直接返回None
    if _storage_service_error:
        return None

    if _storage_service_instance is None:
        try:
            # 从配置中读取存储配置
            storage_config = config.storage

            if not storage_config:
                _storage_service_error = "Storage configuration not found"
                logger.warning("Storage configuration not found. Object storage features disabled.")
                return None

            # 转换为字典
            config_dict = storage_config.model_dump()
            _storage_service_instance = StorageServiceFactory.create(config_dict)
            logger.info("Storage service initialized successfully")

        except Exception as e:
            _storage_service_error = str(e)
            logger.warning(f"Failed to initialize storage service: {e}. Object storage features disabled.")
            return None

    return _storage_service_instance


async def get_report_file_service(
    db_session: AsyncSession = Depends(get_report_db_session),
) -> Optional[ReportFileService]:
    """获取报告文件服务实例

    如果存储服务不可用，返回None
    """
    storage_service = get_storage_service()

    if storage_service is None:
        return None

    return ReportFileService(storage_service, db_session)
