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
from urllib.parse import urlparse

import requests
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
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
        # 品牌：皇家深蓝（Royal & Navy Blue）- 高级深色版
        "皇家深蓝": {
            "primary": RGBColor(255, 215, 0),  # 金色标题 (Gold)
            "background": RGBColor(5, 20, 40),  # 深邃午夜蓝 (Midnight Blue)
            "text": RGBColor(230, 230, 230),  # 银灰/米白正文 (Silver/Off-white)
            "accent": RGBColor(212, 175, 55),  # 这里的 accent 也用金色或稍暗的金
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
        "皇家深蓝": {
            "cover": 0,
            "contents": 1,
            "transition": 2,
            "content": 1,
            "end": 0,
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
        # 记录每个 transition 下 content 的序号（用于三种版式轮换）
        self._section_variant_seq = 0

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
        self,
        slide,
        color1: RGBColor,
        color2: RGBColor,
        direction: str = "vertical",  # vertical | horizontal | diagonal | diagonal_rev
    ):
        """设置渐变背景

        direction:
          - vertical: 自上而下
          - horizontal: 自左而右
          - diagonal: 左上到右下（45°）
        """
        try:
            background = slide.background
            fill = background.fill
            fill.gradient()

            # 设置渐变方向
            if direction == "vertical":
                fill.gradient_angle = 90
            elif direction == "horizontal":
                fill.gradient_angle = 0
            elif direction == "diagonal":
                fill.gradient_angle = 45
            elif direction == "diagonal_rev":
                fill.gradient_angle = 135
            else:
                fill.gradient_angle = 90

            # 设置渐变停止点
            gradient_stops = fill.gradient_stops
            gradient_stops[0].color.rgb = color1
            gradient_stops[1].color.rgb = color2
        except Exception as e:
            logger.warning(f"Failed to set gradient background: {e}")

    # ---------- 颜色辅助 ----------
    def _rgb_tuple(self, c: RGBColor) -> tuple[int, int, int]:
        try:
            r, g, b = int(c[0]), int(c[1]), int(c[2])
            return r, g, b
        except Exception:
            return (0, 0, 0)

    def _clamp(self, v: int) -> int:
        return 0 if v < 0 else 255 if v > 255 else v

    def _lighten(self, c: RGBColor, delta: int) -> RGBColor:
        r, g, b = self._rgb_tuple(c)
        return RGBColor(
            self._clamp(r + delta), self._clamp(g + delta), self._clamp(b + delta)
        )

    def _darken(self, c: RGBColor, delta: int) -> RGBColor:
        r, g, b = self._rgb_tuple(c)
        return RGBColor(
            self._clamp(r - delta), self._clamp(g - delta), self._clamp(b - delta)
        )

    def _mix(self, a: RGBColor, b: RGBColor, ratio: float = 0.5) -> RGBColor:
        ratio = max(0.0, min(1.0, ratio))
        ar, ag, ab = self._rgb_tuple(a)
        br, bg, bb = self._rgb_tuple(b)
        mr = int(ar * (1 - ratio) + br * ratio)
        mg = int(ag * (1 - ratio) + bg * ratio)
        mb = int(ab * (1 - ratio) + bb * ratio)
        return RGBColor(self._clamp(mr), self._clamp(mg), self._clamp(mb))

    def _apply_transition_background(self, slide):
        """按不同风格为过渡页设置专属渐变背景，避免与 cover/end 相同视觉。

        规则：
        - 通用：accent → 主色浅化，45° 对角渐变
        - 学术风：accent（棕）→ 主色浅化（深红），水平渐变
        - 职场风：accent（蓝）→ 主色浅化（深蓝），135° 对角渐变
        - 教育风：accent（深绿）→ 背景混合主色，水平渐变
        - 营销风：accent（亮橙）→ 主色大幅浅化，45° 对角渐变
        """
        primary = self.colors.get("primary")
        background = self.colors.get("background")
        accent = self.colors.get("accent", primary)

        style = self.style or "通用"
        try:
            # 品牌：皇家深蓝（支持中英文别名）
            if style in (
                "皇家深蓝",
                "RoyalNavy",
                "Royal & Navy",
                "Royal Navy",
                "RoyalNavyBlue",
            ):
                # 保持深色背景，使用微弱的径向或对角渐变来突出中心
                start = background
                end = self._lighten(background, 15)  # 稍微亮一点的深蓝
                self._set_gradient_background(slide, start, end, direction="diagonal")
            elif style == "学术风":
                end = self._lighten(primary, 40)
                self._set_gradient_background(
                    slide, accent, end, direction="horizontal"
                )
            elif style == "职场风":
                end = self._lighten(primary, 50)
                self._set_gradient_background(
                    slide, accent, end, direction="diagonal_rev"
                )
            elif style == "教育风":
                end = self._mix(primary, background, 0.35)
                end = self._lighten(end, 20)
                self._set_gradient_background(
                    slide, accent, end, direction="horizontal"
                )
            elif style == "营销风":
                end = self._lighten(primary, 80)
                self._set_gradient_background(slide, accent, end, direction="diagonal")
            else:  # 通用 & 其他
                end = self._lighten(primary, 60)
                self._set_gradient_background(slide, accent, end, direction="diagonal")
        except Exception as e:
            logger.warning(
                f"Failed to apply transition gradient for style {style}: {e}"
            )
            # 回退到默认通用方案
            end = self._lighten(primary, 60)
            self._set_gradient_background(slide, accent, end, direction="diagonal")

    # ---------- Z-Order helpers ----------
    def _send_shape_to_back(self, slide, shape) -> None:
        """将形状发送到最底层，避免遮挡标题/正文。

        说明：python-pptx 未公开 z-order API，这里通过操作 `_spTree` 完成。
        在多数模板下可稳定工作，用于本项目的装饰性几何图形足够。
        """
        try:
            sp = shape._element  # noqa: SLF001 - 使用私有接口以调整图层
            tree = slide.shapes._spTree  # noqa: SLF001
            tree.remove(sp)
            tree.insert(0, sp)  # 放到最底层
        except Exception:
            # 静默失败，避免生成流程中断
            pass

    def _add_royal_decorations(self, slide, slide_type: str):
        """
        为“皇家深蓝”风格添加高级几何图案装饰
        """
        try:
            slide_w = self.prs.slide_width
            slide_h = self.prs.slide_height
            gold = self.colors.get("accent")  # Gold
            # 辅助色：半透明白/蓝

            # 通用：所有页面添加极淡的角落光晕（模拟高级质感）
            # 实际上 geometry shape 更好控制

            if slide_type == "cover":
                # 封面：右上角深蓝切角 + 左侧金色细线 + 底部梯形呼应

                # 1) 右上角三角形（减小尺寸并置底，避免遮挡标题）
                tri_w = int(slide_w * 0.45)
                tri_h = int(slide_h * 0.85)
                tri_l = slide_w - tri_w
                tri_t = 0
                shape = slide.shapes.add_shape(
                    MSO_SHAPE.RIGHT_TRIANGLE,
                    tri_l,
                    tri_t,
                    tri_w,
                    tri_h,
                )
                shape.horizontal_flip = True
                shape.vertical_flip = True
                shape.fill.solid()
                shape.fill.fore_color.rgb = RGBColor(10, 30, 60)
                shape.fill.transparency = 0.45
                try:
                    shape.line.fill.background()
                except Exception:
                    pass
                # 放到最底层，确保不覆盖标题/副标题
                self._send_shape_to_back(slide, shape)

                # 2) 左侧金色细线（与左对齐标题呼应）
                line = slide.shapes.add_shape(
                    MSO_SHAPE.RECTANGLE,
                    Inches(1.0),
                    int(slide_h * 0.3),
                    Inches(0.05),
                    int(slide_h * 0.25),
                )
                line.fill.solid()
                line.fill.fore_color.rgb = gold
                try:
                    line.line.fill.background()
                except Exception:
                    pass

                # 3) 底部梯形（贴合底边并适度出血，亦置底）
                trap_h = int(slide_h * 0.22)
                trap_w = int(slide_w * 0.45)
                trap_l = -Inches(0.6)
                trap_t = slide_h - trap_h
                shape2 = slide.shapes.add_shape(
                    MSO_SHAPE.TRAPEZOID,
                    trap_l,
                    trap_t,
                    trap_w,
                    trap_h,
                )
                shape2.fill.solid()
                shape2.fill.fore_color.rgb = RGBColor(30, 50, 90)
                shape2.fill.transparency = 0.5
                try:
                    shape2.line.fill.background()
                except Exception:
                    pass
                self._send_shape_to_back(slide, shape2)

            elif slide_type == "transition":
                # 过渡页：中心菱形边框或背景纹理

                # 中心大菱形 (减小尺寸，避免遮挡内容)
                sz = int(slide_h * 0.5)
                left = (slide_w - sz) // 2
                top = (slide_h - sz) // 2
                diamond = slide.shapes.add_shape(MSO_SHAPE.DIAMOND, left, top, sz, sz)
                diamond.fill.solid()
                diamond.fill.fore_color.rgb = RGBColor(255, 255, 255)
                diamond.fill.transparency = 0.95  # 极淡
                diamond.line.color.rgb = gold
                diamond.line.width = Pt(1.5)

            elif slide_type == "content" or slide_type == "contents":
                # 内容页/目录页：顶部标题栏装饰 + 底部页脚条

                # 顶部标题下方的金色细长条
                header_line = slide.shapes.add_shape(
                    MSO_SHAPE.RECTANGLE,
                    Inches(0.5),
                    Inches(1.3),  # 标题通常在 0.5-1.2 左右
                    slide_w - Inches(1.0),
                    Pt(2),
                )
                header_line.fill.solid()
                header_line.fill.fore_color.rgb = gold
                header_line.line.fill.background()

                # 右上角几何点缀（缩小并推向右上角，避免遮挡标题）
                acc = slide.shapes.add_shape(
                    MSO_SHAPE.ISOSCELES_TRIANGLE,
                    slide_w - Inches(1.0),
                    -Inches(0.4),
                    Inches(1.2),
                    Inches(1.2),
                )
                acc.fill.solid()
                acc.fill.fore_color.rgb = RGBColor(255, 255, 255)
                acc.fill.transparency = 0.95
                acc.line.fill.background()

            elif slide_type == "end":
                # 结束页：呼应封面的几何
                # 中心圆形
                circle = slide.shapes.add_shape(
                    MSO_SHAPE.OVAL,
                    (slide_w - Inches(4)) // 2,
                    (slide_h - Inches(4)) // 2,
                    Inches(4),
                    Inches(4),
                )
                circle.fill.background()  # 无填充
                circle.line.color.rgb = gold
                circle.line.width = Pt(2)

        except Exception as e:
            logger.warning(f"Failed to add royal decorations: {e}")

    def _apply_slide_background(self, slide, slide_type: str):
        """根据幻灯片类型和风格应用背景"""
        try:
            # 封面页和结束页使用渐变背景
            if slide_type in ["cover", "end"]:
                primary_color = self.colors["primary"]
                background_color = self.colors["background"]

                # 皇家深蓝特殊处理：封面背景不使用简单的 Primary->BG 渐变，而是保持深色质感
                if self.style == "皇家深蓝":
                    # 使用深色微渐变 (Deep Navy -> Slightly Lighter Navy)
                    c1 = background_color
                    c2 = self._lighten(background_color, 20)
                    self._set_gradient_background(slide, c1, c2, "diagonal")
                else:
                    # 创建渐变效果：主色调到背景色
                    self._set_gradient_background(
                        slide, primary_color, background_color, "vertical"
                    )
            # 过渡页使用与封面/结束不同的渐变背景（分风格）
            elif slide_type == "transition":
                self._apply_transition_background(slide)
            # 内容页使用纯色背景
            else:
                self._set_solid_background(slide, self.colors["background"])

            # 应用高级装饰图案（仅限皇家深蓝）
            if self.style == "皇家深蓝":
                self._add_royal_decorations(slide, slide_type)

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

    # 统一设置字体名称（按候选依次尝试）
    def _set_font_name(self, font, candidates: list[str]):
        for name in candidates:
            try:
                font.name = name
                return
            except Exception:
                continue

    def _disable_bullets_paragraph(self, paragraph) -> None:
        """显式关闭段落项目符号，避免模板默认 bullets。"""
        try:
            pPr = paragraph._element.get_or_add_pPr()
            # 清理已有 bullet 相关子元素
            for ch in list(pPr):
                t = ch.tag
                if (
                    t.endswith("buNone")
                    or t.endswith("buChar")
                    or t.endswith("buAutoNum")
                    or t.endswith("buBlip")
                ):
                    pPr.remove(ch)
            # 声明无项目符号
            from pptx.oxml.xmlchemy import OxmlElement

            pPr.append(OxmlElement("a:buNone"))
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
                # 皇家深蓝使用白色或金色标题
                title_paragraph.font.color.rgb = self.colors["primary"]
            except Exception:
                pass

            # 皇家深蓝：左对齐布局，配合左侧线条装饰
            if self.style == "皇家深蓝":
                slide.shapes.title.left = Inches(1.5)
                slide.shapes.title.width = self.prs.slide_width - Inches(2.0)
                slide.shapes.title.top = int(self.prs.slide_height * 0.35)
                title_paragraph.alignment = PP_ALIGN.LEFT
                # 增强字体
                self._set_font_name(
                    title_paragraph.font, ["PingFang SC Semibold", "Microsoft YaHei UI"]
                )

        # 设置副标题
        if subtitle and len(slide.placeholders) > 1:
            subtitle_shape = slide.placeholders[1]
            subtitle_shape.text = subtitle
            subtitle_paragraph = subtitle_shape.text_frame.paragraphs[0]
            subtitle_paragraph.font.size = Pt(28)
            subtitle_paragraph.alignment = PP_ALIGN.CENTER

            # 皇家深蓝：左对齐
            if self.style == "皇家深蓝":
                subtitle_paragraph.alignment = PP_ALIGN.LEFT
                subtitle_shape.left = Inches(1.5)
                subtitle_shape.width = self.prs.slide_width - Inches(2.0)
                try:
                    # 将副标题移至主标题下方，避免顶部出现内容
                    title_bottom = slide.shapes.title.top + slide.shapes.title.height
                    subtitle_shape.top = title_bottom + Inches(0.25)
                    # 降低存在感：小一号且更柔和的灰白
                    subtitle_paragraph.font.size = Pt(20)
                    subtitle_paragraph.font.color.rgb = RGBColor(200, 200, 200)
                except Exception:
                    pass

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

        # 皇家深蓝：调整标题位置
        if self.style == "皇家深蓝" and slide.shapes.title:
            slide.shapes.title.top = Inches(0.5)
            slide.shapes.title.left = Inches(0.5)
            slide.shapes.title.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT
        items = data.get("items", [])

        # 设置标题
        if slide.shapes.title:
            slide.shapes.title.text = title
            try:
                ph = slide.shapes.title.text_frame.paragraphs[0]
                ph.font.color.rgb = self.colors["primary"]
                ph.font.size = Pt(32)
                ph.font.bold = True
                # 标题字体优先序（中文环境）
                ph.font.name = "PingFang SC Semibold"
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

        # 设置标题（整体下移，增强层次）
        title_shape = None
        if slide.shapes.title:
            title_shape = slide.shapes.title
            title_shape.text = title
            title_paragraph = title_shape.text_frame.paragraphs[0]
            title_paragraph.font.size = Pt(42)
            title_paragraph.font.bold = True
            try:
                title_paragraph.font.color.rgb = self.colors["primary"]
            except Exception:
                pass
            # 下移标题，使其更靠近视觉中心
            try:
                slide_w = self.prs.slide_width
                slide_h = self.prs.slide_height
                margin = Inches(0.8)
                title_shape.left = margin
                title_shape.width = slide_w - Inches(1.6)
                desired_title_top = int(slide_h * 0.24)  # 标题顶部约 24%
                title_shape.top = desired_title_top
                # 更高级中文字体（候选顺序）
                self._set_font_name(
                    title_paragraph.font,
                    [
                        "Source Han Sans SC Bold",
                        "PingFang SC Semibold",
                        "Microsoft YaHei UI",
                        "Noto Sans CJK SC",
                        "Microsoft YaHei",
                    ],
                )
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
            # 在标题下方创建文本框，视觉顺序：标题 → 要点
            slide_w = self.prs.slide_width
            slide_h = self.prs.slide_height
            margin = Inches(0.8)
            if title_shape is not None:
                left = margin
                width = slide_w - Inches(1.6)
                # 重新计算安全间距：标题底部 + 0.4英寸（约1cm）安全间距
                top = title_shape.top + title_shape.height + Inches(0.8)
            else:
                left = margin
                width = slide_w - Inches(1.6)
                top = int(slide_h * 0.34)
            height = max(Inches(1.0), slide_h - top - Inches(0.9))

            tb = slide.shapes.add_textbox(left, top, width, height)
            tf = tb.text_frame
            tf.clear()
            para_idx = 0
            for idx, it in enumerate(items, start=1):
                t = it.get("title") if isinstance(it, dict) else str(it)
                if not t:
                    continue
                p = tf.add_paragraph() if para_idx > 0 else tf.paragraphs[0]
                p.text = f"{idx}. {t}"
                try:
                    p.font.size = Pt(20)
                    p.line_spacing = 1.18
                    p.space_after = Pt(2)
                    p.font.color.rgb = self.colors["text"]
                    self._set_font_name(
                        p.font,
                        [
                            "Source Han Sans SC",
                            "PingFang SC",
                            "Microsoft YaHei UI",
                            "Noto Sans CJK SC",
                            "Microsoft YaHei",
                        ],
                    )
                except Exception:
                    pass
                self._disable_bullets_paragraph(p)
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

                deco = slide.shapes.add_shape(
                    MSO_SHAPE.RECTANGLE, bar_left, bar_top, bar_width, bar_height
                )
                deco.fill.solid()
                deco.fill.fore_color.rgb = self.colors["accent"]
                try:
                    deco.line.fill.background()
                except Exception:
                    pass
            except Exception:
                pass

        # 每到一个 transition，重置内容版式轮换计数
        try:
            self._section_variant_seq = 0
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
                ph = slide.shapes.title.text_frame.paragraphs[0]
                ph.font.color.rgb = self.colors["primary"]
                ph.font.size = Pt(32)
                ph.font.bold = True
                self._set_font_name(
                    ph.font,
                    [
                        "Source Han Sans SC Bold",
                        "PingFang SC Semibold",
                        "Microsoft YaHei UI",
                        "Noto Sans CJK SC",
                        "Microsoft YaHei",
                    ],
                )

                # 皇家深蓝：标题左对齐，调整位置
                if self.style == "皇家深蓝":
                    slide.shapes.title.left = Inches(0.5)
                    slide.shapes.title.top = Inches(0.5)
                    slide.shapes.title.width = self.prs.slide_width - Inches(1.0)
                    slide.shapes.title.height = Inches(1.0)
                    ph.alignment = PP_ALIGN.LEFT
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

        # 为 content 轮换三种版式（每个 transition 重置序列）
        try:
            variant = int(getattr(self, "_section_variant_seq", 0)) % 3
            self._section_variant_seq = (
                int(getattr(self, "_section_variant_seq", 0)) + 1
            )
        except Exception:
            variant = 0

        slide_w = self.prs.slide_width
        slide_h = self.prs.slide_height
        margin = Inches(0.5)
        # 调整列宽比例：左侧文本区65%，右侧媒体区35%
        text_left_left = margin
        text_left_w = int(slide_w * 0.65) - margin
        right_left = int(slide_w * 0.65)
        right_top = int(slide_h * 0.24)
        right_w = slide_w - right_left - margin
        block_h = int(slide_h * 0.5)

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

            # 根据版式变更文字区域与媒体区域位置
            try:
                if variant == 0:
                    # 第一张：左文右图（默认）
                    content_shape.left = text_left_left
                    content_shape.top = int(slide_h * 0.26)
                    content_shape.width = text_left_w
                    content_shape.height = slide_h - content_shape.top - Inches(1.0)
                elif variant == 1:
                    # 第二张：右文左图（镜像布局），与第一张区分
                    left_media_w = int(slide_w * 0.30)  # 左侧媒体区30%
                    right_text_left = left_media_w + Inches(0.8)
                    content_shape.left = right_text_left
                    content_shape.top = int(slide_h * 0.24)
                    content_shape.width = slide_w - right_text_left - margin
                    content_shape.height = slide_h - content_shape.top - Inches(1.0)
                    # 更新媒体区到左侧
                    right_left = margin
                    right_w = left_media_w - margin
                else:  # variant == 2
                    # 第三张：竖直排版，占据左半区；右半留白（不放媒体）
                    content_shape.left = text_left_left
                    content_shape.top = int(slide_h * 0.22)
                    content_shape.width = int(slide_w * 0.7) - margin
                    content_shape.height = slide_h - content_shape.top - Inches(1.0)
                    # 禁用媒体区
                    right_w = 0
                    right_left = slide_w
            except Exception:
                pass

            def _style_paragraph(p, size_pt=18):  # 减小字体到18pt
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
                    p.line_spacing = 1.2
                    p.space_after = Pt(2)
                    self._set_font_name(
                        p.font,
                        [
                            "Source Han Sans SC",
                            "PingFang SC",
                            "Microsoft YaHei UI",
                            "Noto Sans CJK SC",
                            "Microsoft YaHei",
                        ],
                    )
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
                _style_paragraph(p, size_pt=18)  # 使用18pt字体

                # 第二段：案例 case（与正文同字号、同样式；自动换行）
                if item_case:
                    p2 = tf.add_paragraph()
                    p2.text = item_case
                    _style_paragraph(p2, size_pt=18)  # 使用18pt字体

        # 根据 variant 计算右侧区域用于放置图片/表格（参数已在上方初始化/调整）

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
                    # Some sites enable anti-hotlink; add UA + Referer
                    parsed = urlparse(url)
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
                        "Referer": f"{parsed.scheme}://{parsed.netloc}/",
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    }
                    resp = requests.get(url, headers=headers, timeout=8)
                    if resp.status_code == 200:
                        ctype = resp.headers.get("content-type", "")
                        # Accept when content-type is image/*; otherwise try to sniff via PIL
                        if resp.content:
                            if ctype.startswith("image/"):
                                return io.BytesIO(resp.content), url
                            # Try sniffing bytes to tolerate servers that misreport content-type
                            try:
                                img_buf = io.BytesIO(resp.content)
                                img_buf.seek(0)
                                Image.open(img_buf).verify()  # raises if not an image
                                img_buf.seek(0)
                                return img_buf, url
                            except Exception:
                                pass
                except Exception:
                    pass
            return None, str(url or "")

        # 插入图片（variant==2 留白，不插入媒体）
        cursor_top = right_top
        imgs = image_items[:2] if right_w > 0 else []

        def _measure_scaled_height(src, target_w: int) -> int:
            try:
                if isinstance(src, io.BytesIO):
                    src.seek(0)
                    with Image.open(src) as im:
                        w, h = im.size
                elif isinstance(src, str):
                    with Image.open(src) as im:
                        w, h = im.size
                else:
                    return 0
                if w <= 0 or h <= 0:
                    return 0
                scale = float(target_w) / float(w)
                return int(h * scale)
            except Exception:
                return 0

        # 预估需要的高度并在两张图时进行自适应缩放，确保不越界
        measured: List[Tuple[io.BytesIO | str | None, str, int]] = (
            []
        )  # (src, hint, est_height)
        spacing = Inches(0.2)
        for img in imgs:
            pic_src, hint = _resolve_image_source(img)
            est_h = (
                _measure_scaled_height(pic_src, int(right_w))
                if pic_src is not None
                else 0
            )
            measured.append((pic_src, hint, est_h))

        # 如果两张图高度总和超过可用高度，则按比例缩小宽度
        if len(measured) == 2 and right_w > 0:
            avail_h = int(block_h)
            total_h = sum(max(0, h) for _, _, h in measured) + int(spacing)
            if total_h > avail_h and total_h > 0:
                scale = max(0.3, float(avail_h - int(spacing)) / float(total_h))
                right_w = int(right_w * scale)

        # 底线：不允许超出右侧可用块的底部
        max_bottom = int(right_top + block_h)

        def _shorten_hint(h: str) -> str:
            try:
                if not h:
                    return "图片不可用"
                p = urlparse(h)
                if p.scheme and p.netloc:
                    last = (p.path or "/").rstrip("/").split("/")[-1]
                    last = last[:40] + ("…" if len(last) > 40 else "")
                    return f"{p.netloc}/{last}" if last else p.netloc
                return h[:50] + ("…" if len(h) > 50 else "")
            except Exception:
                return (h or "")[:50]

        for pic_src, hint, _ in measured:
            title = "图片"
            caption = _shorten_hint(hint)
            try:
                if pic_src is None:
                    # 在右侧媒体区添加占位文本框，不污染正文区
                    try:
                        tb = slide.shapes.add_textbox(
                            right_left, cursor_top, int(right_w), Inches(0.9)
                        )
                        tf = tb.text_frame
                        tf.clear()
                        p = tf.paragraphs[0]
                        p.text = f"{title}: {caption}"
                        p.font.size = Pt(14)
                        p.level = 0
                        self._disable_bullets_paragraph(p)
                        try:
                            p.font.color.rgb = self.colors["text"]
                        except Exception:
                            pass
                        cursor_top = cursor_top + int(tb.height) + int(spacing)
                    except Exception:
                        # 静默跳过
                        pass
                else:
                    pic = slide.shapes.add_picture(
                        pic_src, right_left, cursor_top, width=int(right_w)
                    )
                    cursor_top = cursor_top + pic.height + int(spacing)
                    if cursor_top > max_bottom:
                        # 超界时，将图片顶到下边界，并停止继续插入
                        overflow = cursor_top - max_bottom
                        # 简单纠偏：上移超出的距离（不重新缩放，避免二次质量损失）
                        try:
                            pic.top = max(right_top, pic.top - overflow)
                        except Exception:
                            pass
                        break
            except Exception as e:
                logger.warning(f"Failed to add image to slide: {e}")

        # 插入表格（variant==2 留白，不插入媒体）
        for tbl in table_items[:1] if right_w > 0 else []:  # 每页最多一个表格
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
                                if self.style == "皇家深蓝":
                                    # 深底浅字，提高可读性
                                    cell.fill.solid()
                                    deep_navy = self._lighten(self.colors["background"], 12)
                                    cell.fill.fore_color.rgb = deep_navy
                                    p = cell.text_frame.paragraphs[0]
                                    p.font.color.rgb = RGBColor(255, 255, 255)
                                    p.font.size = Pt(14)
                                    p.line_spacing = 1.15
                                else:
                                    cell.text_frame.paragraphs[0].font.color.rgb = (
                                        self.colors["text"]
                                    )
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
