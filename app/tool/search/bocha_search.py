from typing import Any, Dict, List, Optional

import requests

from app.config import config
from app.logger import logger
from app.tool.search.base import SearchItem, WebSearchEngine
from pydantic import PrivateAttr

# Module-level constant to avoid Pydantic scanning class attributes
BOCHA_API_ENDPOINT = "https://api.bocha.cn/v1/web-search"


class BochaSearchEngine(WebSearchEngine):
    """博查AI搜索服务实现"""

    _session: requests.Session = PrivateAttr(default_factory=requests.Session)

    def __init__(self, **data):
        """初始化博查搜索服务"""
        super().__init__(**data)
        # 设置默认请求头
        self._session.headers.update(
            {"Content-Type": "application/json", "Accept": "application/json"}
        )

    def _get_api_key(self) -> Optional[str]:
        """从配置中获取API密钥"""
        scfg = getattr(config, "search_config", None)
        return getattr(scfg, "bocha_api_key", None) if scfg else None

    def _build_request_payload(
        self, query: str, num_results: int = 10, **kwargs
    ) -> Dict[str, Any]:
        """构建API请求体"""
        payload = {
            "query": query,
            "count": min(50, max(1, num_results)),  # 限制在1-50之间
        }

        # 从kwargs或配置中获取可选参数
        scfg = getattr(config, "search_config", None)

        # 时间范围
        freshness = kwargs.get("freshness") or (
            getattr(scfg, "bocha_freshness", None) if scfg else None
        )
        if freshness:
            payload["freshness"] = freshness

        # 是否显示摘要
        summary = kwargs.get("summary") or (
            getattr(scfg, "bocha_summary", False) if scfg else False
        )
        payload["summary"] = summary

        # 包含的网站
        include = kwargs.get("include") or (
            getattr(scfg, "bocha_include", None) if scfg else None
        )
        if include:
            payload["include"] = include

        # 排除的网站
        exclude = kwargs.get("exclude") or (
            getattr(scfg, "bocha_exclude", None) if scfg else None
        )
        if exclude:
            payload["exclude"] = exclude

        return payload

    def _parse_api_response(self, response_data: Dict[str, Any]) -> List[SearchItem]:
        """解析博查API响应并转换为SearchItem列表"""
        results = []

        # 检查响应结构
        if not isinstance(response_data, dict):
            logger.warning("博查API响应格式异常：不是有效的JSON对象")
            return results

        # 获取主要数据
        data = response_data.get("data")
        if not data:
            logger.warning("博查API响应中没有data字段")
            return results

        # 获取网页搜索结果
        web_pages = data.get("webPages", {})
        if not web_pages:
            logger.info("博查API响应中没有webPages数据")
            return results

        # 获取搜索结果列表
        values = web_pages.get("value", [])
        if not values:
            logger.info("博查API响应中没有搜索结果")
            return results

        # 转换每个搜索结果
        for i, item in enumerate(values):
            try:
                # 提取基本信息
                title = item.get("name", f"博查结果 {i+1}")
                url = item.get("url", "")

                # 获取描述信息，优先使用summary，其次使用snippet
                description = item.get("summary") or item.get("snippet", "")

                # 创建SearchItem对象
                search_item = SearchItem(
                    title=title,
                    url=url,
                    description=description if description else None,
                )
                results.append(search_item)

            except Exception as e:
                logger.warning(f"解析博查搜索结果时出错: {e}")
                continue

        return results

    def perform_search(
        self, query: str, num_results: int = 10, *args, **kwargs
    ) -> List[SearchItem]:
        """
        执行博查AI搜索

        Args:
            query: 搜索关键词
            num_results: 返回结果数量（1-50）
            *args: 额外参数
            **kwargs: 额外关键字参数（支持freshness, summary, include, exclude）

        Returns:
            List[SearchItem]: 搜索结果列表
        """
        if not query:
            logger.warning("搜索查询为空")
            return []

        api_key = self._get_api_key()
        if not api_key:
            logger.warning("未配置博查API密钥")
            return []

        try:
            # 构建请求
            # Bocha 单次最大返回 10 条，强制裁剪
            effective_count = min(10, max(1, num_results))
            payload = self._build_request_payload(query, effective_count, **kwargs)
            headers = {"Authorization": f"Bearer {api_key}"}

            # 发送请求
            logger.info(f"向博查API发送搜索请求: {query}")
            response = self._session.post(
                BOCHA_API_ENDPOINT, json=payload, headers=headers, timeout=30
            )

            # 检查响应状态
            if response.status_code != 200:
                logger.warning(
                    f"博查API返回非200状态码: {response.status_code}, "
                    f"响应内容: {response.text[:200]}"
                )
                return []

            # 解析响应
            response_data = response.json()
            results = self._parse_api_response(response_data)
            # 去重（同一 URL 只保留一次）并限制到最大 10 条
            seen = set()
            deduped: List[SearchItem] = []
            for item in results:
                try:
                    key = (item.url or "").strip()
                except Exception:
                    key = ""
                if not key or key in seen:
                    continue
                seen.add(key)
                deduped.append(item)

            final = deduped[:effective_count]
            logger.info(f"博查搜索成功，返回 {len(final)} 条结果（原始 {len(results)}）")
            return final

        except requests.exceptions.Timeout:
            logger.error("博查API请求超时")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"博查API请求异常: {e}")
            return []
        except Exception as e:
            logger.error(f"博查搜索过程中发生未知错误: {e}")
            return []
