# OpenManus 接入 Dify 知识库 - 需求说明书

| 项目 | 内容 |
| :--- | :--- |
| **文档版本** | v1.0 |
| **最后更新** | 2025-12-05 |
| **状态** | 待评审 |
| **负责人** | AI Assistant |

---

## 1. 项目背景与目标

### 1.1 背景
当前 OpenManus 作为通用智能 Agent，具备强大的任务规划与代码执行能力，但缺乏对企业私有数据（Internal Knowledge）的访问权限。这导致其在处理特定业务咨询、技术运维或内部流程相关任务时，无法提供准确信息。

### 1.2 目标
通过开发自定义工具（Custom Tool），将 **Dify 知识库（RAG Engine）** 的检索能力无缝接入 OpenManus。
实现以下核心能力：
1.  **主动感知**：Agent 能自动识别需查阅私有知识的场景。
2.  **数据获取**：通过 Dify API 获取高相关度的知识片段。
3.  **闭环回答**：结合私有知识与通用逻辑，输出准确解决方案。

---

## 2. 总体架构设计

### 2.1 交互流程图 (Text-based)
```mermaid
graph LR
    User[用户指令] --> OpenManus[OpenManus (大脑)]
    OpenManus -- 意图识别 --> Decision{需要查库?}
    Decision -- 是 --> Tool[工具: DifyRetriever]
    Decision -- 否 --> General[通用回答]
    Tool -- HTTP POST --> Dify[Dify API (知识库)]
    Dify -- 返回 Top-K 片段 --> Tool
    Tool -- 原始文本 --> OpenManus
    OpenManus -- 综合生成 --> Response[最终回答]
2.2 模块边界
OpenManus 端：负责任务拆解、工具路由、上下文理解。

Dify 端：负责文档切片、向量存储、语义检索，仅返回 Raw Text（原始文本）。

3. 功能需求详情
3.1 新增工具：DifyKnowledgeRetriever
在 OpenManus 的 tools 模块下实现一个新的 Python 类。

属性	定义
类名/工具名	search_internal_knowledge_base
功能描述 (Prompt)	Critical Configuration. 需明确声明：“这是一个内部知识库搜索工具。当用户询问关于[公司业务/技术架构/历史项目]等非公开信息时，必须优先使用此工具获取上下文。”
输入参数	query (string): 提炼后的搜索关键词或自然语言问题。
输出结果	content (string): 检索到的 Top-K 文档片段拼接而成的文本。

3.2 接口对接规范 (Dify Side)
目标接口：POST /v1/datasets/{dataset_id}/retrieve (知识库检索接口)

认证方式：Authorization: Bearer {API_KEY}

请求Payload示例：

JSON

{
  "query": "OpenManus 部署流程",
  "retrieval_model": "search",
  "score_threshold": 0.5,
  "top_k": 3
}
异常处理：

超时：超过 5s 未响应，捕获异常并返回“连接知识库超时”。

空结果：若 records 为空，返回“知识库中未找到相关信息”。

3.3 配置管理
需在 .env 文件中增加以下配置项，严禁硬编码：

DIFY_API_BASE: Dify API 服务地址 (e.g., https://api.dify.ai/v1)

DIFY_API_KEY: 数据集专属 API Key

DIFY_DATASET_ID: (可选) 如果 API Key 不绑定特定数据集，需通过 ID 指定。

4. System Prompt 调优建议
为确保工具被正确调用，需在 OpenManus 的 System Prompt 中增加如下指令：

Tool Usage Policy: You have access to a specialized tool named search_internal_knowledge_base.

Trigger: If the user asks about internal projects, protocols, or company-specific data.

Action: You MUST use this tool to retrieve context before answering.

Prohibition: Do NOT hallucinate answers for internal topics without using this tool.

5. 非功能性需求 (NFR)
性能：工具端到端调用延迟应 < 2000ms。

安全：

Agent 运行环境（Sandbox）需开通对 Dify 服务的网络访问白名单。

日志脱敏：避免在控制台明文打印返回的完整知识库内容。

兼容性：代码需兼容 Python 3.9+ 环境。

6. 实施路线图 (Roadmap)
Phase 1: 验证 (0.5d)

使用 curl 调试 Dify 接口，确定最佳阈值参数。

Phase 2: 开发 (0.5d)

完成 Python Tool 代码编写与单元测试。

Phase 3: 集成 (0.5d)

注册工具至 OpenManus，配置环境变量与 Prompt。

Phase 4: 验收 (0.5d)

针对 3 个典型场景（有结果、无结果、超时）进行测试。

7. 验收标准
意图识别准确：询问“上季度财报数据”时，Agent 自动调用 search_internal_knowledge_base。

信息引用正确：Agent 回答中包含知识库特有的细节信息。

故障降级：当 API 密钥失效时，Agent 能够给出清晰的错误提示，而不是崩溃。
