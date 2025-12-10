"""对象存储服务模块"""

from .base import ObjectStorageService
from .aliyun_oss import AliyunOSSService
from .aws_s3 import AWSS3Service
from .minio import MinIOService
from .factory import StorageServiceFactory

__all__ = [
    'ObjectStorageService',
    'AliyunOSSService',
    'AWSS3Service',
    'MinIOService',
    'StorageServiceFactory',
]
