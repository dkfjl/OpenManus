"""
AIPPTSlide 到 PPTX 的转换服务
将 AIPPT API 返回的 JSON 数据转换为实际的 PowerPoint 文件
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from app.logger import logger
from app.services.execution_log_service import log_execution_event


class AIPPTToPPTXService:
    """AIPPTSlide JSON 到 PPTX 文件的转换服务"""

    def __init__(self):
        self.prs = None
        self.slide_count = 0

    def create_presentation(self) -> Presentation:
        """创建新的演示文稿"""
        self.prs = Presentation()
        self.slide_count = 0
        return self.prs

    def convert_slides_to_pptx(self, slides_data: List[Dict[str, Any]], output_path: str) -> dict:
        """
        将 AIPPTSlide 数据列表转换为 PPTX 文件

        Args:
            slides_data: AIPPTSlide JSON 数据列表
            output_path: 输出文件路径

        Returns:
            转换结果字典
        """
        try:
            log_execution_event(
                "aippt_to_pptx",
                "Starting AIPPTSlide to PPTX conversion",
                {"slides_count": len(slides_data), "output_path": output_path}
            )

            # 创建新的演示文稿
            self.create_presentation()

            # 处理每个 slide
            for i, slide_data in enumerate(slides_data):
                try:
                    slide_type = slide_data.get("type", "content")
                    logger.info(f"Processing slide {i+1}: {slide_type}")

                    if slide_type == "cover":
                        self._create_cover_slide(slide_data)
                    elif slide_type == "contents":
                        self._create_contents_slide(slide_data)
                    elif slide_type == "transition":
                        self._create_transition_slide(slide_data)
                    elif slide_type == "content":
                        self._create_content_slide(slide_data)
                    elif slide_type == "end":
                        self._create_end_slide(slide_data)
                    else:
                        logger.warning(f"Unknown slide type: {slide_type}, treating as content")
                        self._create_content_slide(slide_data)

                    self.slide_count += 1

                except Exception as e:
                    logger.error(f"Failed to process slide {i+1}: {e}")
                    # 继续处理下一个 slide
                    continue

            # 确保输出目录存在
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # 保存文件
            self.prs.save(output_path)

            log_execution_event(
                "aippt_to_pptx",
                "AIPPTSlide to PPTX conversion completed",
                {
                    "output_path": output_path,
                    "slides_processed": self.slide_count,
                    "file_size": output_file.stat().st_size if output_file.exists() else 0
                }
            )

            return {
                "status": "success",
                "filepath": output_path,
                "slides_processed": self.slide_count,
                "file_size": output_file.stat().st_size if output_file.exists() else 0
            }

        except Exception as e:
            logger.error(f"AIPPTSlide to PPTX conversion failed: {e}")
            log_execution_event(
                "aippt_to_pptx",
                "AIPPTSlide to PPTX conversion failed",
                {"error": str(e)}
            )
            return {
                "status": "failed",
                "filepath": output_path,
                "error": str(e)
            }

    def _create_cover_slide(self, slide_data: Dict[str, Any]):
        """创建封面页"""
        slide_layout = self.prs.slide_layouts[0]  # 标题幻灯片布局
        slide = self.prs.slides.add_slide(slide_layout)

        data = slide_data.get("data", {})
        title = data.get("title", "演示文稿")
        subtitle = data.get("text", "")

        # 设置标题
        if slide.shapes.title:
            slide.shapes.title.text = title
            title_paragraph = slide.shapes.title.text_frame.paragraphs[0]
            title_paragraph.font.size = Pt(44)
            title_paragraph.font.bold = True
            title_paragraph.alignment = PP_ALIGN.CENTER

        # 设置副标题
        if subtitle and len(slide.placeholders) > 1:
            subtitle_shape = slide.placeholders[1]
            subtitle_shape.text = subtitle
            subtitle_paragraph = subtitle_shape.text_frame.paragraphs[0]
            subtitle_paragraph.font.size = Pt(28)
            subtitle_paragraph.alignment = PP_ALIGN.CENTER

    def _create_contents_slide(self, slide_data: Dict[str, Any]):
        """创建目录页"""
        slide_layout = self.prs.slide_layouts[1]  # 标题和内容布局
        slide = self.prs.slides.add_slide(slide_layout)

        data = slide_data.get("data", {})
        title = data.get("title", "目录")
        items = data.get("items", [])

        # 设置标题
        if slide.shapes.title:
            slide.shapes.title.text = title

        # 设置目录项
        if len(slide.placeholders) > 1:
            content_shape = slide.placeholders[1]
            content_shape.text = ""
            tf = content_shape.text_frame

            for i, item in enumerate(items):
                if i > 0:
                    p = tf.add_paragraph()
                else:
                    p = tf.paragraphs[0]

                p.text = f"{i+1}. {item}"
                p.font.size = Pt(24)
                p.level = 0

    def _create_transition_slide(self, slide_data: Dict[str, Any]):
        """创建过渡页"""
        slide_layout = self.prs.slide_layouts[2]  # 节标题布局
        slide = self.prs.slides.add_slide(slide_layout)

        data = slide_data.get("data", {})
        title = data.get("title", "章节")
        text = data.get("text", "")

        # 设置标题
        if slide.shapes.title:
            slide.shapes.title.text = title
            title_paragraph = slide.shapes.title.text_frame.paragraphs[0]
            title_paragraph.font.size = Pt(40)
            title_paragraph.font.bold = True

        # 设置描述
        if text and len(slide.placeholders) > 1:
            content_shape = slide.placeholders[1]
            content_shape.text = text

    def _create_content_slide(self, slide_data: Dict[str, Any]):
        """创建内容页"""
        slide_layout = self.prs.slide_layouts[1]  # 标题和内容布局
        slide = self.prs.slides.add_slide(slide_layout)

        data = slide_data.get("data", {})
        title = data.get("title", "内容")
        items = data.get("items", [])

        # 设置标题
        if slide.shapes.title:
            slide.shapes.title.text = title

        # 设置内容项
        if len(slide.placeholders) > 1:
            content_shape = slide.placeholders[1]
            content_shape.text = ""
            tf = content_shape.text_frame

            for i, item in enumerate(items):
                if isinstance(item, dict):
                    item_title = item.get("title", "")
                    item_text = item.get("text", "")
                else:
                    item_title = str(item)
                    item_text = ""

                if i > 0:
                    p = tf.add_paragraph()
                else:
                    p = tf.paragraphs[0]

                if item_title and item_text:
                    p.text = f"• {item_title}: {item_text}"
                elif item_title:
                    p.text = f"• {item_title}"
                else:
                    p.text = f"• {item_text}"

                p.font.size = Pt(20)
                p.level = 0

                # 如果有详细文本，添加为子项
                if item_text and item_title and len(item_text) > 50:
                    detail_p = tf.add_paragraph()
                    detail_p.text = f"  {item_text}"
                    detail_p.font.size = Pt(18)
                    detail_p.level = 1

    def _create_end_slide(self, slide_data: Dict[str, Any]):
        """创建结束页"""
        slide_layout = self.prs.slide_layouts[0]  # 标题幻灯片布局
        slide = self.prs.slides.add_slide(slide_layout)

        # 设置结束页标题
        if slide.shapes.title:
            slide.shapes.title.text = "谢谢"
            title_paragraph = slide.shapes.title.text_frame.paragraphs[0]
            title_paragraph.font.size = Pt(44)
            title_paragraph.font.bold = True
            title_paragraph.alignment = PP_ALIGN.CENTER

        # 可选的副标题
        if len(slide.placeholders) > 1:
            subtitle_shape = slide.placeholders[1]
            subtitle_shape.text = "Q&A"
            subtitle_paragraph = subtitle_shape.text_frame.paragraphs[0]
            subtitle_paragraph.font.size = Pt(32)
            subtitle_paragraph.alignment = PP_ALIGN.CENTER


def convert_aippt_slides_to_pptx(slides_data: List[Dict[str, Any]], output_path: str) -> dict:
    """
    便捷函数：将 AIPPTSlide 数据转换为 PPTX 文件

    Args:
        slides_data: AIPPTSlide JSON 数据列表
        output_path: 输出文件路径

    Returns:
        转换结果字典
    """
    service = AIPPTToPPTXService()
    return service.convert_slides_to_pptx(slides_data, output_path)
