"""MinIO存储服务实现

MinIO是S3兼容的对象存储服务，可以自托管。
使用boto3的S3客户端，配置自定义endpoint。
"""

import asyncio
from typing import Optional, Dict, Any
from pathlib import Path

try:
    import boto3
    from botocore.client import Config
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    Config = None
    ClientError = None

from app.logger import logger
from .base import ObjectStorageService


class MinIOService(ObjectStorageService):
    """MinIO存储服务（S3兼容）"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        if boto3 is None:
            raise ImportError(
                "boto3 package is required for MinIO support. "
                "Install it with: pip install boto3"
            )

        access_key = config.get('access_key')
        secret_key = config.get('secret_key')
        endpoint = config.get('endpoint')

        # MinIO通常使用http://或https://开头的完整URL
        if not endpoint:
            raise ValueError("endpoint is required for MinIO")

        if not access_key or not secret_key:
            raise ValueError("access_key and secret_key are required for MinIO")

        # 确定是否使用SSL
        use_ssl = endpoint.startswith('https://')

        # 移除协议前缀，因为boto3会自动处理
        endpoint_url = endpoint

        # 创建S3客户端，配置自定义endpoint
        self.s3_client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version='s3v4'),
            region_name=self.region or 'us-east-1',  # MinIO通常不关心region，但boto3需要
            use_ssl=use_ssl
        )

        logger.info(f"Initialized MinIO service: endpoint={endpoint}, bucket={self.bucket}")

    async def upload_file(self, file_path: Path, storage_key: str) -> str:
        """上传文件到MinIO"""
        try:
            def _upload():
                extra_args = {
                    'ContentType': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                }
                if self.private_storage:
                    extra_args['ACL'] = 'private'
                else:
                    extra_args['ACL'] = 'public-read'

                self.s3_client.upload_file(
                    str(file_path),
                    self.bucket,
                    storage_key,
                    ExtraArgs=extra_args
                )
                return True

            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, _upload)

            if success:
                logger.info(f"File uploaded successfully to MinIO: {storage_key}")
                return storage_key
            else:
                raise RuntimeError(f"Failed to upload file: {storage_key}")

        except Exception as e:
            logger.error(f"Error uploading file to MinIO: {e}")
            raise

    async def generate_presigned_url(
        self,
        storage_key: str,
        expire_seconds: Optional[int] = None
    ) -> str:
        """生成预签名URL"""
        try:
            expire_time = expire_seconds or self.presign_expire_seconds

            def _generate_url():
                url = self.s3_client.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': self.bucket,
                        'Key': storage_key
                    },
                    ExpiresIn=expire_time
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
                self.s3_client.delete_object(Bucket=self.bucket, Key=storage_key)
                return True

            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, _delete)

            if success:
                logger.info(f"File deleted successfully from MinIO: {storage_key}")
            return success

        except Exception as e:
            logger.error(f"Error deleting file from MinIO: {e}")
            return False

    async def get_file_info(self, storage_key: str) -> Dict[str, Any]:
        """获取文件信息"""
        try:
            def _get_info():
                response = self.s3_client.head_object(Bucket=self.bucket, Key=storage_key)
                return {
                    'size': response.get('ContentLength', 0),
                    'content_type': response.get('ContentType', ''),
                    'last_modified': response.get('LastModified', ''),
                    'etag': response.get('ETag', ''),
                }

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, _get_info)
            return info

        except Exception as e:
            logger.error(f"Error getting file info from MinIO: {e}")
            raise

    async def file_exists(self, storage_key: str) -> bool:
        """检查文件是否存在"""
        try:
            def _exists():
                try:
                    self.s3_client.head_object(Bucket=self.bucket, Key=storage_key)
                    return True
                except ClientError as e:
                    if e.response['Error']['Code'] == '404':
                        return False
                    raise

            loop = asyncio.get_event_loop()
            exists = await loop.run_in_executor(None, _exists)
            return exists

        except Exception as e:
            logger.error(f"Error checking file existence in MinIO: {e}")
            return False
