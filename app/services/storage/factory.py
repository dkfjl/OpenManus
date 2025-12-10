"""对象存储服务工厂"""

from typing import Dict, Any

from app.logger import logger
from .base import ObjectStorageService
from .aliyun_oss import AliyunOSSService
from .aws_s3 import AWSS3Service
from .minio import MinIOService


class StorageServiceFactory:
    """存储服务工厂类"""

    _services = {
        'oss': AliyunOSSService,
        'aliyun': AliyunOSSService,
        's3': AWSS3Service,
        'aws': AWSS3Service,
        'minio': MinIOService,
    }

    @classmethod
    def create(cls, config: Dict[str, Any]) -> ObjectStorageService:
        """创建存储服务实例

        Args:
            config: 存储配置字典，必须包含'type'字段

        Returns:
            ObjectStorageService实例

        Raises:
            ValueError: 当存储类型不支持时
        """
        storage_type = config.get('type', '').lower()

        if storage_type not in cls._services:
            supported = ', '.join(cls._services.keys())
            raise ValueError(
                f"Unsupported storage type: {storage_type}. "
                f"Supported types: {supported}"
            )

        service_class = cls._services[storage_type]
        logger.info(f"Creating storage service: {service_class.__name__}")

        return service_class(config)

    @classmethod
    def register(cls, type_name: str, service_class: type):
        """注册新的存储服务类型

        Args:
            type_name: 存储类型名称
            service_class: 服务类（必须继承自ObjectStorageService）
        """
        if not issubclass(service_class, ObjectStorageService):
            raise TypeError(
                f"Service class must be a subclass of ObjectStorageService, "
                f"got {service_class.__name__}"
            )

        cls._services[type_name.lower()] = service_class
        logger.info(f"Registered new storage service: {type_name} -> {service_class.__name__}")
