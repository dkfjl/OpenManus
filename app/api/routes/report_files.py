"""报告文件存储API路由"""

from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pathlib import Path

from app.services.report_file_service import ReportFileService
from app.api.deps.report_file_deps import get_report_file_service
from app.schemas.report_file import (
    PreviewURLResponse,
    PreviewDataResponse,
    DownloadURLResponse,
    MetadataResponse,
    DeleteFileResponse,
    FileInfoResponse,
    FileMetadata,
    PreviewOptions,
)
from app.logger import logger


router = APIRouter(prefix="/api/reports", tags=["Reports"])


def get_client_ip(request: Request) -> str:
    """获取客户端IP"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_user_agent(request: Request) -> str:
    """获取User-Agent"""
    return request.headers.get("User-Agent", "unknown")


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


@router.get("/{file_uuid}/preview")
async def get_preview_url(
    file_uuid: str,
    request: Request,
    user_id: str = "default_user",  # TODO: 从认证中获取
    service: ReportFileService = Depends(get_report_file_service)
) -> PreviewURLResponse:
    """获取预览URL

    Args:
        file_uuid: 文件UUID
        user_id: 用户ID
        request: 请求对象
        service: 报告文件服务

    Returns:
        预览URL响应
    """
    try:
        # 获取客户端信息
        access_ip = get_client_ip(request)
        user_agent = get_user_agent(request)

        # 获取文件信息
        file_info = await service.get_file_info(file_uuid, user_id)
        if not file_info:
            raise HTTPException(status_code=404, detail="文件不存在或无访问权限")

        # 生成预览URL
        preview_url = await service.get_preview_url(
            file_uuid=file_uuid,
            user_id=user_id,
            access_ip=access_ip,
            user_agent=user_agent
        )

        # 计算过期时间
        expire_at = datetime.now() + timedelta(seconds=service.storage_service.presign_expire_seconds)

        return PreviewURLResponse(
            preview_url=preview_url,
            expire_at=expire_at,
            file_info=FileInfoResponse(
                file_uuid=file_info.uuid,
                filename=file_info.original_filename,
                file_size=file_info.file_size,
                created_at=file_info.created_at
            )
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting preview URL: {e}")
        raise HTTPException(status_code=500, detail="获取预览URL失败")


@router.get("/{file_uuid}/preview-data")
async def get_preview_data(
    file_uuid: str,
    request: Request,
    user_id: str = "default_user",  # TODO: 从认证中获取
    service: ReportFileService = Depends(get_report_file_service)
) -> PreviewDataResponse:
    """获取预览所需数据（优化版接口）

    Args:
        file_uuid: 文件UUID
        user_id: 用户ID
        request: 请求对象
        service: 报告文件服务

    Returns:
        预览数据响应
    """
    try:
        # 获取客户端信息
        access_ip = get_client_ip(request)
        user_agent = get_user_agent(request)

        # 获取文件信息
        file_info = await service.get_file_info(file_uuid, user_id)
        if not file_info:
            raise HTTPException(status_code=404, detail="文件不存在或无访问权限")

        # 生成预览URL
        preview_url = await service.get_preview_url(
            file_uuid=file_uuid,
            user_id=user_id,
            access_ip=access_ip,
            user_agent=user_agent
        )

        # 计算过期时间
        expires_at = datetime.now() + timedelta(seconds=service.storage_service.presign_expire_seconds)

        return PreviewDataResponse(
            preview_url=preview_url,
            file_metadata=FileMetadata(
                name=file_info.original_filename,
                size=file_info.file_size,
                type="docx"
            ),
            preview_options=PreviewOptions(),
            expires_at=expires_at
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting preview data: {e}")
        raise HTTPException(status_code=500, detail="获取预览数据失败")


@router.get("/{file_uuid}/download")
async def download_report_file(
    file_uuid: str,
    request: Request,
    user_id: str = "default_user",  # TODO: 从认证中获取
    service: ReportFileService = Depends(get_report_file_service)
) -> DownloadURLResponse:
    """下载报告文件

    Args:
        file_uuid: 文件UUID
        user_id: 用户ID
        request: 请求对象
        service: 报告文件服务

    Returns:
        下载URL响应
    """
    try:
        # 获取客户端信息
        access_ip = get_client_ip(request)
        user_agent = get_user_agent(request)

        # 获取文件信息
        file_info = await service.get_file_info(file_uuid, user_id)
        if not file_info:
            raise HTTPException(status_code=404, detail="文件不存在或无访问权限")

        # 生成下载URL
        download_url = await service.get_download_url(
            file_uuid=file_uuid,
            user_id=user_id,
            access_ip=access_ip,
            user_agent=user_agent
        )

        return DownloadURLResponse(
            download_url=download_url,
            expires_in=service.storage_service.presign_expire_seconds
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting download URL: {e}")
        raise HTTPException(status_code=500, detail="获取下载URL失败")


@router.get("/{file_uuid}/metadata")
async def get_report_metadata(
    file_uuid: str,
    user_id: str = "default_user",  # TODO: 从认证中获取
    service: ReportFileService = Depends(get_report_file_service)
) -> MetadataResponse:
    """获取报告文件元数据

    Args:
        file_uuid: 文件UUID
        user_id: 用户ID
        service: 报告文件服务

    Returns:
        元数据响应
    """
    try:
        file_info = await service.get_file_info(file_uuid, user_id)
        if not file_info:
            raise HTTPException(status_code=404, detail="文件不存在或无访问权限")

        return MetadataResponse(
            file_uuid=file_info.uuid,
            filename=file_info.original_filename,
            file_size=file_info.file_size,
            file_size_human=format_file_size(file_info.file_size),
            created_at=file_info.created_at.isoformat(),
            content_type=file_info.content_type,
            supports_preview=True,
            preview_compatible=True
        )

    except Exception as e:
        logger.error(f"Error getting file metadata: {e}")
        raise HTTPException(status_code=500, detail="获取文件元数据失败")


@router.delete("/{file_uuid}")
async def delete_report_file(
    file_uuid: str,
    user_id: str = "default_user",  # TODO: 从认证中获取
    service: ReportFileService = Depends(get_report_file_service)
) -> DeleteFileResponse:
    """删除报告文件

    Args:
        file_uuid: 文件UUID
        user_id: 用户ID
        service: 报告文件服务

    Returns:
        删除响应
    """
    try:
        success = await service.delete_file(file_uuid, user_id)

        if success:
            return DeleteFileResponse(
                success=True,
                message="文件删除成功"
            )
        else:
            raise HTTPException(status_code=404, detail="文件不存在或无删除权限")

    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        raise HTTPException(status_code=500, detail="删除文件失败")
