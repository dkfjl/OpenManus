"""报告文件管理服务"""

import uuid
from typing import Optional
from pathlib import Path
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.logger import logger
from app.report_storage_db.models import ReportFile, FileAccessLog
from app.services.storage import ObjectStorageService


class ReportFileService:
    """报告文件管理服务"""

    def __init__(self, storage_service: ObjectStorageService, db_session: AsyncSession):
        """初始化服务

        Args:
            storage_service: 对象存储服务实例
            db_session: 数据库会话
        """
        self.storage_service = storage_service
        self.db = db_session

    async def upload_report_file(
        self,
        file_path: Path,
        original_filename: str,
        user_id: str,
        expire_days: int = 30
    ) -> str:
        """上传报告文件

        Args:
            file_path: 本地文件路径
            original_filename: 原始文件名
            user_id: 用户ID
            expire_days: 文件过期天数，默认30天

        Returns:
            文件UUID
        """
        try:
            # 生成UUID
            file_uuid = str(uuid.uuid4())

            # 生成存储key
            storage_key = self.storage_service.generate_storage_key(file_uuid, original_filename)

            # 上传到对象存储
            await self.storage_service.upload_file(file_path, storage_key)

            # 计算过期时间
            expires_at = datetime.now() + timedelta(days=expire_days) if expire_days > 0 else None

            # 保存元数据
            file_info = ReportFile(
                uuid=file_uuid,
                original_filename=original_filename,
                file_size=file_path.stat().st_size,
                storage_key=storage_key,
                storage_type=self.storage_service.config.get('type', 'oss'),
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                created_by=user_id,
                expires_at=expires_at,
                status='active'  # 使用字符串而不是Enum
            )

            async with self.db.begin():
                self.db.add(file_info)
                await self.db.flush()

            logger.info(f"Report file uploaded: uuid={file_uuid}, filename={original_filename}")

            # 删除本地文件
            try:
                file_path.unlink(missing_ok=True)
                logger.debug(f"Local file deleted: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to delete local file {file_path}: {e}")

            return file_uuid

        except Exception as e:
            logger.error(f"Error uploading report file: {e}")
            raise

    async def get_file_info(self, file_uuid: str, user_id: Optional[str] = None) -> Optional[ReportFile]:
        """获取文件信息

        Args:
            file_uuid: 文件UUID
            user_id: 用户ID，如果提供则验证权限

        Returns:
            文件信息对象，如果不存在则返回None
        """
        try:
            async with self.db.begin():
                stmt = select(ReportFile).where(ReportFile.uuid == file_uuid)
                result = await self.db.execute(stmt)
                file_info = result.scalar_one_or_none()

                if not file_info:
                    return None

                # 权限验证
                if user_id and file_info.created_by != user_id:
                    logger.warning(f"Permission denied: user={user_id}, file_uuid={file_uuid}")
                    return None

                return file_info

        except Exception as e:
            logger.error(f"Error getting file info: {e}")
            raise

    async def get_preview_url(
        self,
        file_uuid: str,
        user_id: str,
        access_ip: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> str:
        """获取预览URL

        Args:
            file_uuid: 文件UUID
            user_id: 用户ID
            access_ip: 访问IP
            user_agent: 用户代理

        Returns:
            预签名URL

        Raises:
            FileNotFoundError: 文件不存在
            PermissionError: 无访问权限
            ValueError: 文件已过期或删除
        """
        # 查询文件信息
        file_info = await self.get_file_info(file_uuid, user_id)

        if not file_info:
            raise FileNotFoundError(f"File not found: {file_uuid}")

        # 检查文件状态
        if file_info.status != 'active':
            raise ValueError(f"File is not active: status={file_info.status}")

        # 检查过期时间
        if file_info.expires_at and datetime.now() > file_info.expires_at:
            # 更新状态为已过期
            async with self.db.begin():
                file_info.status = 'expired'
                await self.db.flush()
            raise ValueError("File has expired")

        # 生成临时URL
        presigned_url = await self.storage_service.generate_presigned_url(
            file_info.storage_key,
            expire_seconds=self.storage_service.presign_expire_seconds
        )

        # 记录访问日志
        try:
            access_log = FileAccessLog(
                file_uuid=file_uuid,
                user_id=user_id,
                access_type='preview',  # 使用字符串而不是Enum
                access_ip=access_ip,
                user_agent=user_agent,
                presign_url=presigned_url[:1000] if presigned_url else None,  # 限制长度
                expire_at=datetime.now() + timedelta(seconds=self.storage_service.presign_expire_seconds)
            )

            async with self.db.begin():
                self.db.add(access_log)
                # 更新下载次数
                file_info.download_count += 1
                await self.db.flush()

            logger.info(f"Preview URL generated: uuid={file_uuid}, user={user_id}")

        except Exception as e:
            logger.error(f"Error logging access: {e}")
            # 不影响主流程

        return presigned_url

    async def get_download_url(
        self,
        file_uuid: str,
        user_id: str,
        access_ip: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> str:
        """获取下载URL（类似preview_url，但记录为download类型）

        Args:
            file_uuid: 文件UUID
            user_id: 用户ID
            access_ip: 访问IP
            user_agent: 用户代理

        Returns:
            预签名URL
        """
        # 查询文件信息
        file_info = await self.get_file_info(file_uuid, user_id)

        if not file_info:
            raise FileNotFoundError(f"File not found: {file_uuid}")

        if file_info.status != 'active':
            raise ValueError(f"File is not active: status={file_info.status}")

        if file_info.expires_at and datetime.now() > file_info.expires_at:
            async with self.db.begin():
                file_info.status = 'expired'
                await self.db.flush()
            raise ValueError("File has expired")

        # 生成临时URL
        presigned_url = await self.storage_service.generate_presigned_url(
            file_info.storage_key,
            expire_seconds=self.storage_service.presign_expire_seconds
        )

        # 记录访问日志
        try:
            access_log = FileAccessLog(
                file_uuid=file_uuid,
                user_id=user_id,
                access_type='download',  # 使用字符串而不是Enum
                access_ip=access_ip,
                user_agent=user_agent,
                presign_url=presigned_url[:1000] if presigned_url else None,
                expire_at=datetime.now() + timedelta(seconds=self.storage_service.presign_expire_seconds)
            )

            async with self.db.begin():
                self.db.add(access_log)
                file_info.download_count += 1
                await self.db.flush()

            logger.info(f"Download URL generated: uuid={file_uuid}, user={user_id}")

        except Exception as e:
            logger.error(f"Error logging access: {e}")

        return presigned_url

    async def delete_file(self, file_uuid: str, user_id: str) -> bool:
        """删除文件

        Args:
            file_uuid: 文件UUID
            user_id: 用户ID

        Returns:
            是否删除成功
        """
        try:
            # 获取文件信息
            file_info = await self.get_file_info(file_uuid, user_id)

            if not file_info:
                logger.warning(f"File not found or permission denied: {file_uuid}")
                return False

            # 从对象存储中删除
            storage_deleted = await self.storage_service.delete_file(file_info.storage_key)

            # 更新数据库状态
            async with self.db.begin():
                file_info.status = 'deleted'  # 使用字符串而不是Enum
                await self.db.flush()

            logger.info(f"File deleted: uuid={file_uuid}, storage_deleted={storage_deleted}")
            return True

        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return False
