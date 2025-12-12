"""
PPT大纲生成服务
负责生成符合用户指定JSON格式的PPT大纲
"""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from app.enhanced_schema import EnhancedOutlineStatus
from app.llm import LLM
from app.logger import logger
from app.schema import Message, MetaData, PPTOutlineItem, Substep
from app.services.enhanced_outline_storage import enhanced_outline_storage
from app.services.execution_log_service import log_execution_event
from app.utils.async_tasks import create_enhanced_outline_task


async def generate_ppt_outline_with_format(
    topic: str,
    language: str = "zh",
    reference_content: Optional[str] = None,
    reference_sources: Optional[List[str]] = None,
    generate_enhanced: bool = True,
) -> Dict[str, Any]:
    """
    生成符合用户指定格式的PPT大纲

    Args:
        topic: PPT主题
        language: 输出语言
        reference_content: 参考内容摘要
        reference_sources: 参考文件源列表
        generate_enhanced: 是否生成增强版大纲

    Returns:
        包含PPT大纲的响应数据
    """
    start_time = time.time()

    log_execution_event(
        "ppt_outline_format",
        "Starting PPT outline generation with custom format",
        {
            "topic": topic[:100],
            "language": language,
            "has_reference": bool(reference_content),
            "generate_enhanced": generate_enhanced,
        },
    )

    try:
        # 构建专门的prompt来生成用户指定格式的JSON
        prompt = _build_format_prompt(topic, language, reference_content)

        # 调用LLM生成大纲
        llm = LLM()
        response = await llm.ask(
            [Message.user_message(prompt)],
            stream=False,
            temperature=0.3,
        )

        # 解析和验证返回的JSON
        outline_items = _parse_outline_response(response, topic, language)

        execution_time = time.time() - start_time

        # 初始化增强版大纲相关信息
        enhanced_outline_status = EnhancedOutlineStatus.PENDING
        enhanced_outline_uuid = None

        # 如果需要生成增强版大纲，启动异步任务
        if generate_enhanced:
            try:
                # 创建增强版大纲记录
                enhanced_uuid = await enhanced_outline_storage.create_outline_record(
                    topic=topic,
                    language=language,
                    reference_sources=reference_sources or [],
                )

                # 启动异步任务生成增强版大纲
                await create_enhanced_outline_task(
                    original_outline=outline_items,
                    topic=topic,
                    language=language,
                    reference_content=reference_content,
                    reference_sources=reference_sources or [],
                    enhanced_uuid=enhanced_uuid,
                )

                enhanced_outline_status = EnhancedOutlineStatus.PROCESSING
                enhanced_outline_uuid = enhanced_uuid

                log_execution_event(
                    "enhanced_outline",
                    "Started async enhanced outline generation",
                    {
                        "enhanced_uuid": enhanced_uuid,
                        "topic": topic,
                        "language": language,
                    },
                )

            except Exception as e:
                logger.error(f"Failed to start enhanced outline generation: {str(e)}")
                enhanced_outline_status = EnhancedOutlineStatus.FAILED
                # 不影响主流程，继续返回初始大纲

        result = {
            "status": "success",
            "outline": outline_items,
            "enhanced_outline_status": enhanced_outline_status,
            "enhanced_outline_uuid": enhanced_outline_uuid,
            "topic": topic,
            "language": language,
            "execution_time": execution_time,
            "reference_sources": reference_sources or [],
        }

        log_execution_event(
            "ppt_outline_format",
            "PPT outline generation completed successfully",
            {
                "item_count": len(outline_items),
                "execution_time": execution_time,
                "reference_sources_count": len(reference_sources or []),
                "enhanced_outline_status": enhanced_outline_status,
                "enhanced_outline_uuid": enhanced_outline_uuid,
            },
        )

        return result

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(f"PPT outline generation failed: {str(e)}")

        # 返回错误响应
        return {
            "status": "error",
            "outline": [],
            "enhanced_outline_status": EnhancedOutlineStatus.FAILED,
            "enhanced_outline_uuid": None,
            "topic": topic,
            "language": language,
            "execution_time": execution_time,
            "reference_sources": reference_sources or [],
            "error": str(e),
        }


def _build_format_prompt(
    topic: str, language: str, reference_content: Optional[str]
) -> str:
    """构建生成用户指定格式PPT大纲的prompt"""

    lang_instruction = "请用中文" if language == "zh" else "Please use English"

    # 构建参考材料部分
    if reference_content:
        reference_part = (
            f"以下是参考材料，请适当融入内容规划：\n{reference_content[:1500]}"
        )
    else:
        reference_part = "无参考材料，基于主题生成内容"

    base_prompt = f"""
任务：为主题"{topic}"生成PPT制作过程的详细大纲，输出严格的JSON数组格式。

输出要求：
1. 必须返回JSON数组，每个元素代表PPT制作的一个步骤
2. 每个步骤必须包含：key、title、description、detailType、meta字段
3. meta字段必须包含：summary和substeps
4. substeps是数组，每个子步骤包含：key、text、showDetail，可选的detailType和detailPayload
5. detailType 必须是以下四种之一：text（文本）、image（图片）、list（列表）、table（表格）
6. 严格按照以下示例结构输出：

[
    {{
        "key": "0",
        "title": "需求分析与任务拆解",
        "description": "我来为你制作一份专业的{topic}PPT。让我先分析你的需求",
        "detailType": "text",
        "meta": {{
            "summary": "自动从输入中提炼目标与约束，形成可执行列表",
            "substeps": [
                {{"key": "0-1", "text": "分析用户意图与上下文", "showDetail": false}},
                {{"key": "0-2", "text": "拆解任务及依赖关系", "showDetail": false}},
                {{
                    "key": "0-3",
                    "text": "待办清单",
                    "showDetail": true,
                    "detailType": "list",
                    "detailPayload": {{
                        "format": "markdown",
                        "content": "### 待办清单\n\n- 拟定标题与副标题\n- 生成PPT目录\n- 生成各章大纲\n- 构建PPT主体\n- 优化版式与内容"
                    }}
                }}
            ]
        }}
    }}
]

内容要求：
{lang_instruction}生成内容
- 围绕{topic}主题，生成5-8个制作步骤
- 每个步骤描述PPT制作的具体环节
- detailType 根据内容选择：text（文本段落）、list（要点列表）、table（对比表格）、image（配图说明）
- detailPayload 使用 format="markdown" 和 content 字段
- 所有内容以 Markdown 格式组织

参考材料：
{reference_part}
"""

    return base_prompt.strip()


def _parse_outline_response(
    response: str, topic: str, language: str
) -> List[PPTOutlineItem]:
    """解析LLM返回的JSON响应"""

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

        # 验证数据结构并转换为PPTOutlineItem对象
        outline_items = []
        for item_data in data:
            # 验证必需字段
            if not all(
                key in item_data for key in ["key", "title", "description", "meta"]
            ):
                continue

            meta_data = item_data["meta"]
            if not all(key in meta_data for key in ["summary", "substeps"]):
                continue

            # 构建子步骤
            substeps = []
            for step_data in meta_data.get("substeps", []):
                if not all(key in step_data for key in ["key", "text", "showDetail"]):
                    continue

                substep = Substep(
                    key=step_data["key"],
                    text=step_data["text"],
                    showDetail=step_data["showDetail"],
                    detailType=step_data.get("detailType"),
                    detailPayload=step_data.get("detailPayload"),
                )
                substeps.append(substep)

            # 构建元数据
            meta = MetaData(summary=meta_data["summary"], substeps=substeps)

            # 构建大纲项目
            outline_item = PPTOutlineItem(
                key=item_data["key"],
                title=item_data["title"],
                description=item_data["description"],
                detailType=item_data.get("detailType", "markdown"),
                meta=meta,
            )
            outline_items.append(outline_item)

        if not outline_items:
            raise ValueError("No valid outline items found in response")

        return outline_items

    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing failed: {str(e)}")
        # 返回fallback大纲
        return _create_fallback_outline(topic, language)
    except Exception as e:
        logger.error(f"Outline parsing failed: {str(e)}")
        return _create_fallback_outline(topic, language)


def _create_fallback_outline(topic: str, language: str) -> List[PPTOutlineItem]:
    """创建fallback大纲，当LLM生成失败时使用"""

    if language == "zh":
        topic_framework = (
            f"### {topic} PPT框架\n\n- 封面页\n- 目录页\n- 内容章节\n- 结尾页"
        )
        export_suggestions = (
            "### 导出建议\n\n- 保存为PPTX格式\n- 准备PDF备份\n- 检查兼容性"
        )

        fallback_data = [
            {
                "key": "0",
                "title": "需求分析",
                "description": f"分析{topic}PPT的制作需求",
                "detailType": "text",
                "meta": {
                    "summary": "分析用户需求，确定PPT制作目标",
                    "substeps": [
                        {
                            "key": "0-1",
                            "text": "明确PPT主题和目的",
                            "showDetail": False,
                        },
                        {"key": "0-2", "text": "分析目标受众", "showDetail": False},
                        {
                            "key": "0-3",
                            "text": "确定内容框架",
                            "showDetail": True,
                            "detailType": "list",
                            "detailPayload": {
                                "format": "markdown",
                                "content": topic_framework,
                            },
                        },
                    ],
                },
            },
            {
                "key": "1",
                "title": "内容规划",
                "description": "规划PPT的具体内容和结构",
                "detailType": "text",
                "meta": {
                    "summary": "制定详细的内容规划和章节安排",
                    "substeps": [
                        {"key": "1-1", "text": "撰写各章节标题", "showDetail": False},
                        {"key": "1-2", "text": "准备关键要点", "showDetail": False},
                        {"key": "1-3", "text": "收集支撑材料", "showDetail": False},
                    ],
                },
            },
            {
                "key": "2",
                "title": "视觉设计",
                "description": "设计PPT的视觉风格和版式",
                "detailType": "text",
                "meta": {
                    "summary": "确定视觉风格、配色方案和版式设计",
                    "substeps": [
                        {"key": "2-1", "text": "选择主题色彩", "showDetail": False},
                        {"key": "2-2", "text": "设计页面布局", "showDetail": False},
                        {"key": "2-3", "text": "选择字体样式", "showDetail": False},
                    ],
                },
            },
            {
                "key": "3",
                "title": "优化完善",
                "description": "对PPT进行最后的优化和调整",
                "detailType": "text",
                "meta": {
                    "summary": "检查并优化PPT的内容和呈现效果",
                    "substeps": [
                        {"key": "3-1", "text": "内容校对", "showDetail": False},
                        {"key": "3-2", "text": "版式调整", "showDetail": False},
                        {
                            "key": "3-3",
                            "text": "最终导出",
                            "showDetail": True,
                            "detailType": "list",
                            "detailPayload": {
                                "format": "markdown",
                                "content": export_suggestions,
                            },
                        },
                    ],
                },
            },
        ]
    else:
        topic_framework_en = f"### {topic} PPT Framework\n\n- Cover page\n- Table of contents\n- Content sections\n- Closing page"

        fallback_data = [
            {
                "key": "0",
                "title": "Requirements Analysis",
                "description": f"Analyze requirements for {topic} PPT",
                "detailType": "text",
                "meta": {
                    "summary": "Analyze user needs and define PPT creation goals",
                    "substeps": [
                        {
                            "key": "0-1",
                            "text": "Define PPT theme and purpose",
                            "showDetail": False,
                        },
                        {
                            "key": "0-2",
                            "text": "Analyze target audience",
                            "showDetail": False,
                        },
                        {
                            "key": "0-3",
                            "text": "Determine content framework",
                            "showDetail": True,
                            "detailType": "list",
                            "detailPayload": {
                                "format": "markdown",
                                "content": topic_framework_en,
                            },
                        },
                    ],
                },
            },
            {
                "key": "1",
                "title": "Content Planning",
                "description": "Plan specific content and structure of PPT",
                "detailType": "text",
                "meta": {
                    "summary": "Develop detailed content planning and section arrangement",
                    "substeps": [
                        {
                            "key": "1-1",
                            "text": "Write section headings",
                            "showDetail": False,
                        },
                        {
                            "key": "1-2",
                            "text": "Prepare key points",
                            "showDetail": False,
                        },
                        {
                            "key": "1-3",
                            "text": "Collect supporting materials",
                            "showDetail": False,
                        },
                    ],
                },
            },
        ]

    # 将fallback数据转换为PPTOutlineItem对象
    outline_items = []
    for item_data in fallback_data:
        substeps = []
        for step_data in item_data["meta"]["substeps"]:
            substep = Substep(
                key=step_data["key"],
                text=step_data["text"],
                showDetail=step_data["showDetail"],
                detailType=step_data.get("detailType"),
                detailPayload=step_data.get("detailPayload"),
            )
            substeps.append(substep)

        meta = MetaData(summary=item_data["meta"]["summary"], substeps=substeps)

        outline_item = PPTOutlineItem(
            key=item_data["key"],
            title=item_data["title"],
            description=item_data["description"],
            detailType=item_data["detailType"],
            meta=meta,
        )
        outline_items.append(outline_item)

    return outline_items
