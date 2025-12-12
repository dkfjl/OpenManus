"""对象存储服务模块

提供统一的对象存储接口，支持多种云存储厂商：
- 阿里云 OSS
- AWS S3
- 腾讯云 COS
- MinIO
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime


class ObjectStorageService(ABC):
    """对象存储服务基类"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.bucket = config['bucket']
        self.region = config.get('region', '')
        self.private_storage = config.get('security', {}).get('private_storage', True)
        self.presign_expire_seconds = config.get('presign_expire_seconds', 3600)

    @abstractmethod
    async def upload_file(self, file_path: Path, storage_key: str) -> str:
        """上传文件到对象存储，返回存储key

        Args:
            file_path: 本地文件路径
            storage_key: 对象存储中的key

        Returns:
            存储的key
        """
        pass

    @abstractmethod
    async def generate_presigned_url(
        self,
        storage_key: str,
        expire_seconds: Optional[int] = None,
        response_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """生成预签名URL

        Args:
            storage_key: 对象存储中的key
            expire_seconds: 过期时间（秒），如果为None则使用默认值
            response_params: 额外的响应参数（如内容处置/类型），
                统一使用键：
                - content_disposition: str (e.g., 'inline; filename="a.docx"')
                - content_type: str (e.g., 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')

        Returns:
            预签名的URL
        """
        pass

    @abstractmethod
    async def delete_file(self, storage_key: str) -> bool:
        """删除文件

        Args:
            storage_key: 对象存储中的key

        Returns:
            是否删除成功
        """
        pass

    @abstractmethod
    async def get_file_info(self, storage_key: str) -> Dict[str, Any]:
        """获取文件信息

        Args:
            storage_key: 对象存储中的key

        Returns:
            文件信息字典
        """
        pass

    @abstractmethod
    async def file_exists(self, storage_key: str) -> bool:
        """检查文件是否存在

        Args:
            storage_key: 对象存储中的key

        Returns:
            文件是否存在
        """
        pass

    def generate_storage_key(self, uuid: str, original_filename: str) -> str:
        """生成存储路径key

        Args:
            uuid: 文件UUID
            original_filename: 原始文件名

        Returns:
            存储路径key，格式：reports/YYYYMMDD/uuid.ext
        """
        timestamp = datetime.now().strftime('%Y%m%d')
        file_ext = Path(original_filename).suffix
        return f"reports/{timestamp}/{uuid}{file_ext}"
