from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from app.llm import LLM
from app.schema import Message
from app.logger import logger
from app.services.execution_log_service import log_execution_event


def _sanitize_filename(topic: str) -> str:
    """Sanitize topic for filename generation"""
    sanitized = re.sub(r"[^\w\u4e00-\u9fff]+", "_", topic).strip("_") or "presentation"
    return f"{sanitized}.pptx"


def _default_reports_path(topic: str) -> str:
    """Generate default file path for PPTX"""
    from pathlib import Path
    return str(Path("reports") / _sanitize_filename(topic))


async def generate_aippt_outline(
    *,
    topic: str,
    language: Optional[str] = None,
    reference_content: Optional[str] = None,
) -> dict:
    """
    Generate PPT outline in AIPPT JSON format based on user content.

    Args:
        topic: The main topic/content for the PPT
        language: Output language (zh, en, etc.)
        reference_content: Optional reference material to incorporate

    Returns:
        Dict containing the outline JSON and metadata
    """
    language = language or "zh"

    log_execution_event(
        "aippt_outline",
        "Starting AIPPT outline generation",
        {"topic": topic[:100], "language": language},
    )
    # Also print a console log so users can see progress without reading JSONL
    logger.info(
        "[AIPPT] Start outline generation | topic='{}' | language={}",
        topic,
        language,
    )

    # Build the prompt template
    language_instruction = "请用中文" if language == "zh" else "Please use English"

    prompt_template = f"""{language_instruction}为"{topic}"生成PPT大纲。
要求：
1. 返回标准的JSON格式，符合PPTist的AIPPT类型定义
2. 包含封面页、目录页、过渡页、内容页、结束页
3. 每个内容页包含2-4个要点
4. 内容要有逻辑性和层次性

PPT页面类型定义：

1. 封面页 (cover):
{{
  "type": "cover",
  "data": {{
    "title": "PPT标题",
    "text": "副标题或描述"
  }}
}}

2. 目录页 (contents):
{{
  "type": "contents",
  "data": {{
    "items": ["目录项1", "目录项2", "目录项3"]
  }}
}}

3. 过渡页 (transition):
{{
  "type": "transition",
  "data": {{
    "title": "章节标题",
    "text": "章节描述"
  }}
}}

4. 内容页 (content):
{{
  "type": "content",
  "data": {{
    "title": "页面标题",
    "items": [
      {{
        "title": "要点标题",
        "text": "要点详细说明"
      }}
    ]
  }}
}}

5. 结束页 (end):
{{
  "type": "end"
}}

请生成完整的PPT大纲JSON数组，包含所有页面类型。"""

    # Add reference content if provided
    if reference_content and reference_content.strip():
        prompt_template += f"\n\n参考材料：\n{reference_content[:2000]}"

    try:
        # Initialize LLM client
        llm = LLM()

        # Generate outline
        # NOTE: LLM.ask expects a list of messages, not a raw string.
        # Passing a string leads to iterating over characters and a TypeError
        # in LLM.format_messages. Wrap the prompt as a user message.
        response = await llm.ask(
            [Message.user_message(prompt_template)],
            # Non-streaming makes it easier to parse the full JSON afterwards
            stream=False,
            temperature=0.2,
        )

        # Extract JSON from response
        outline_json = _extract_json_from_response(response)

        # Validate the outline structure
        validated_outline = _validate_outline(outline_json, topic)

        log_execution_event(
            "aippt_outline",
            "AIPPT outline generated successfully",
            {"slides_count": len(validated_outline)},
        )
        # Print the whole outline to logs for visibility
        try:
            pretty_outline = json.dumps(validated_outline, ensure_ascii=False, indent=2)
        except Exception:
            pretty_outline = str(validated_outline)
        logger.info(
            "[AIPPT] Outline generated successfully ({} slides)\n{}",
            len(validated_outline),
            pretty_outline,
        )

        return {
            "status": "success",
            "outline": validated_outline,
            "topic": topic,
            "language": language,
        }

    except Exception as e:
        log_execution_event(
            "aippt_outline",
            "AIPPT outline generation failed",
            {"error": str(e)},
        )
        logger.error("[AIPPT] Outline generation failed: {}", e)

        # Return a fallback outline
        fallback_outline = _create_fallback_outline(topic, language)
        # Print fallback outline to logs for debugging/visibility
        try:
            pretty_fallback = json.dumps(fallback_outline, ensure_ascii=False, indent=2)
        except Exception:
            pretty_fallback = str(fallback_outline)
        logger.info(
            "[AIPPT] Using fallback outline ({} slides)\n{}",
            len(fallback_outline),
            pretty_fallback,
        )

        return {
            "status": "fallback",
            "outline": fallback_outline,
            "topic": topic,
            "language": language,
            "error": str(e),
        }


def _extract_json_from_response(response: str) -> List[dict]:
    """Extract JSON array from LLM response"""
    # Try to find JSON array in the response
    json_match = re.search(r'\[.*\]', response, re.DOTALL)

    if json_match:
        json_str = json_match.group(0)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from match: {e}")
            raise ValueError("Invalid JSON format in LLM response")

    # Try to parse the entire response as JSON
    try:
        parsed = json.loads(response.strip())
        if isinstance(parsed, list):
            return parsed
        else:
            raise ValueError("Response is not a JSON array")
    except json.JSONDecodeError:
        raise ValueError("No valid JSON found in LLM response")


def _validate_outline(outline: List[dict], topic: str) -> List[dict]:
    """Validate and fix the outline structure"""
    if not outline:
        raise ValueError("Empty outline")

    validated = []

    # Ensure we have required slide types
    has_cover = False
    has_contents = False
    has_end = False

    for slide in outline:
        if not isinstance(slide, dict):
            continue

        slide_type = slide.get("type")
        if slide_type == "cover":
            has_cover = True
            # Ensure cover has required fields
            if "data" not in slide:
                slide["data"] = {}
            if "title" not in slide["data"]:
                slide["data"]["title"] = topic
            if "text" not in slide["data"]:
                slide["data"]["text"] = ""
        elif slide_type == "contents":
            has_contents = True
            # Ensure contents has required fields
            if "data" not in slide:
                slide["data"] = {}
            if "items" not in slide["data"]:
                slide["data"]["items"] = ["目录"]
        elif slide_type == "end":
            has_end = True
            # End slide doesn't need data
        elif slide_type in ["transition", "content"]:
            # Ensure these have basic structure
            if "data" not in slide:
                slide["data"] = {}
            if slide_type == "content" and "items" not in slide["data"]:
                slide["data"]["items"] = []

        validated.append(slide)

    # Add missing required slides
    if not has_cover:
        validated.insert(0, {
            "type": "cover",
            "data": {
                "title": topic,
                "text": ""
            }
        })

    if not has_contents:
        validated.insert(1, {
            "type": "contents",
            "data": {
                "items": ["目录"]
            }
        })

    if not has_end:
        validated.append({
            "type": "end"
        })

    return validated


def _create_fallback_outline(topic: str, language: str) -> List[dict]:
    """Create a basic fallback outline when generation fails"""
    if language == "zh":
        return [
            {
                "type": "cover",
                "data": {
                    "title": topic,
                    "text": "自动生成的演示文稿"
                }
            },
            {
                "type": "contents",
                "data": {
                    "items": ["概述", "主要内容", "总结"]
                }
            },
            {
                "type": "content",
                "data": {
                    "title": "概述",
                    "items": [
                        {
                            "title": "背景介绍",
                            "text": "相关背景信息"
                        },
                        {
                            "title": "目标说明",
                            "text": "本次演示的目标"
                        }
                    ]
                }
            },
            {
                "type": "content",
                "data": {
                    "title": "主要内容",
                    "items": [
                        {
                            "title": "核心要点",
                            "text": "主要内容和分析"
                        },
                        {
                            "title": "详细说明",
                            "text": "进一步的解释和说明"
                        }
                    ]
                }
            },
            {
                "type": "content",
                "data": {
                    "title": "总结",
                    "items": [
                        {
                            "title": "要点回顾",
                            "text": "主要内容的总结"
                        },
                        {
                            "title": "展望",
                            "text": "未来的发展方向"
                        }
                    ]
                }
            },
            {
                "type": "end"
            }
        ]
    else:
        return [
            {
                "type": "cover",
                "data": {
                    "title": topic,
                    "text": "Auto-generated Presentation"
                }
            },
            {
                "type": "contents",
                "data": {
                    "items": ["Overview", "Main Content", "Conclusion"]
                }
            },
            {
                "type": "content",
                "data": {
                    "title": "Overview",
                    "items": [
                        {
                            "title": "Background",
                            "text": "Background information"
                        },
                        {
                            "title": "Objectives",
                            "text": "Presentation objectives"
                        }
                    ]
                }
            },
            {
                "type": "content",
                "data": {
                    "title": "Main Content",
                    "items": [
                        {
                            "title": "Key Points",
                            "text": "Main content and analysis"
                        },
                        {
                            "title": "Details",
                            "text": "Further explanations"
                        }
                    ]
                }
            },
            {
                "type": "content",
                "data": {
                    "title": "Conclusion",
                    "items": [
                        {
                            "title": "Summary",
                            "text": "Summary of main points"
                        },
                        {
                            "title": "Future",
                            "text": "Future directions"
                        }
                    ]
                }
            },
            {
                "type": "end"
            }
        ]
