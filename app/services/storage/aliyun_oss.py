"""阿里云OSS存储服务实现"""

import asyncio
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime, timedelta

try:
    import oss2
    from oss2.models import SimplifiedObjectInfo
except ImportError:
    oss2 = None

from app.logger import logger
from .base import ObjectStorageService


class AliyunOSSService(ObjectStorageService):
    """阿里云OSS存储服务"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        if oss2 is None:
            raise ImportError(
                "oss2 package is required for Aliyun OSS support. "
                "Install it with: pip install oss2"
            )

        access_key = config.get('access_key')
        secret_key = config.get('secret_key')
        endpoint = config.get('endpoint') or f"https://oss-{self.region}.aliyuncs.com"

        if not access_key or not secret_key:
            raise ValueError("access_key and secret_key are required for Aliyun OSS")

        # 创建认证对象
        auth = oss2.Auth(access_key, secret_key)

        # 创建Bucket对象
        self.bucket_client = oss2.Bucket(auth, endpoint, self.bucket)

        logger.info(f"Initialized Aliyun OSS service: bucket={self.bucket}, region={self.region}")

    async def upload_file(self, file_path: Path, storage_key: str) -> str:
        """上传文件到阿里云OSS"""
        try:
            # OSS SDK是同步的，所以需要在executor中运行
            def _upload():
                with open(file_path, 'rb') as f:
                    # 设置为私有权限
                    headers = {
                        'x-oss-object-acl': 'private' if self.private_storage else 'public-read',
                        'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                    }
                    result = self.bucket_client.put_object(storage_key, f, headers=headers)
                    return result.status == 200

            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, _upload)

            if success:
                logger.info(f"File uploaded successfully: {storage_key}")
                return storage_key
            else:
                raise RuntimeError(f"Failed to upload file: {storage_key}")

        except Exception as e:
            logger.error(f"Error uploading file to OSS: {e}")
            raise

    async def generate_presigned_url(
        self,
        storage_key: str,
        expire_seconds: Optional[int] = None,
        response_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """生成预签名URL"""
        try:
            expire_time = expire_seconds or self.presign_expire_seconds

            def _generate_url():
                # 生成下载签名URL
                params = None
                if response_params:
                    params = {}
                    cd = response_params.get('content_disposition')
                    ct = response_params.get('content_type')
                    if cd:
                        params['response-content-disposition'] = cd
                    if ct:
                        params['response-content-type'] = ct
                url = self.bucket_client.sign_url(
                    'GET',
                    storage_key,
                    expire_time,
                    slash_safe=True,
                    params=params
                )
                return url

            loop = asyncio.get_event_loop()
            url = await loop.run_in_executor(None, _generate_url)

            logger.debug(f"Generated presigned URL for {storage_key}, expires in {expire_time}s")
            return url

        except Exception as e:
            logger.error(f"Error generating presigned URL: {e}")
            raise

    async def delete_file(self, storage_key: str) -> bool:
        """删除文件"""
        try:
            def _delete():
                result = self.bucket_client.delete_object(storage_key)
                return result.status == 204

            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, _delete)

            if success:
                logger.info(f"File deleted successfully: {storage_key}")
            return success

        except Exception as e:
            logger.error(f"Error deleting file from OSS: {e}")
            return False

    async def get_file_info(self, storage_key: str) -> Dict[str, Any]:
        """获取文件信息"""
        try:
            def _get_info():
                meta = self.bucket_client.get_object_meta(storage_key)
                return {
                    'size': int(meta.headers.get('Content-Length', 0)),
                    'content_type': meta.headers.get('Content-Type', ''),
                    'last_modified': meta.headers.get('Last-Modified', ''),
                    'etag': meta.headers.get('ETag', ''),
                }

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, _get_info)
            return info

        except Exception as e:
            logger.error(f"Error getting file info from OSS: {e}")
            raise

    async def file_exists(self, storage_key: str) -> bool:
        """检查文件是否存在"""
        try:
            def _exists():
                return self.bucket_client.object_exists(storage_key)

            loop = asyncio.get_event_loop()
            exists = await loop.run_in_executor(None, _exists)
            return exists

        except Exception as e:
            logger.error(f"Error checking file existence in OSS: {e}")
            return False
