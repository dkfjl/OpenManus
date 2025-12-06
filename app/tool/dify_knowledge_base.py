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
