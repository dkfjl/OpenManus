from typing import List

from fastapi import APIRouter, File, UploadFile

from app.logger import logger
from app.schema import FileUploadResponse
from app.services.file_upload_service import file_upload_service

router = APIRouter()


@router.post("/api/files/upload", response_model=FileUploadResponse)
async def upload_files_endpoint(
    upload_files: List[UploadFile] = File(..., description="上传的文件，最多5个")
) -> FileUploadResponse:
    try:
        if not upload_files:
            return FileUploadResponse(status="error", uuids=[], files=[], message="没有上传文件")
        if len(upload_files) > 5:
            return FileUploadResponse(
                status="error", uuids=[], files=[], message="上传文件数量超过限制，最多支持5个文件"
            )
        result = await file_upload_service.upload_files(upload_files)
        return result
    except Exception as e:
        logger.error(f"文件上传接口错误: {str(e)}")
        return FileUploadResponse(status="error", uuids=[], files=[], message=f"文件上传失败: {str(e)}")


@router.get("/api/files/upload-formats")
async def get_upload_formats():
    return file_upload_service.get_supported_formats()

