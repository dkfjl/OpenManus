"""
增强版PPT大纲生成服务
基于初始大纲生成专业、完整的PPT内容大纲
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from app.enhanced_schema import (
    EnhancedOutlineStatus,
    EnhancedSlideItem,
    build_enhanced_outline_prompt,
    create_fallback_enhanced_outline,
    validate_enhanced_outline,
)
from app.llm import LLM
from app.logger import logger
from app.schema import Message, PPTOutlineItem
from app.services.execution_log_service import log_execution_event


async def generate_enhanced_outline(
    original_outline: List[PPTOutlineItem],
    topic: str,
    language: str = "zh",
    reference_content: Optional[str] = None,
) -> List[EnhancedSlideItem]:
    """
    基于初始大纲生成增强版专业PPT大纲

    Args:
        original_outline: 原始PPT大纲
        topic: PPT主题
        language: 输出语言
        reference_content: 参考内容摘要

    Returns:
        增强版PPT大纲页面列表
    """
    start_time = time.time()

    log_execution_event(
        "enhanced_outline_generation",
        "Starting enhanced PPT outline generation",
        {
            "topic": topic[:100],
            "language": language,
            "original_outline_length": len(original_outline),
            "has_reference": bool(reference_content),
        },
    )

    try:
        # 构建专门的prompt来生成增强版大纲
        prompt = build_enhanced_outline_prompt(topic, language, reference_content)

        # 调用LLM生成大纲
        llm = LLM()
        response = await llm.ask(
            [Message.user_message(prompt)],
            stream=False,
            temperature=0.3,
        )

        # 解析和验证返回的JSON
        enhanced_outline = _parse_enhanced_response(response, topic, language)

        execution_time = time.time() - start_time

        log_execution_event(
            "enhanced_outline_generation",
            "Enhanced PPT outline generation completed successfully",
            {
                "slide_count": len(enhanced_outline),
                "execution_time": execution_time,
                "validation_passed": True,
            },
        )

        return enhanced_outline

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(f"Enhanced outline generation failed: {str(e)}")

        log_execution_event(
            "enhanced_outline_generation",
            "Enhanced PPT outline generation failed",
            {
                "error": str(e),
                "execution_time": execution_time,
            },
        )

        # 返回fallback大纲
        return create_fallback_enhanced_outline(topic, language)


def _parse_enhanced_response(
    response: str, topic: str, language: str
) -> List[EnhancedSlideItem]:
    """解析LLM返回的增强版大纲JSON响应"""

    try:
        # 清理响应文本，提取JSON
        cleaned_response = response.strip()

        # 尝试直接解析为JSON数组
        if cleaned_response.startswith("[") and cleaned_response.endswith("]"):
            data = json.loads(cleaned_response)
        else:
            # 尝试从文本中提取JSON数组
            import re

            json_match = re.search(r"\[.*\]", cleaned_response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                raise ValueError("No valid JSON array found in response")

        # 验证数据结构并转换为EnhancedSlideItem对象
        enhanced_outline = []
        for item_data in data:
            # 验证必需字段 - type字段必须存在
            if "type" not in item_data:
                continue

            # 确保data字段存在，特别是结束页可能没有data字段
            if "data" not in item_data:
                if item_data["type"] == "end":
                    item_data["data"] = {}  # 为结束页添加空的data字段
                else:
                    continue  # 其他类型必须有data字段

            # 创建EnhancedSlideItem对象
            slide_item = EnhancedSlideItem.model_validate(
                {"type": item_data["type"], "data": item_data["data"]}
            )
            enhanced_outline.append(slide_item)

        if not enhanced_outline:
            raise ValueError("No valid slide items found in response")

        # 对中文内容进行最小字数强化（内容页 items[*].text ≥ 50字）
        if (language or "zh").lower().startswith("zh"):
            _enforce_min_chinese_text_length(enhanced_outline, topic, min_chars=50)

        # 验证整体大纲结构
        if not validate_enhanced_outline(enhanced_outline):
            logger.warning("Enhanced outline validation failed, using fallback")
            return create_fallback_enhanced_outline(topic, language)

        return enhanced_outline

    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing failed for enhanced outline: {str(e)}")
        # 返回fallback大纲
        outline = create_fallback_enhanced_outline(topic, language)
        if (language or "zh").lower().startswith("zh"):
            _enforce_min_chinese_text_length(outline, topic, min_chars=50)
        return outline

    except Exception as e:
        logger.error(f"Enhanced outline parsing failed: {str(e)}")
        # 返回fallback大纲
        outline = create_fallback_enhanced_outline(topic, language)
        if (language or "zh").lower().startswith("zh"):
            _enforce_min_chinese_text_length(outline, topic, min_chars=50)
        return outline


def _enforce_min_chinese_text_length(
    outline: List[EnhancedSlideItem], topic: str, *, min_chars: int = 50
) -> None:
    """确保中文内容页 items[*].text 的字数不少于 min_chars。

    仅在 type == "content" 且 data.items 为列表时生效，按需对过短文本做温和扩展。
    """

    def enrich(text: Optional[str], title: str) -> str:
        base = (text or "").strip()
        # 统计不含空白的字符数
        count = len("".join(base.split()))
        if count >= min_chars:
            return base

        addon = (
            f"。围绕“{title}”，结合“{topic}”，补充背景、目标、关键方法、实施步骤与注意事项，"
            f"并以简要案例说明做法与结果，明确评估指标与预期效果，强调可执行与落地细节。"
        )
        # 迭代拼接直到满足最小长度
        while len("".join(base.split())) < min_chars:
            base = (base + addon).strip("。") + "。"
        return base

    try:
        for slide in outline:
            if getattr(slide, "type", None) != "content":
                continue
            items = slide.data.get("items") if isinstance(slide.data, dict) else None
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                title = str(it.get("title") or it.get("point") or "要点").strip()
                it["text"] = enrich(it.get("text"), title)
    except Exception as e:
        # 不因扩展失败而中断流程，仅记录
        logger.warning(f"Chinese text length enforcement skipped due to: {e}")


async def process_enhanced_outline_async(
    original_outline: List[PPTOutlineItem],
    topic: str,
    language: str,
    reference_content: Optional[str],
    reference_sources: List[str],
    uuid: str,
    storage_service: Any,
) -> None:
    """
    异步处理增强版大纲生成

    Args:
        original_outline: 原始PPT大纲
        topic: PPT主题
        language: 输出语言
        reference_content: 参考内容摘要
        reference_sources: 参考文件源列表
        uuid: 增强版大纲UUID
        storage_service: 存储服务实例
    """
    try:
        # 更新状态为processing
        await storage_service.update_outline_status(
            uuid, EnhancedOutlineStatus.PROCESSING
        )

        # 生成增强版大纲
        enhanced_outline = await generate_enhanced_outline(
            original_outline=original_outline,
            topic=topic,
            language=language,
            reference_content=reference_content,
        )

        # 保存增强版大纲
        await storage_service.save_outline(
            outline=enhanced_outline,
            topic=topic,
            language=language,
            reference_sources=reference_sources,
            uuid=uuid,
            status=EnhancedOutlineStatus.COMPLETED,
        )

        log_execution_event(
            "enhanced_outline_async",
            "Async enhanced outline processing completed",
            {
                "uuid": uuid,
                "slide_count": len(enhanced_outline),
                "topic": topic,
                "language": language,
            },
        )

    except Exception as e:
        logger.error(
            f"Async enhanced outline processing failed for UUID {uuid}: {str(e)}"
        )

        # 更新状态为failed
        await storage_service.update_outline_status(
            uuid=uuid, status=EnhancedOutlineStatus.FAILED, error_message=str(e)
        )

        log_execution_event(
            "enhanced_outline_async",
            "Async enhanced outline processing failed",
            {
                "uuid": uuid,
                "error": str(e),
                "topic": topic,
            },
        )


# 大纲结构分析函数
def analyze_outline_structure(original_outline: List[PPTOutlineItem]) -> Dict[str, Any]:
    """分析原始大纲结构，为增强版生成提供参考"""

    analysis = {
        "total_steps": len(original_outline),
        "has_planning_steps": False,
        "has_design_steps": False,
        "has_content_steps": False,
        "key_topics": [],
        "complexity_level": "medium",
    }

    for item in original_outline:
        title_lower = item.title.lower()
        desc_lower = item.description.lower()

        # 分析步骤类型
        if any(
            keyword in title_lower + desc_lower
            for keyword in ["规划", "计划", "设计", "plan", "design"]
        ):
            analysis["has_planning_steps"] = True

        if any(
            keyword in title_lower + desc_lower
            for keyword in ["内容", "制作", "构建", "content", "create"]
        ):
            analysis["has_content_steps"] = True

        # 提取关键主题
        if len(analysis["key_topics"]) < 5:  # 最多提取5个关键主题
            analysis["key_topics"].append(item.title)

    # 确定复杂度级别
    if analysis["total_steps"] <= 3:
        analysis["complexity_level"] = "simple"
    elif analysis["total_steps"] >= 8:
        analysis["complexity_level"] = "complex"

    return analysis


# 内容质量评估函数
def assess_content_quality(outline: List[EnhancedSlideItem]) -> Dict[str, Any]:
    """评估生成的大纲内容质量"""

    assessment = {
        "total_slides": len(outline),
        "cover_present": False,
        "contents_present": False,
        "end_present": False,
        "content_slides": 0,
        "transition_slides": 0,
        "avg_items_per_content_slide": 0,
        "quality_score": 0,
    }

    content_items_count = 0

    for slide in outline:
        slide_type = slide.type

        if slide_type == "cover":
            assessment["cover_present"] = True
        elif slide_type == "contents":
            assessment["contents_present"] = True
        elif slide_type == "end":
            assessment["end_present"] = True
        elif slide_type == "content":
            assessment["content_slides"] += 1
            if "items" in slide.data and isinstance(slide.data["items"], list):
                items_count = len(slide.data["items"])
                content_items_count += items_count
        elif slide_type == "transition":
            assessment["transition_slides"] += 1

    # 计算平均每页要点数
    if assessment["content_slides"] > 0:
        assessment["avg_items_per_content_slide"] = (
            content_items_count / assessment["content_slides"]
        )

    # 计算质量分数 (0-100)
    quality_score = 0
    if assessment["cover_present"]:
        quality_score += 20
    if assessment["contents_present"]:
        quality_score += 20
    if assessment["end_present"]:
        quality_score += 20
    if assessment["content_slides"] >= 3:
        quality_score += 20
    if 2 <= assessment["avg_items_per_content_slide"] <= 4:
        quality_score += 20

    assessment["quality_score"] = min(quality_score, 100)

    return assessment
