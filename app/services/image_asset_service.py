"""
图片资源服务
负责图片资源的解析、校验和获取
"""

import asyncio
from typing import Dict, Optional
from urllib.parse import urlparse

import aiohttp

from app.logger import logger
from app.services.file_upload_service import file_upload_service


class ImageAssetService:
    """图片资源解析与校验服务"""

    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=5)
        # 图库 API 配置（可扩展）
        self.unsplash_access_key = None  # TODO: 从配置读取
        self.pexels_api_key = None  # TODO: 从配置读取

    async def from_upload(self, file_uuid: str) -> Optional[str]:
        """
        基于上传文件 UUID 生成图片访问链接

        Args:
            file_uuid: 文件 UUID

        Returns:
            图片 URL，失败返回 None
        """
        try:
            # 获取文件信息
            file_info = file_upload_service.get_file_info_by_uuid(file_uuid)
            if not file_info:
                logger.warning(f"未找到 UUID 对应的文件: {file_uuid}")
                return None

            # 检查是否为图片类型
            if not file_info.type.startswith("image/"):
                logger.warning(f"文件不是图片类型: {file_info.type}")
                return None

            # TODO: 实际部署时应使用对象存储（如 S3/OSS）生成公开链接或预签名 URL
            # 当前返回本地路径占位符（需要配置静态文件服务）
            # 假设有一个静态文件服务映射 /uploads 目录
            image_url = f"/uploads/{file_info.saved_name}"

            logger.info(f"生成上传图片链接: {file_uuid} -> {image_url}")
            return image_url

        except Exception as e:
            logger.error(f"从上传文件生成图片链接失败: {str(e)}")
            return None

    async def search(
        self, topic: str, hint: Optional[str] = None, lang: str = "zh"
    ) -> Optional[str]:
        """
        从图库检索图片

        Args:
            topic: 主题关键词
            hint: 额外提示词
            lang: 语言代码

        Returns:
            图片直链，失败返回 None
        """
        try:
            # 构建搜索关键词
            query = topic
            if hint:
                query = f"{topic} {hint}"

            # TODO: 集成图库 API（Unsplash/Pexels）
            # 当前返回 None，表示暂不支持自动检索
            logger.info(f"图库检索功能尚未实现: query={query}, lang={lang}")
            return None

            # 示例：Unsplash API 集成（需要配置 API key）
            # if self.unsplash_access_key:
            #     url = await self._search_unsplash(query, lang)
            #     if url:
            #         return url

            # 示例：Pexels API 集成
            # if self.pexels_api_key:
            #     url = await self._search_pexels(query, lang)
            #     if url:
            #         return url

        except Exception as e:
            logger.error(f"图库检索失败: {str(e)}")
            return None

    async def validate(self, url: str) -> bool:
        """
        校验图片 URL 有效性

        规则：
        1. URL 必须为 https:// 绝对地址
        2. 通过 HEAD 请求校验：status=200 且 content-type 以 image/ 开头

        Args:
            url: 图片 URL

        Returns:
            是否有效
        """
        try:
            # 检查 URL 格式
            if not url:
                return False

            parsed = urlparse(url)

            # 对于本地路径（/uploads/*），暂时认为有效（TODO: 实际验证文件存在）
            if parsed.path.startswith("/uploads/"):
                # 简化处理：信任本地上传的文件
                return True

            # 必须是 https 协议（生产环境要求）
            if parsed.scheme not in ["https", "http"]:  # http 允许用于开发测试
                logger.debug(f"图片 URL 协议不符合要求: {url}")
                return False

            # HEAD 请求校验
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.head(url, allow_redirects=True) as response:
                    # 检查状态码
                    if response.status != 200:
                        logger.debug(f"图片 URL 返回非 200 状态: {response.status}")
                        return False

                    # 检查 Content-Type
                    content_type = response.headers.get("Content-Type", "").lower()
                    if not content_type.startswith("image/"):
                        logger.debug(f"URL 不是图片类型: {content_type}")
                        return False

                    return True

        except asyncio.TimeoutError:
            logger.warning(f"图片 URL 校验超时: {url}")
            return False
        except Exception as e:
            logger.warning(f"图片 URL 校验失败: {url}, {str(e)}")
            return False

    async def resolve(
        self,
        topic: str,
        substep: Optional[str] = None,
        lang: str = "zh",
        uploaded_uuid: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """
        聚合方法：解析图片资源

        优先级：
        1. 用户上传图片（如果提供了 uploaded_uuid）
        2. 图库检索（基于 topic 和 substep）
        3. 失败返回 None

        Args:
            topic: 主题
            substep: 子步骤描述
            lang: 语言
            uploaded_uuid: 上传文件的 UUID（可选）

        Returns:
            包含 imageUrl, alt, caption 的字典，失败返回 None
        """
        try:
            image_url = None

            # 优先级1：用户上传
            if uploaded_uuid:
                image_url = await self.from_upload(uploaded_uuid)
                if image_url and await self.validate(image_url):
                    return {
                        "imageUrl": image_url,
                        "alt": substep or topic,
                        "caption": f"{topic} - {substep}" if substep else topic,
                    }

            # 优先级2：图库检索
            hint = substep if substep else None
            image_url = await self.search(topic, hint, lang)
            if image_url and await self.validate(image_url):
                return {
                    "imageUrl": image_url,
                    "alt": substep or topic,
                    "caption": f"{topic} 相关图片",
                }

            # 所有方式都失败
            logger.info(f"未能解析到有效图片资源: topic={topic}, substep={substep}")
            return None

        except Exception as e:
            logger.error(f"图片资源解析失败: {str(e)}")
            return None

    # 私有方法：图库 API 集成示例（未实现）
    async def _search_unsplash(self, query: str, lang: str) -> Optional[str]:
        """从 Unsplash 检索图片"""
        # TODO: 实现 Unsplash API 调用
        return None

    async def _search_pexels(self, query: str, lang: str) -> Optional[str]:
        """从 Pexels 检索图片"""
        # TODO: 实现 Pexels API 调用
        return None


# 全局图片资源服务实例
image_asset_service = ImageAssetService()
