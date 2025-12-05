"""
增强版PPT大纲数据模型
定义二次生成专业PPT大纲的数据结构
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SlideType(str, Enum):
    """PPT页面类型枚举"""

    COVER = "cover"  # 封面页
    CONTENTS = "contents"  # 目录页
    TRANSITION = "transition"  # 过渡页
    CONTENT = "content"  # 内容页
    END = "end"  # 结束页


class EnhancedSlideItem(BaseModel):
    """增强版PPT大纲页面项目"""

    type: str = Field(
        ..., description="页面类型：cover/contents/transition/content/end"
    )
    data: Dict[str, Any] = Field(..., description="页面数据，根据type变化")


class EnhancedOutlineStatus(str, Enum):
    """增强版大纲生成状态"""

    PENDING = "pending"  # 等待生成
    PROCESSING = "processing"  # 正在生成
    COMPLETED = "completed"  # 生成完成
    FAILED = "failed"  # 生成失败


class EnhancedOutlineInfo(BaseModel):
    """增强版大纲元数据信息"""

    uuid: str
    topic: str
    language: str
    status: EnhancedOutlineStatus
    created_at: str
    updated_at: str
    file_path: str
    reference_sources: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None


class EnhancedOutlineResponse(BaseModel):
    """增强版PPT大纲响应"""

    status: str
    outline: Optional[List[EnhancedSlideItem]] = Field(
        default=None, description="增强版大纲（状态为completed时提供）"
    )
    topic: str
    language: str
    created_at: Optional[str] = Field(
        default=None, description="创建时间（状态为completed时提供）"
    )
    reference_sources: List[str] = Field(default_factory=list)
    message: Optional[str] = Field(default=None, description="状态说明信息")


# 语言映射配置
LANGUAGE_MAP = {"zh": "请用中文", "en": "Please use English"}


# 增强版大纲生成提示词模板
ENHANCED_OUTLINE_PROMPT_TEMPLATE = """
{language_instruction}为"{topic}"生成专业、完整的PPT大纲。

要求：
1. 返回标准的JSON数组格式，每个元素代表一页PPT
2. 大纲结构：封面页 → 目录页 → 3-6个主要章节（每章节包含过渡页+2-4个内容页）→ 结束页
3. 每个内容页包含2-4个要点，每个要点要有明确的标题和详细说明
4. 内容要有清晰的逻辑递进关系，从概述到深入，从理论到实践
5. 语言简洁专业，适合演讲展示

页面类型及格式规范：
- cover: 封面页 - {{ "type": "cover", "data": {{ "title": "主标题", "text": "副标题或描述文字" }} }}
- contents: 目录页 - {{ "type": "contents", "data": {{ "items": ["章节1", "章节2", "章节3"] }} }}
- transition: 过渡页 - {{ "type": "transition", "data": {{ "title": "章节标题", "text": "章节简介" }} }}
- content: 内容页 - {{ "type": "content", "data": {{ "title": "页面标题", "items": [{{"title": "要点标题", "text": "详细说明"}}] }} }}
- end: 结束页 - {{ "type": "end", "data": {{}} }}

请确保：
- 主标题简洁有力，副标题补充说明
- 章节划分合理，覆盖主题的主要方面
- 每个要点既有概括性标题，又有实质性内容
- 整体结构完整，便于后续内容填充和PPT制作

{reference_section}

示例结构：
[
  {{"type": "cover", "data": {{"title": "主题", "text": "副标题"}}}},
  {{"type": "contents", "data": {{"items": ["章节1", "章节2", "章节3"]}}}},
  {{"type": "transition", "data": {{"title": "章节1", "text": "章节介绍"}}}},
  {{"type": "content", "data": {{"title": "具体内容", "items": [{{"title": "要点1", "text": "说明1"}}]}}}},
  ...
  {{"type": "end", "data": {{}}}}
]
"""


def build_enhanced_outline_prompt(
    topic: str, language: str = "zh", reference_content: Optional[str] = None
) -> str:
    """构建增强版大纲生成提示词"""

    lang_instruction = LANGUAGE_MAP.get(language, LANGUAGE_MAP["zh"])

    # 构建参考材料部分
    if reference_content:
        reference_section = f"""
参考材料：
以下是相关参考材料，请适当融入内容规划：
{reference_content[:2000]}
"""
    else:
        reference_section = ""

    return ENHANCED_OUTLINE_PROMPT_TEMPLATE.format(
        language_instruction=lang_instruction,
        topic=topic,
        reference_section=reference_section,
    ).strip()


# 封面页数据验证函数
def validate_cover_page(data: Dict[str, Any]) -> bool:
    """验证封面页数据格式"""
    return (
        isinstance(data, dict)
        and "title" in data
        and isinstance(data["title"], str)
        and len(data["title"].strip()) > 0
    )


# 目录页数据验证函数
def validate_contents_page(data: Dict[str, Any]) -> bool:
    """验证目录页数据格式"""
    return (
        isinstance(data, dict)
        and "items" in data
        and isinstance(data["items"], list)
        and len(data["items"]) > 0
        and all(isinstance(item, str) for item in data["items"])
    )


# 过渡页数据验证函数
def validate_transition_page(data: Dict[str, Any]) -> bool:
    """验证过渡页数据格式"""
    return (
        isinstance(data, dict)
        and "title" in data
        and isinstance(data["title"], str)
        and len(data["title"].strip()) > 0
    )


# 内容页数据验证函数
def validate_content_page(data: Dict[str, Any]) -> bool:
    """验证内容页数据格式"""
    if not isinstance(data, dict):
        return False

    if "title" not in data or not isinstance(data["title"], str):
        return False

    if "items" not in data or not isinstance(data["items"], list):
        return False

    if len(data["items"]) == 0:
        return False

    # 验证每个要点
    for item in data["items"]:
        if not isinstance(item, dict):
            return False
        if "title" not in item or not isinstance(item["title"], str):
            return False
        if "text" not in item or not isinstance(item["text"], str):
            return False

    return True


# 页面数据验证映射
PAGE_VALIDATORS = {
    SlideType.COVER: validate_cover_page,
    SlideType.CONTENTS: validate_contents_page,
    SlideType.TRANSITION: validate_transition_page,
    SlideType.CONTENT: validate_content_page,
    SlideType.END: lambda data: True,  # 结束页不需要验证数据
}


def validate_enhanced_outline(outline: List[EnhancedSlideItem]) -> bool:
    """验证增强版大纲数据结构"""
    if not outline or len(outline) == 0:
        return False

    # 验证必须包含的页面类型
    page_types = [item.type for item in outline]
    required_types = [SlideType.COVER, SlideType.CONTENTS, SlideType.END]

    for required_type in required_types:
        if required_type not in page_types:
            return False

    # 验证每个页面的数据格式
    for item in outline:
        if item.type not in PAGE_VALIDATORS:
            return False

        if not PAGE_VALIDATORS[item.type](item.data):
            return False

    return True


# Fallback增强版大纲生成函数
def create_fallback_enhanced_outline(
    topic: str, language: str = "zh"
) -> List[EnhancedSlideItem]:
    """创建fallback增强版大纲"""

    if language == "zh":
        fallback_data = [
            {
                "type": "cover",
                "data": {
                    "title": f"{topic}专业解析",
                    "text": "深入理解核心概念与实践应用",
                },
            },
            {
                "type": "contents",
                "data": {"items": ["概述", "核心概念", "实践应用", "总结展望"]},
            },
            {
                "type": "transition",
                "data": {"title": "概述", "text": "了解基本背景和重要性"},
            },
            {
                "type": "content",
                "data": {
                    "title": "主题概述",
                    "items": [
                        {
                            "title": "定义与背景",
                            "text": f"{topic}是现代领域中的重要概念，具有广泛的应用价值。",
                        },
                        {
                            "title": "发展现状",
                            "text": "当前{topic}在技术发展和实际应用中扮演着关键角色。",
                        },
                    ],
                },
            },
            {
                "type": "transition",
                "data": {"title": "核心概念", "text": "深入理解关键要素"},
            },
            {
                "type": "content",
                "data": {
                    "title": "关键要素分析",
                    "items": [
                        {
                            "title": "基本原理",
                            "text": f"{topic}基于坚实的理论基础，具有科学的原理支撑。",
                        },
                        {
                            "title": "主要特征",
                            "text": "具有独特性、实用性和创新性等显著特征。",
                        },
                        {
                            "title": "应用范围",
                            "text": "广泛应用于多个领域，展现出强大的适应性。",
                        },
                    ],
                },
            },
            {
                "type": "transition",
                "data": {"title": "实践应用", "text": "探索实际应用价值"},
            },
            {
                "type": "content",
                "data": {
                    "title": "应用场景",
                    "items": [
                        {
                            "title": "典型应用",
                            "text": f"{topic}在实际项目中发挥重要作用，提升效率和质量。",
                        },
                        {
                            "title": "实施策略",
                            "text": "需要科学的规划和合理的实施步骤来确保成功应用。",
                        },
                    ],
                },
            },
            {
                "type": "transition",
                "data": {"title": "总结展望", "text": "回顾要点并展望未来"},
            },
            {
                "type": "content",
                "data": {
                    "title": "总结与展望",
                    "items": [
                        {
                            "title": "核心要点",
                            "text": f"{topic}具有重要的理论价值和实践意义。",
                        },
                        {
                            "title": "发展趋势",
                            "text": "未来将在技术创新和应用拓展方面持续发展。",
                        },
                    ],
                },
            },
            {"type": "end", "data": {}},
        ]
    else:
        fallback_data = [
            {
                "type": "cover",
                "data": {
                    "title": f"Professional Analysis of {topic}",
                    "text": "Understanding Core Concepts and Practical Applications",
                },
            },
            {
                "type": "contents",
                "data": {
                    "items": ["Overview", "Core Concepts", "Applications", "Conclusion"]
                },
            },
            {
                "type": "transition",
                "data": {
                    "title": "Overview",
                    "text": "Understanding the background and significance",
                },
            },
            {
                "type": "content",
                "data": {
                    "title": "Topic Overview",
                    "items": [
                        {
                            "title": "Definition and Background",
                            "text": f"{topic} is an important concept in modern fields with wide applications.",
                        },
                        {
                            "title": "Current Status",
                            "text": f"{topic} plays a key role in technological development and practical applications.",
                        },
                    ],
                },
            },
            {"type": "end", "data": {}},
        ]

    return [EnhancedSlideItem.model_validate(item) for item in fallback_data]
