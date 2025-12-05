"""
文件上传服务
负责处理文件上传、UUID生成和文件管理
"""

import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
from fastapi import UploadFile

from app.config import config
from app.logger import logger
from app.schema import FileInfo, FileUploadResponse
from app.services.document_parser_service import DocumentParserService
from app.services.document_summary_service import DocumentSummaryService


class FileUploadService:
    """文件上传服务类"""

    def __init__(self):
        self.upload_dir = config.workspace_root / "uploads"
        self.upload_dir.mkdir(exist_ok=True)
        self.max_files = 5
        self.max_file_size = 10 * 1024 * 1024  # 10MB
        self.supported_extensions = {
            ".pdf",
            ".docx",
            ".txt",
            ".jpg",
            ".jpeg",
            ".png",
            ".html",
            ".htm",
        }

    async def upload_files(self, files: List[UploadFile]) -> FileUploadResponse:
        """
        上传多个文件并生成UUID

        Args:
            files: 上传的文件列表

        Returns:
            FileUploadResponse: 上传结果
        """
        if not files:
            return FileUploadResponse(
                status="error", uuids=[], files=[], message="没有上传文件"
            )

        if len(files) > self.max_files:
            return FileUploadResponse(
                status="error",
                uuids=[],
                files=[],
                message=f"上传文件数量超过限制，最多支持{self.max_files}个文件",
            )

        uploaded_files = []
        uuids = []

        try:
            for file in files:
                # 验证文件
                validation_result = await self._validate_file(file)
                if not validation_result["valid"]:
                    return FileUploadResponse(
                        status="error",
                        uuids=[],
                        files=[],
                        message=validation_result["message"],
                    )

                # 生成UUID
                file_uuid = str(uuid.uuid4())

                # 保存文件
                file_info = await self._save_file(file, file_uuid)
                if file_info:
                    uploaded_files.append(file_info)
                    uuids.append(file_uuid)
                    logger.info(
                        f"文件上传成功: {file_info.original_name} -> {file_info.saved_name}"
                    )

            if not uploaded_files:
                return FileUploadResponse(
                    status="error", uuids=[], files=[], message="文件上传失败"
                )

            return FileUploadResponse(
                status="success",
                uuids=uuids,
                files=uploaded_files,
                message=f"成功上传{len(uploaded_files)}个文件",
            )

        except Exception as e:
            logger.error(f"文件上传失败: {str(e)}")
            # 清理已上传的文件
            await self._cleanup_files(uuids)
            return FileUploadResponse(
                status="error", uuids=[], files=[], message=f"文件上传失败: {str(e)}"
            )

    async def _validate_file(self, file: UploadFile) -> Dict[str, Any]:
        """验证上传文件"""
        if not file.filename:
            return {"valid": False, "message": "文件名不能为空"}

        # 检查文件扩展名
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in self.supported_extensions:
            return {
                "valid": False,
                "message": f"不支持的文件格式: {file_ext}。支持的格式: {', '.join(self.supported_extensions)}",
            }

        # 检查文件大小
        content = await file.read()
        await file.seek(0)  # 重置文件指针

        if len(content) > self.max_file_size:
            return {
                "valid": False,
                "message": f"文件过大: {len(content) / (1024*1024):.2f}MB。最大允许: {self.max_file_size / (1024*1024)}MB",
            }

        if len(content) == 0:
            return {"valid": False, "message": "文件为空"}

        return {"valid": True, "message": "验证通过"}

    async def _save_file(self, file: UploadFile, file_uuid: str) -> Optional[FileInfo]:
        """保存文件到本地"""
        try:
            original_name = file.filename or "unknown"
            file_ext = Path(original_name).suffix.lower()
            saved_name = f"{file_uuid}_{original_name}"
            file_path = self.upload_dir / saved_name

            # 保存文件
            async with aiofiles.open(file_path, "wb") as f:
                content = await file.read()
                await f.write(content)

            # 获取文件信息
            file_size = len(content)
            file_type = file.content_type or "application/octet-stream"

            return FileInfo(
                uuid=file_uuid,
                original_name=original_name,
                saved_name=saved_name,
                size=file_size,
                type=file_type,
            )

        except Exception as e:
            logger.error(f"保存文件失败: {str(e)}")
            return None

    async def _cleanup_files(self, uuids: List[str]) -> None:
        """清理已上传的文件"""
        for file_uuid in uuids:
            try:
                # 查找并删除该UUID的文件
                for file_path in self.upload_dir.glob(f"{file_uuid}_*"):
                    if file_path.exists():
                        file_path.unlink()
                        logger.info(f"清理文件: {file_path}")
            except Exception as e:
                logger.warning(f"清理文件失败 {file_uuid}: {str(e)}")

    def get_file_by_uuid(self, file_uuid: str) -> Optional[Path]:
        """
        根据UUID查找文件

        Args:
            file_uuid: 文件UUID

        Returns:
            文件路径，如果找到则返回，否则返回None
        """
        try:
            # 查找该UUID的文件
            matching_files = list(self.upload_dir.glob(f"{file_uuid}_*"))
            if matching_files:
                return matching_files[0]  # 返回第一个匹配的文件
            return None
        except Exception as e:
            logger.error(f"查找文件失败 {file_uuid}: {str(e)}")
            return None

    def get_file_info_by_uuid(self, file_uuid: str) -> Optional[FileInfo]:
        """
        根据UUID获取文件信息

        Args:
            file_uuid: 文件UUID

        Returns:
            文件信息，如果找到则返回，否则返回None
        """
        try:
            file_path = self.get_file_by_uuid(file_uuid)
            if not file_path or not file_path.exists():
                return None

            # 解析文件名
            saved_name = file_path.name
            parts = saved_name.split("_", 1)
            if len(parts) != 2:
                return None

            original_name = parts[1]
            file_size = file_path.stat().st_size

            # 推测MIME类型
            from mimetypes import guess_type

            mime_type, _ = guess_type(str(file_path))
            file_type = mime_type or "application/octet-stream"

            return FileInfo(
                uuid=file_uuid,
                original_name=original_name,
                saved_name=saved_name,
                size=file_size,
                type=file_type,
            )

        except Exception as e:
            logger.error(f"获取文件信息失败 {file_uuid}: {str(e)}")
            return None

    def get_supported_formats(self) -> Dict[str, Any]:
        """获取支持的文件格式信息"""
        return {
            "supported_extensions": list(self.supported_extensions),
            "max_file_size_mb": self.max_file_size / (1024 * 1024),
            "max_file_count": self.max_files,
            "description": {
                ".pdf": "PDF文档",
                ".docx": "Word文档",
                ".txt": "纯文本文件",
                ".jpg/.jpeg": "JPEG图片（OCR识别）",
                ".png": "PNG图片（OCR识别）",
                ".html/.htm": "HTML文档（提取正文）",
            },
        }


# 全局文件上传服务实例
file_upload_service = FileUploadService()


async def get_files_by_uuids(file_uuids: List[str]) -> List[Path]:
    """
    根据UUID列表获取文件路径列表

    Args:
        file_uuids: UUID列表

    Returns:
        存在的文件路径列表
    """
    files = []
    for uuid_str in file_uuids:
        file_path = file_upload_service.get_file_by_uuid(uuid_str)
        if file_path and file_path.exists():
            files.append(file_path)
        else:
            logger.warning(f"未找到UUID对应的文件: {uuid_str}")

    return files


async def get_file_contents_by_uuids(file_uuids: List[str]) -> str:
    """
    根据UUID列表获取文件内容摘要

    Args:
        file_uuids: UUID列表

    Returns:
        合并的文件内容摘要
    """
    if not file_uuids:
        return ""

    files = await get_files_by_uuids(file_uuids)
    if not files:
        return ""

    # 使用现有的文档解析和摘要服务
    from app.services.document_parser_service import DocumentParserService
    from app.services.document_summary_service import DocumentSummaryService

    parser_service = DocumentParserService()
    summary_service = DocumentSummaryService()

    try:
        # 模拟UploadFile对象
        class MockUploadFile:
            def __init__(self, file_path: Path):
                self.filename = file_path.name
                self.file_path = file_path
                self.content_type = None
                # 创建文件对象用于兼容性
                self.file = open(file_path, "rb")
                self._content = None

            async def read(self):
                if self._content is None:
                    async with aiofiles.open(self.file_path, "rb") as f:
                        self._content = await f.read()
                return self._content

            async def seek(self, pos):
                if self.file:
                    self.file.seek(pos)

            def __del__(self):
                # 清理文件对象
                if hasattr(self, "file") and self.file and not self.file.closed:
                    self.file.close()

        # 解析文件
        mock_files = [MockUploadFile(file_path) for file_path in files]
        parsed_content = await parser_service.parse_uploaded_files(mock_files)

        if parsed_content.strip():
            # 生成摘要
            summary = await summary_service.summarize_limited(
                parsed_content, language="zh", max_chars=1500  # 默认中文
            )
            return summary

        return ""

    except Exception as e:
        logger.error(f"处理UUID文件失败: {str(e)}")
        return ""
