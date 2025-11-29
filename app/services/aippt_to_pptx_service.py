"""
AIPPTSlide 到 PPTX 的转换服务
将 AIPPT API 返回的 JSON 数据转换为实际的 PowerPoint 文件
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from app.config import config
from app.logger import logger
from app.services.execution_log_service import log_execution_event


class AIPPTToPPTXService:
    """AIPPTSlide JSON 到 PPTX 文件的转换服务"""

    # 风格颜色主题配置
    STYLE_COLORS = {
        "通用": {
            "primary": RGBColor(0, 112, 192),  # 主色调：蓝色
            "background": RGBColor(240, 240, 240),  # 背景色：浅灰
            "text": RGBColor(0, 0, 0),  # 文字色：黑色
            "accent": RGBColor(31, 78, 120),  # 强调色：深蓝
        },
        "学术风": {
            "primary": RGBColor(128, 0, 0),  # 主色调：深红
            "background": RGBColor(248, 248, 248),  # 背景色：极浅灰
            "text": RGBColor(51, 51, 51),  # 文字色：深灰
            "accent": RGBColor(165, 42, 42),  # 强调色：棕色
        },
        "职场风": {
            "primary": RGBColor(0, 51, 102),  # 主色调：深蓝
            "background": RGBColor(230, 240, 250),  # 背景色：浅蓝灰
            "text": RGBColor(0, 0, 0),  # 文字色：黑色
            "accent": RGBColor(0, 112, 192),  # 强调色：蓝色
        },
        "教育风": {
            "primary": RGBColor(0, 176, 80),  # 主色调：绿色
            "background": RGBColor(240, 250, 240),  # 背景色：浅绿
            "text": RGBColor(0, 0, 0),  # 文字色：黑色
            "accent": RGBColor(0, 137, 62),  # 强调色：深绿
        },
        "营销风": {
            "primary": RGBColor(255, 102, 0),  # 主色调：橙色
            "background": RGBColor(255, 245, 230),  # 背景色：浅橙
            "text": RGBColor(51, 51, 51),  # 文字色：深灰
            "accent": RGBColor(255, 153, 51),  # 强调色：亮橙
        },
    }

    # 风格布局配置
    STYLE_LAYOUTS = {
        "通用": {
            "cover": 0,  # 标题幻灯片
            "contents": 1,  # 标题和内容
            "transition": 2,  # 节标题
            "content": 1,  # 标题和内容
            "end": 0,  # 标题幻灯片
        },
        "学术风": {
            "cover": 0,  # 简洁标题页
            "contents": 1,
            "transition": 2,
            "content": 1,
            "end": 0,
        },
        "职场风": {
            "cover": 0,  # 专业标题页
            "contents": 1,
            "transition": 2,
            "content": 1,
            "end": 0,
        },
        "教育风": {
            "cover": 0,  # 活泼标题页
            "contents": 1,
            "transition": 2,
            "content": 1,
            "end": 0,
        },
        "营销风": {
            "cover": 0,  # 吸引人标题页
            "contents": 1,
            "transition": 2,
            "content": 1,
            "end": 0,
        },
    }

    def __init__(self, style: str = "通用"):
        self.prs = None
        self.slide_count = 0
        self.style = style
        self.colors = self._get_style_colors(style)
        self.layouts = self._get_style_layouts(style)

    def create_presentation(self) -> Presentation:
        """创建新的演示文稿"""
        self.prs = Presentation()
        self.slide_count = 0
        return self.prs

    def _get_style_colors(self, style: str) -> dict:
        """获取风格对应的颜色配置"""
        return self.STYLE_COLORS.get(style, self.STYLE_COLORS["通用"])

    def _get_style_layouts(self, style: str) -> dict:
        """获取风格对应的布局配置"""
        return self.STYLE_LAYOUTS.get(style, self.STYLE_LAYOUTS["通用"])

    def _set_solid_background(self, slide, color: RGBColor):
        """设置纯色背景"""
        try:
            background = slide.background
            fill = background.fill
            fill.solid()
            fill.fore_color.rgb = color
        except Exception as e:
            logger.warning(f"Failed to set solid background: {e}")

    def _set_gradient_background(
        self, slide, color1: RGBColor, color2: RGBColor, direction: str = "vertical"
    ):
        """设置渐变背景"""
        try:
            background = slide.background
            fill = background.fill
            fill.gradient()

            # 设置渐变类型和方向
            if direction == "vertical":
                fill.gradient_angle = 90  # 从上到下
            elif direction == "horizontal":
                fill.gradient_angle = 0  # 从左到右
            else:
                fill.gradient_angle = 90

            # 设置渐变停止点
            gradient_stops = fill.gradient_stops
            gradient_stops[0].color.rgb = color1
            gradient_stops[1].color.rgb = color2
        except Exception as e:
            logger.warning(f"Failed to set gradient background: {e}")

    def _apply_slide_background(self, slide, slide_type: str):
        """根据幻灯片类型和风格应用背景"""
        try:
            # 封面页和结束页使用渐变背景
            if slide_type in ["cover", "end"]:
                primary_color = self.colors["primary"]
                background_color = self.colors["background"]
                # 创建渐变效果：主色调到背景色
                self._set_gradient_background(
                    slide, primary_color, background_color, "vertical"
                )
            # 过渡页使用纯色背景（主色调的浅色版）
            elif slide_type == "transition":
                # 创建主色调的浅色版本：对每个通道向 255 偏移
                try:
                    pr, pg, pb = tuple(self.colors["primary"])  # RGBColor 是可迭代的
                except Exception:
                    pr, pg, pb = (0, 0, 0)
                delta = 80
                light_color = RGBColor(
                    min(255, pr + delta),
                    min(255, pg + delta),
                    min(255, pb + delta),
                )
                self._set_solid_background(slide, light_color)
            # 内容页使用纯色背景
            else:
                self._set_solid_background(slide, self.colors["background"])
        except Exception as e:
            logger.warning(f"Failed to apply slide background: {e}")

    # 样式辅助：布局与文字颜色
    def _choose_layout(self, slide_type: str):
        """按风格映射选择布局索引并安全回退。"""
        try:
            idx = int(self.layouts.get(slide_type, 1 if slide_type != "cover" else 0))
        except Exception:
            idx = 1 if slide_type != "cover" else 0
        try:
            if idx < 0 or idx >= len(self.prs.slide_layouts):
                idx = 1 if slide_type != "cover" else 0
            return self.prs.slide_layouts[idx]
        except Exception:
            return self.prs.slide_layouts[1 if slide_type != "cover" else 0]

    def _apply_text_frame_color(self, text_frame, color: RGBColor):
        try:
            if text_frame is None:
                return
            for p in list(getattr(text_frame, "paragraphs", []) or []):
                try:
                    # 段落默认字体颜色
                    pf = getattr(p, "font", None)
                    if pf and getattr(pf, "color", None):
                        p.font.color.rgb = color
                    for r in getattr(p, "runs", []) or []:
                        if getattr(r, "font", None) and getattr(r.font, "color", None):
                            r.font.color.rgb = color
                except Exception:
                    continue
        except Exception:
            pass

    def _apply_shape_text_color(self, shape, color: RGBColor):
        try:
            if getattr(shape, "has_text_frame", False):
                self._apply_text_frame_color(shape.text_frame, color)
        except Exception:
            pass

    def _disable_bullets_paragraph(self, paragraph) -> None:
        """显式关闭段落项目符号，避免模板默认 bullets。"""
        try:
            pPr = paragraph._element.get_or_add_pPr()
            # 清理已有 bullet 相关子元素
            for ch in list(pPr):
                t = ch.tag
                if t.endswith('buNone') or t.endswith('buChar') or t.endswith('buAutoNum') or t.endswith('buBlip'):
                    pPr.remove(ch)
            # 声明无项目符号
            from pptx.oxml.xmlchemy import OxmlElement
            pPr.append(OxmlElement('a:buNone'))
        except Exception:
            pass

    def convert_slides_to_pptx(
        self, slides_data: List[Dict[str, Any]], output_path: str
    ) -> dict:
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
                {
                    "slides_count": len(slides_data),
                    "output_path": output_path,
                    "style": self.style,
                },
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
                        logger.warning(
                            f"Unknown slide type: {slide_type}, treating as content"
                        )
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
                    "file_size": (
                        output_file.stat().st_size if output_file.exists() else 0
                    ),
                    "style": self.style,
                },
            )

            return {
                "status": "success",
                "filepath": output_path,
                "slides_processed": self.slide_count,
                "file_size": output_file.stat().st_size if output_file.exists() else 0,
            }

        except Exception as e:
            logger.error(f"AIPPTSlide to PPTX conversion failed: {e}")
            log_execution_event(
                "aippt_to_pptx",
                "AIPPTSlide to PPTX conversion failed",
                {"error": str(e), "style": self.style},
            )
            return {"status": "failed", "filepath": output_path, "error": str(e)}

    def _create_cover_slide(self, slide_data: Dict[str, Any]):
        """创建封面页"""
        slide_layout = self._choose_layout("cover")
        slide = self.prs.slides.add_slide(slide_layout)
        self._apply_slide_background(slide, "cover")

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
            try:
                title_paragraph.font.color.rgb = self.colors["primary"]
            except Exception:
                pass

        # 设置副标题
        if subtitle and len(slide.placeholders) > 1:
            subtitle_shape = slide.placeholders[1]
            subtitle_shape.text = subtitle
            subtitle_paragraph = subtitle_shape.text_frame.paragraphs[0]
            subtitle_paragraph.font.size = Pt(28)
            subtitle_paragraph.alignment = PP_ALIGN.CENTER
            try:
                subtitle_paragraph.font.color.rgb = self.colors["text"]
            except Exception:
                pass

    def _create_contents_slide(self, slide_data: Dict[str, Any]):
        """创建目录页"""
        slide_layout = self._choose_layout("contents")
        slide = self.prs.slides.add_slide(slide_layout)
        self._apply_slide_background(slide, "contents")

        data = slide_data.get("data", {})
        title = data.get("title", "目录")
        items = data.get("items", [])

        # 设置标题
        if slide.shapes.title:
            slide.shapes.title.text = title
            try:
                slide.shapes.title.text_frame.paragraphs[0].font.color.rgb = self.colors["primary"]
            except Exception:
                pass

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
                # 关闭 bullets，防止模板自带项目符号
                self._disable_bullets_paragraph(p)
                try:
                    p.font.color.rgb = self.colors["text"]
                except Exception:
                    pass

    def _create_transition_slide(self, slide_data: Dict[str, Any]):
        """创建过渡页"""
        slide_layout = self._choose_layout("transition")
        slide = self.prs.slides.add_slide(slide_layout)
        self._apply_slide_background(slide, "transition")

        data = slide_data.get("data", {})
        title = data.get("title", "章节")
        text = data.get("text", "")

        # 设置标题（并整体上移标题位置）
        title_shape = None
        if slide.shapes.title:
            title_shape = slide.shapes.title
            title_shape.text = title
            title_paragraph = title_shape.text_frame.paragraphs[0]
            title_paragraph.font.size = Pt(40)
            title_paragraph.font.bold = True
            try:
                title_paragraph.font.color.rgb = self.colors["primary"]
            except Exception:
                pass
            # 上移标题，使内容区可上移更多
            try:
                slide_w = self.prs.slide_width
                slide_h = self.prs.slide_height
                margin = Inches(0.8)
                title_shape.left = margin
                title_shape.width = slide_w - Inches(1.6)
                desired_title_top = int(slide_h * 0.16)  # 标题顶部约 16%
                if title_shape.top > desired_title_top:
                    title_shape.top = desired_title_top
            except Exception:
                pass

        # 删除除标题外的占位符，避免出现“单击此处添加文本”
        try:
            for ph in list(slide.placeholders):
                if title_shape and ph == title_shape:
                    continue
                # 移除非标题占位符
                try:
                    sp = ph._element
                    sp.getparent().remove(sp)
                except Exception:
                    continue
        except Exception:
            pass

        # 设置描述或要点
        items = []
        try:
            items = list((data.get("items") or []) if isinstance(data, dict) else [])
        except Exception:
            items = []

        wrote_text = False
        try:
            # 在标题下方创建文本框，保证视觉顺序为：标题 → 概述/要点
            # 并整体上移（约 30%~50%）：将内容块顶部锚定在距顶部 ~32% 处，且不穿过标题底部
            slide_w = self.prs.slide_width
            slide_h = self.prs.slide_height
            margin = Inches(0.8)
            desired_top_ratio = 0.32  # 32% 顶部锚点，满足“上移 30%-50%”的诉求
            if title_shape is not None:
                tshape = title_shape
                left = margin
                base_top = tshape.top + tshape.height + Inches(0.2)
                width = slide_w - Inches(1.6)
                # 计算期望 top，并确保不与标题重叠
                desired_top = int(slide_h * desired_top_ratio)
                min_top_after_title = tshape.top + tshape.height + Inches(0.05)
                top = max(desired_top, min_top_after_title)
            else:
                left = margin
                width = slide_w - Inches(1.6)
                top = int(slide_h * desired_top_ratio)
                top = max(top, Inches(1.2))
            height = max(Inches(1.0), slide_h - top - Inches(0.8))

            tb = slide.shapes.add_textbox(left, top, width, height)
            tf = tb.text_frame
            tf.clear()
            para_idx = 0
            if text:
                p = tf.paragraphs[0]
                p.text = str(text)
                try:
                    p.font.size = Pt(20)
                except Exception:
                    pass
                self._disable_bullets_paragraph(p)
                try:
                    p.font.color.rgb = self.colors["text"]
                except Exception:
                    pass
                para_idx += 1
            for idx, it in enumerate(items, start=1):
                t = it.get("title") if isinstance(it, dict) else str(it)
                if not t:
                    continue
                p = tf.add_paragraph() if para_idx > 0 else tf.paragraphs[0]
                p.text = f"{idx}. {t}"
                try:
                    p.font.size = Pt(18)
                except Exception:
                    pass
                self._disable_bullets_paragraph(p)
                try:
                    p.font.color.rgb = self.colors["text"]
                except Exception:
                    pass
                para_idx += 1
            wrote_text = para_idx > 0
        except Exception:
            wrote_text = False

        if not wrote_text and not text:
            # 无描述/要点时，添加强调色横条作装饰（位置随上移策略相应上移）
            try:
                slide_w = self.prs.slide_width
                bar_left = Inches(0.6)
                bar_top = max(Inches(1.6), top + Inches(0.2))
                bar_width = slide_w - Inches(1.2)
                bar_height = Inches(0.25)
                from pptx.enum.shapes import MSO_SHAPE
                deco = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, bar_left, bar_top, bar_width, bar_height)
                deco.fill.solid()
                deco.fill.fore_color.rgb = self.colors["accent"]
                try:
                    deco.line.fill.background()
                except Exception:
                    pass
            except Exception:
                pass

    def _create_content_slide(self, slide_data: Dict[str, Any]):
        """创建内容页"""
        slide_layout = self._choose_layout("content")
        slide = self.prs.slides.add_slide(slide_layout)
        self._apply_slide_background(slide, "content")

        data = slide_data.get("data", {})
        title = data.get("title", "内容")
        items = data.get("items", [])

        # 设置标题
        if slide.shapes.title:
            slide.shapes.title.text = title
            try:
                slide.shapes.title.text_frame.paragraphs[0].font.color.rgb = self.colors["primary"]
            except Exception:
                pass

        # 将 items 分类：文本、图片、表格
        text_items: list = []
        image_items: list = []
        table_items: list = []
        for it in items:
            if isinstance(it, dict) and it.get("type") in ("image", "table"):
                if it.get("type") == "image":
                    image_items.append(it)
                else:
                    table_items.append(it)
            else:
                text_items.append(it)

        # 文本要点写入内容占位（统一样式：字号一致、左对齐、无缩进、自动换行）
        if len(slide.placeholders) > 1:
            content_shape = slide.placeholders[1]
            content_shape.text = ""
            tf = content_shape.text_frame
            try:
                tf.word_wrap = True
                # 统一左右边距，避免模板默认缩进
                tf.margin_left = Inches(0.2)
                tf.margin_right = Inches(0.2)
            except Exception:
                pass

            def _style_paragraph(p, size_pt=20):
                try:
                    p.level = 0
                except Exception:
                    pass
                try:
                    p.alignment = PP_ALIGN.LEFT
                except Exception:
                    pass
                try:
                    p.font.size = Pt(size_pt)
                    p.font.color.rgb = self.colors["text"]
                except Exception:
                    pass
                self._disable_bullets_paragraph(p)

            for i, item in enumerate(text_items):
                # 支持 dict 带 text/case；否则按字符串回退
                if isinstance(item, dict):
                    item_title = (item.get("title") or "").strip()
                    item_text = (item.get("text") or "").strip()
                    item_case = (item.get("case") or "").strip()
                else:
                    item_title = str(item)
                    item_text = ""
                    item_case = ""

                # 第一段：正文 text（不少于 50 字由第二步保证），与标题合并展示更紧凑
                p = tf.add_paragraph() if i > 0 else tf.paragraphs[0]
                if item_title and item_text:
                    p.text = f"{item_title}：{item_text}"
                elif item_title:
                    p.text = item_title
                else:
                    p.text = item_text
                _style_paragraph(p, size_pt=20)

                # 第二段：案例 case（与正文同字号、同样式；自动换行）
                if item_case:
                    p2 = tf.add_paragraph()
                    p2.text = item_case
                    _style_paragraph(p2, size_pt=20)

        # 计算右侧区域用于放置图片/表格
        slide_w = self.prs.slide_width
        slide_h = self.prs.slide_height
        margin = Inches(0.5)
        right_left = int(slide_w * 0.55)
        right_top = int(slide_h * 0.25)
        right_w = slide_w - right_left - margin
        block_h = int(slide_h * 0.5)

        # 帮助函数：解析图片源
        def _resolve_image_source(
            item: Dict[str, Any],
        ) -> Tuple[io.BytesIO | str | None, str]:
            # 返回 (image_file_or_stream, hint)
            # 优先使用 path；其次 base64；url 仅作为占位提示
            path = item.get("path") or item.get("file") or item.get("local_path")
            if isinstance(path, str) and path:
                p = Path(path)
                if not p.is_absolute():
                    p = (config.workspace_root / p).resolve()
                if p.exists():
                    return str(p), str(p)
            b64 = item.get("base64")
            if isinstance(b64, str) and b64:
                try:
                    raw = base64.b64decode(b64)
                    return io.BytesIO(raw), "base64"
                except Exception:
                    pass
            url = item.get("url")
            if isinstance(url, str) and url:
                try:
                    resp = requests.get(url, timeout=8)
                    if resp.status_code == 200:
                        ctype = resp.headers.get("content-type", "")
                        if ctype.startswith("image/") and resp.content:
                            return io.BytesIO(resp.content), url
                except Exception:
                    pass
            return None, str(url or "")

        # 插入图片
        cursor_top = right_top
        for img in image_items[:2]:  # 控制数量，避免过度拥挤
            pic_src, hint = _resolve_image_source(img)
            title = img.get("title") or "图片"
            caption = img.get("caption") or hint
            try:
                if pic_src is None:
                    # 回退为文本提示
                    if len(slide.placeholders) > 1:
                        tf = slide.placeholders[1].text_frame
                        p = tf.add_paragraph()
                        # 不使用项目符号
                        p.text = f"{title}: {caption}"
                        p.font.size = Pt(18)
                        p.level = 0
                        self._disable_bullets_paragraph(p)
                        try:
                            p.font.color.rgb = self.colors["text"]
                        except Exception:
                            pass
                else:
                    pic = slide.shapes.add_picture(
                        pic_src, right_left, cursor_top, width=int(right_w)
                    )
                    cursor_top = min(
                        cursor_top + pic.height + Inches(0.2), int(slide_h - block_h)
                    )
            except Exception as e:
                logger.warning(f"Failed to add image to slide: {e}")

        # 插入表格
        for tbl in table_items[:1]:  # 每页最多一个表格
            headers = tbl.get("headers") or []
            rows = tbl.get("rows") or []
            try:
                cols = max(len(headers), max((len(r) for r in rows), default=0))
                rows_count = len(rows) + (1 if headers else 0)
                if cols > 0 and rows_count > 0:
                    table_shape = slide.shapes.add_table(
                        rows_count, cols, right_left, cursor_top, right_w, block_h
                    )
                    table = table_shape.table
                    # 头部
                    r_idx = 0
                    if headers:
                        for c, val in enumerate(headers[:cols]):
                            cell = table.cell(0, c)
                            cell.text = str(val)
                            # 头部单元格填充主色并设置白色文字
                            try:
                                cell.fill.solid()
                                cell.fill.fore_color.rgb = self.colors["primary"]
                                ph = cell.text_frame.paragraphs[0]
                                ph.font.bold = True
                                ph.font.color.rgb = RGBColor(255, 255, 255)
                            except Exception:
                                # 至少加粗
                                cell.text_frame.paragraphs[0].font.bold = True
                        r_idx = 1
                    # 数据
                    for r in rows[: rows_count - r_idx]:
                        for c in range(cols):
                            val = r[c] if c < len(r) else ""
                            cell = table.cell(r_idx, c)
                            cell.text = str(val)
                            try:
                                cell.text_frame.paragraphs[0].font.color.rgb = self.colors["text"]
                            except Exception:
                                pass
                        r_idx += 1
            except Exception as e:
                logger.warning(f"Failed to add table to slide: {e}")

    def _create_end_slide(self, slide_data: Dict[str, Any]):
        """创建结束页"""
        slide_layout = self._choose_layout("end")
        slide = self.prs.slides.add_slide(slide_layout)
        self._apply_slide_background(slide, "end")

        # 设置结束页标题
        if slide.shapes.title:
            slide.shapes.title.text = "谢谢"
            title_paragraph = slide.shapes.title.text_frame.paragraphs[0]
            title_paragraph.font.size = Pt(44)
            title_paragraph.font.bold = True
            title_paragraph.alignment = PP_ALIGN.CENTER
            try:
                title_paragraph.font.color.rgb = self.colors["primary"]
            except Exception:
                pass

        # 可选的副标题
        if len(slide.placeholders) > 1:
            subtitle_shape = slide.placeholders[1]
            subtitle_shape.text = "Q&A"
            subtitle_paragraph = subtitle_shape.text_frame.paragraphs[0]
            subtitle_paragraph.font.size = Pt(32)
            subtitle_paragraph.alignment = PP_ALIGN.CENTER
            try:
                subtitle_paragraph.font.color.rgb = self.colors["text"]
            except Exception:
                pass


def convert_aippt_slides_to_pptx(
    slides_data: List[Dict[str, Any]], output_path: str, style: str = "通用"
) -> dict:
    """
    便捷函数：将 AIPPTSlide 数据转换为 PPTX 文件

    Args:
        slides_data: AIPPTSlide JSON 数据列表
        output_path: 输出文件路径
        style: PPT 风格（通用/学术风/职场风/教育风/营销风）

    Returns:
        转换结果字典
    """
    service = AIPPTToPPTXService(style=style)
    return service.convert_slides_to_pptx(slides_data, output_path)
