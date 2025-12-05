# OpenManus Dify知识库集成 - 详细实施计划

## 项目概述
将Dify知识库（RAG Engine）的检索能力无缝接入OpenManus，实现对企业私有数据的智能访问。

## 实施路线图

### Phase 1: 配置管理 (0.5天)

#### 1.1 配置模型定义
在 [`app/config.py`](app/config.py) 中添加Dify知识库配置模型：

```python
class DifyKnowledgeBaseSettings(BaseModel):
    """Configuration for Dify knowledge base integration"""

    api_base: str = Field(
        "https://api.dify.ai/v1",
        description="Dify API service base URL"
    )
    api_key: str = Field(
        "",
        description="Dataset-specific API key for authentication"
    )
    dataset_id: Optional[str] = Field(
        None,
        description="Dataset ID if API key is not bound to specific dataset"
    )
    retrieval_model: str = Field(
        "search",
        description="Retrieval model to use"
    )
    score_threshold: float = Field(
        0.5,
        description="Minimum relevance score threshold"
    )
    top_k: int = Field(
        3,
        description="Number of top results to retrieve"
    )
    timeout: int = Field(
        5,
        description="Request timeout in seconds"
    )
    max_retries: int = Field(
        3,
        description="Maximum retry attempts for failed requests"
    )
```

#### 1.2 主配置集成
更新 [`AppConfig`](app/config.py:343) 类：

```python
class AppConfig(BaseModel):
    # ... existing fields ...
    dify_config: Optional[DifyKnowledgeBaseSettings] = Field(
        None,
        description="Dify knowledge base configuration"
    )
```

#### 1.3 配置加载逻辑
在配置加载方法中添加Dify配置解析：

```python
# 在 _load_initial_config 方法中添加
dify_config = raw_config.get("dify")
if dify_config:
    dify_settings = DifyKnowledgeBaseSettings(**dify_config)
else:
    dify_settings = DifyKnowledgeBaseSettings()

# 在 config_dict 中添加
config_dict["dify_config"] = dify_settings
```

#### 1.4 配置访问属性
添加配置访问属性：

```python
@property
def dify(self) -> Optional[DifyKnowledgeBaseSettings]:
    """Get Dify knowledge base configuration"""
    return self._config.dify_config
```

### Phase 2: Dify API客户端模块 (0.5天)

#### 2.1 创建Dify客户端模块
创建 [`app/tool/dify_client.py`](app/tool/dify_client.py)：

```python
import asyncio
import json
from typing import Dict, List, Optional, Any
from datetime import datetime

import aiohttp
from pydantic import BaseModel, Field

from app.config import config
from app.logger import logger


class DifyRetrievalRequest(BaseModel):
    """Request model for Dify knowledge base retrieval"""
    query: str = Field(..., description="Search query")
    retrieval_model: str = Field("search", description="Retrieval model")
    score_threshold: float = Field(0.5, description="Score threshold")
    top_k: int = Field(3, description="Number of results")


class DifyRetrievalResponse(BaseModel):
    """Response model for Dify knowledge base retrieval"""
    records: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = Field(0, description="Total number of records")
    query: str = Field(..., description="Original query")


class DifyClient:
    """Client for interacting with Dify knowledge base API"""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._setup_session()

    def _setup_session(self):
        """Setup aiohttp session with proper configuration"""
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=config.dify.timeout if config.dify else 5)
            self.session = aiohttp.ClientSession(timeout=timeout)

    async def __aenter__(self):
        self._setup_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def retrieve_knowledge(
        self,
        query: str,
        dataset_id: Optional[str] = None,
        retrieval_model: str = "search",
        score_threshold: float = 0.5,
        top_k: int = 3
    ) -> DifyRetrievalResponse:
        """
        Retrieve knowledge from Dify knowledge base

        Args:
            query: Search query
            dataset_id: Dataset ID (optional)
            retrieval_model: Retrieval model
            score_threshold: Minimum relevance score
            top_k: Number of top results

        Returns:
            DifyRetrievalResponse with retrieved records
        """
        if not config.dify or not config.dify.api_key:
            raise ValueError("Dify configuration not properly set")

        # Build request payload
        request_data = DifyRetrievalRequest(
            query=query,
            retrieval_model=retrieval_model,
            score_threshold=score_threshold,
            top_k=top_k
        )

        # Determine dataset ID
        target_dataset_id = dataset_id or config.dify.dataset_id
        if not target_dataset_id:
            raise ValueError("Dataset ID is required")

        # Build API URL
        api_base = config.dify.api_base.rstrip('/')
        url = f"{api_base}/datasets/{target_dataset_id}/retrieve"

        # Build headers
        headers = {
            "Authorization": f"Bearer {config.dify.api_key}",
            "Content-Type": "application/json"
        }

        logger.info(f"Retrieving knowledge from Dify: {query}")

        try:
            async with self.session.post(
                url,
                headers=headers,
                json=request_data.dict()
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return DifyRetrievalResponse(
                        records=data.get("records", []),
                        total=data.get("total", 0),
                        query=query
                    )
                else:
                    error_text = await response.text()
                    logger.error(f"Dify API error {response.status}: {error_text}")
                    raise Exception(f"Dify API error {response.status}: {error_text}")

        except asyncio.TimeoutError:
            logger.error("Dify API request timed out")
            raise Exception("Connection to knowledge base timed out")
        except Exception as e:
            logger.error(f"Error calling Dify API: {str(e)}")
            raise Exception(f"Failed to retrieve knowledge: {str(e)}")

    async def close(self):
        """Close the HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None


# Global client instance
dify_client = DifyClient()
```

### Phase 3: 创建Dify知识库检索工具类 (0.5天)

#### 3.1 创建工具类
创建 [`app/tool/dify_knowledge_base.py`](app/tool/dify_knowledge_base.py)：

```python
import json
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from app.config import config
from app.logger import logger
from app.tool.base import BaseTool, ToolResult
from app.tool.dify_client import dify_client, DifyRetrievalResponse


class KnowledgeRetrievalResult(ToolResult):
    """Structured result for knowledge base retrieval"""

    query: str = Field(description="The search query that was executed")
    results: list = Field(default_factory=list, description="Retrieved knowledge records")
    total_records: int = Field(0, description="Total number of records found")

    def format_output(self) -> str:
        """Format the retrieval results for display"""
        if self.error:
            return self.error

        if not self.results:
            return "No relevant information found in the knowledge base."

        output_lines = [f"Knowledge base search results for '{self.query}':"]

        for i, record in enumerate(self.results, 1):
            content = record.get("content", "")
            score = record.get("score", 0)
            metadata = record.get("metadata", {})

            output_lines.append(f"\n{i}. Content: {content}")
            if score:
                output_lines.append(f"   Relevance Score: {score:.3f}")
            if metadata:
                output_lines.append(f"   Metadata: {json.dumps(metadata, ensure_ascii=False)}")

        return "\n".join(output_lines)


class DifyKnowledgeRetriever(BaseTool):
    """Tool for retrieving knowledge from Dify knowledge base"""

    name: str = "search_internal_knowledge_base"
    description: str = """这是一个内部知识库搜索工具。当用户询问关于公司业务、技术架构、历史项目等非公开信息时，必须优先使用此工具获取上下文。"""
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "(required) 提炼后的搜索关键词或自然语言问题。"
            },
            "dataset_id": {
                "type": "string",
                "description": "(optional) 数据集ID，如果API密钥未绑定特定数据集。"
            },
            "top_k": {
                "type": "integer",
                "description": "(optional) 返回结果数量，默认3个。",
                "default": 3
            },
            "score_threshold": {
                "type": "number",
                "description": "(optional) 最小相关性阈值，默认0.5。",
                "default": 0.5
            }
        },
        "required": ["query"]
    }

    async def execute(
        self,
        query: str,
        dataset_id: Optional[str] = None,
        top_k: int = 3,
        score_threshold: float = 0.5
    ) -> KnowledgeRetrievalResult:
        """
        Execute knowledge retrieval from Dify knowledge base

        Args:
            query: Search query
            dataset_id: Optional dataset ID
            top_k: Number of results to return
            score_threshold: Minimum relevance score

        Returns:
            KnowledgeRetrievalResult with retrieved knowledge
        """
        try:
            # Validate configuration
            if not config.dify or not config.dify.api_key:
                return KnowledgeRetrievalResult(
                    query=query,
                    error="Knowledge base configuration is not properly set. Please configure Dify API settings.",
                    results=[],
                    total_records=0
                )

            # Use configured defaults if not provided
            if top_k == 3 and config.dify.top_k:
                top_k = config.dify.top_k
            if score_threshold == 0.5 and config.dify.score_threshold:
                score_threshold = config.dify.score_threshold

            logger.info(f"Searching knowledge base: {query}")

            # Perform retrieval
            response = await dify_client.retrieve_knowledge(
                query=query,
                dataset_id=dataset_id,
                retrieval_model=config.dify.retrieval_model or "search",
                score_threshold=score_threshold,
                top_k=top_k
            )

            # Check if results are empty
            if not response.records:
                return KnowledgeRetrievalResult(
                    query=query,
                    error="知识库中未找到相关信息。",
                    results=[],
                    total_records=0
                )

            # Create successful result
            result = KnowledgeRetrievalResult(
                query=query,
                results=response.records,
                total_records=response.total
            )

            # Format output
            result.output = result.format_output()

            logger.info(f"Knowledge retrieval successful: {len(response.records)} records found")
            return result

        except ValueError as e:
            logger.error(f"Knowledge retrieval validation error: {str(e)}")
            return KnowledgeRetrievalResult(
                query=query,
                error=f"配置错误: {str(e)}",
                results=[],
                total_records=0
            )

        except Exception as e:
            error_msg = str(e)
            if "timed out" in error_msg.lower():
                error_msg = "连接知识库超时"
            elif "api error" in error_msg.lower():
                error_msg = "知识库服务暂时不可用"
            else:
                error_msg = f"知识库检索失败: {error_msg}"

            logger.error(f"Knowledge retrieval error: {error_msg}")
            return KnowledgeRetrievalResult(
                query=query,
                error=error_msg,
                results=[],
                total_records=0
            )
```

### Phase 4: 工具注册和集成 (0.5天)

#### 4.1 更新工具初始化文件
更新 [`app/tool/__init__.py`](app/tool/__init__.py)：

```python
from app.tool.base import BaseTool
from app.tool.bash import Bash
from app.tool.browser_use_tool import BrowserUseTool
from app.tool.crawl4ai import Crawl4aiTool
from app.tool.create_chat_completion import CreateChatCompletion
from app.tool.dify_knowledge_base import DifyKnowledgeRetriever  # 新增
from app.tool.markdown_document import MarkdownDocumentTool
from app.tool.planning import PlanningTool
from app.tool.str_replace_editor import StrReplaceEditor
from app.tool.terminate import Terminate
from app.tool.tool_collection import ToolCollection
from app.tool.web_search import WebSearch
from app.tool.word_document import WordDocumentTool

__all__ = [
    "BaseTool",
    "Bash",
    "BrowserUseTool",
    "Terminate",
    "StrReplaceEditor",
    "WebSearch",
    "ToolCollection",
    "CreateChatCompletion",
    "PlanningTool",
    "Crawl4aiTool",
    "WordDocumentTool",
    "MarkdownDocumentTool",
    "DifyKnowledgeRetriever",  # 新增
]
```

#### 4.2 更新Manus代理工具集合
更新 [`app/agent/manus.py`](app/agent/manus.py)：

```python
from app.tool import (
    Terminate,
    ToolCollection,
    DifyKnowledgeRetriever,  # 新增
)
# ... 其他导入 ...

class Manus(ToolCallAgent):
    # ... existing code ...

    # Add general-purpose tools to the tool collection
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            PythonExecute(),
            BrowserUseTool(),
            StrReplaceEditor(),
            AskHuman(),
            Terminate(),
            DifyKnowledgeRetriever(),  # 新增
        )
    )
```

#### 4.3 更新系统提示
更新 [`app/prompt/manus.py`](app/prompt/manus.py)：

```python
SYSTEM_PROMPT = (
    "You are OpenManus, an all-capable AI assistant, aimed at solving any task presented by the user. "
    "You have various tools at your disposal that you can call upon to efficiently complete complex requests. "
    "Whether it's programming, information retrieval, file processing, web browsing, or human interaction (only for extreme cases), you can handle it all. "
    "The initial directory is: {directory}\n\n"
    "Tool Usage Policy: You have access to a specialized tool named search_internal_knowledge_base. "
    "Trigger: If the user asks about internal projects, protocols, or company-specific data. "
    "Action: You MUST use this tool to retrieve context before answering. "
    "Prohibition: Do NOT hallucinate answers for internal topics without using this tool."
)

NEXT_STEP_PROMPT = """
Based on user needs, proactively select the most appropriate tool or combination of tools. For complex tasks, you can break down the problem and use different tools step by step to solve it. After using each tool, clearly explain the execution results and suggest the next steps.

Special Instructions:
- When asked about company-specific information, internal processes, or proprietary data, always use the search_internal_knowledge_base tool first
- Do not make up information about internal topics - retrieve it from the knowledge base
- If the knowledge base doesn't contain relevant information, clearly state that and suggest alternatives

If you want to stop the interaction at any point, use the `terminate` tool/function call.
"""
```

### Phase 5: 示例配置文件 (0.5天)

#### 5.1 更新示例配置
更新 [`config/config.example.toml`](config/config.example.toml)：

```toml
# Dify knowledge base configuration (optional)
[dify]
api_base = "https://api.dify.ai/v1"  # Dify API service base URL
api_key = "YOUR_DIFY_API_KEY"        # Dataset-specific API key
dataset_id = "YOUR_DATASET_ID"       # Dataset ID (optional if API key is bound to specific dataset)
retrieval_model = "search"           # Retrieval model to use
score_threshold = 0.5                # Minimum relevance score threshold
top_k = 3                           # Number of top results to retrieve
timeout = 5                         # Request timeout in seconds
max_retries = 3                     # Maximum retry attempts
```

### Phase 6: 单元测试 (0.5天)

#### 6.1 创建测试文件
创建 [`tests/test_dify_knowledge_base.py`](tests/test_dify_knowledge_base.py)：

```python
import asyncio
import pytest
from unittest.mock import Mock, patch, AsyncMock

from app.tool.dify_knowledge_base import DifyKnowledgeRetriever
from app.tool.dify_client import DifyRetrievalResponse


class TestDifyKnowledgeRetriever:
    """Test cases for Dify knowledge base retriever tool"""

    @pytest.fixture
    def retriever(self):
        return DifyKnowledgeRetriever()

    @pytest.fixture
    def mock_config(self):
        with patch('app.tool.dify_knowledge_base.config') as mock_config:
            mock_config.dify = Mock()
            mock_config.dify.api_key = "test_api_key"
            mock_config.dify.api_base = "https://api.dify.ai/v1"
            mock_config.dify.dataset_id = "test_dataset"
            mock_config.dify.retrieval_model = "search"
            mock_config.dify.score_threshold = 0.5
            mock_config.dify.top_k = 3
            yield mock_config

    @pytest.mark.asyncio
    async def test_successful_retrieval(self, retriever, mock_config):
        """Test successful knowledge retrieval"""
        mock_response = DifyRetrievalResponse(
            records=[
                {"content": "Test content 1", "score": 0.8, "metadata": {"source": "doc1"}},
                {"content": "Test content 2", "score": 0.7, "metadata": {"source": "doc2"}}
            ],
            total=2,
            query="test query"
        )

        with patch('app.tool.dify_knowledge_base.dify_client.retrieve_knowledge',
                   new_callable=AsyncMock, return_value=mock_response):
            result = await retriever.execute("test query")

            assert result.query == "test query"
            assert len(result.results) == 2
            assert result.total_records == 2
            assert result.error is None
            assert "Test content 1" in result.output

    @pytest.mark.asyncio
    async def test_empty_results(self, retriever, mock_config):
        """Test handling of empty results"""
        mock_response = DifyRetrievalResponse(
            records=[],
            total=0,
            query="test query"
        )

        with patch('app.tool.dify_knowledge_base.dify_client.retrieve_knowledge',
                   new_callable=AsyncMock, return_value=mock_response):
            result = await retriever.execute("test query")

            assert result.query == "test query"
            assert len(result.results) == 0
            assert result.total_records == 0
            assert "知识库中未找到相关信息" in result.error

    @pytest.mark.asyncio
    async def test_timeout_error(self, retriever, mock_config):
        """Test timeout error handling"""
        with patch('app.tool.dify_knowledge_base.dify_client.retrieve_knowledge',
                   new_callable=AsyncMock,
                   side_effect=Exception("Connection timed out")):
            result = await retriever.execute("test query")

            assert result.query == "test query"
            assert len(result.results) == 0
            assert "连接知识库超时" in result.error

    @pytest.mark.asyncio
    async def test_configuration_error(self, retriever):
        """Test configuration error handling"""
        with patch('app.tool.dify_knowledge_base.config.dify', None):
            result = await retriever.execute("test query")

            assert result.query == "test query"
            assert "配置错误" in result.error or "configuration" in result.error.lower()
```

### Phase 7: 集成测试和验证 (0.5天)

#### 7.1 测试场景
创建 [`tests/integration/test_dify_integration.py`](tests/integration/test_dify_integration.py)：

```python
import asyncio
import pytest
from unittest.mock import patch, Mock

from app.agent.manus import Manus
from app.tool.dify_knowledge_base import DifyKnowledgeRetriever


class TestDifyIntegration:
    """Integration tests for Dify knowledge base with Manus agent"""

    @pytest.mark.asyncio
    async def test_agent_tool_registration(self):
        """Test that Dify tool is properly registered with Manus agent"""
        agent = await Manus.create()

        # Check if Dify tool is in available tools
        tool_names = [tool.name for tool in agent.available_tools.tools]
        assert "search_internal_knowledge_base" in tool_names

        # Verify it's the correct tool type
        dify_tool = next((tool for tool in agent.available_tools.tools
                         if tool.name == "search_internal_knowledge_base"), None)
        assert isinstance(dify_tool, DifyKnowledgeRetriever)

    @pytest.mark.asyncio
    async def test_system_prompt_includes_tool_policy(self):
        """Test that system prompt includes tool usage policy"""
        agent = await Manus.create()

        # Check if system prompt contains tool usage instructions
        assert "search_internal_knowledge_base" in agent.system_prompt
        assert "internal projects" in agent.system_prompt
        assert "company-specific data" in agent.system_prompt

    @pytest.mark.asyncio
    async def test_intent_recognition(self):
        """Test that agent recognizes when to use knowledge base"""
        # This would be a more complex test involving the full agent flow
        # For now, we verify the tool is available and properly configured
        agent = await Manus.create()

        # Simulate a query that should trigger knowledge base search
        test_queries = [
            "公司的上季度财报数据是什么？",
            "我们部门的技术架构文档在哪里？",
            "内部项目的部署流程是什么？"
        ]

        # Verify tool description mentions internal knowledge
        dify_tool = next((tool for tool in agent.available_tools.tools
                         if tool.name == "search_internal_knowledge_base"), None)

        assert dify_tool is not None
        assert "内部知识库" in dify_tool.description
        assert "公司业务" in dify_tool.description
```

## 验收标准验证

### 功能验收测试

#### 1. 意图识别准确
测试用例：
- 输入："上季度财报数据"
- 期望：Agent自动调用search_internal_knowledge_base

#### 2. 信息引用正确
测试用例：
- 知识库包含："Q3收入为1000万元"
- 查询："上季度收入是多少？"
- 期望：回答中包含"1000万元"

#### 3. 故障降级
测试用例：
- API密钥失效
- 期望：返回清晰的错误提示，不崩溃

## 性能和安全要求

### 性能指标
- 端到端调用延迟 < 2000ms
- 支持并发请求处理
- 合理的超时和重试机制

### 安全要求
- 环境变量配置，禁止硬编码
- 日志脱敏处理
- 网络访问白名单配置
- Python 3.9+兼容性

## 部署和运维

### 环境配置
1. 在 `.env` 文件中添加Dify配置：
```bash
DIFY_API_BASE=https://api.dify.ai/v1
DIFY_API_KEY=your_api_key_here
DIFY_DATASET_ID=your_dataset_id_here
```

2. 更新配置文件 `config/config.toml`

### 监控和日志
- 记录每次知识库检索的查询和结果数量
- 监控API响应时间和错误率
- 设置告警机制处理异常情况

## 总结
本实施计划提供了完整的OpenManus与Dify知识库集成方案，包括配置管理、工具开发、系统集成、测试验证等各个环节。按照此计划执行，可以实现企业私有数据的智能检索和问答功能。
