# OpenManus 提示词库功能 - README 更新内容

## ✨ 新功能：提示词库 (Prompt Library)

OpenManus 现在支持统一的提示词管理功能，帮助您更高效地组织和复用提示词模板。

### 核心特性

- 📚 **推荐模板库**：12个精选的高质量提示词模板，覆盖常见场景
- 💾 **个人提示词管理**：创建、更新、删除您的自定义提示词
- 🔄 **变量替换**：使用 `{variable}` 占位符实现动态内容替换
- 🤖 **Agent 集成**：通过 PromptLibraryTool 让 Agent 访问提示词库
- ⚡ **高性能**：P50 延迟 < 2ms，支持高并发访问
- 🔒 **安全可靠**：完整的权限控制和并发冲突检测

### 快速开始

#### 1. 列出推荐模板

```bash
curl http://localhost:8000/console/api/prompt/overview?type=recommended
```

#### 2. 创建个人提示词

```bash
curl -X POST http://localhost:8000/console/api/prompts \
  -H "Content-Type: application/json" \
  -H "X-User-Id: your_user_id" \
  -d '{
    "name": "数据分析助手",
    "description": "用于数据分析任务",
    "prompt": "你是{role}，请分析{data_source}的数据",
    "ownerId": "your_user_id"
  }'
```

#### 3. 在 /run 接口中使用提示词

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "promptId": "template_id",
    "promptType": "recommended",
    "mergeVars": {
      "role": "数据分析师",
      "data_source": "销售数据"
    },
    "prompt": "请重点关注Q4季度"
  }'
```

### 预置模板

系统预置了12个高质量模板：

| 模板名称 | 适用场景 |
|---------|---------|
| 通用结构 | 多种场景通用框架 |
| 需求分析模板 | 产品需求文档撰写 |
| 代码生成助手 | 编程任务辅助 |
| 文案创作模板 | 营销文案、公众号 |
| 数据分析助手 | 数据分析与洞察 |
| 技术文档撰写 | API文档、技术规范 |
| 问题诊断助手 | Bug分析与解决 |
| 学习计划制定 | 个人学习路径规划 |
| 会议纪要整理 | 会议记录结构化 |
| 邮件撰写助手 | 商务邮件撰写 |
| 代码审查助手 | 代码质量检查 |
| 头脑风暴引导 | 创意激发与整理 |

### API 端点

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/console/api/prompt/overview` | 列出提示词（支持分页、搜索） |
| GET | `/console/api/prompt/detail` | 获取提示词详情 |
| POST | `/console/api/prompts` | 创建个人提示词 |
| PUT | `/console/api/prompts/:id` | 更新个人提示词 |
| DELETE | `/console/api/prompts/:id` | 删除个人提示词 |

### Agent 工具使用

Agent 可以通过 `prompt_library` 工具访问提示词库：

```python
# Agent 对话示例
User: 帮我找一个代码生成的提示词模板

Agent: 我会使用提示词库工具查找代码生成模板
[调用 prompt_library 工具]

Agent: 找到了"代码生成助手"模板，该模板适用于编程任务辅助...
```

### 性能指标

基于100次请求的性能测试结果：

- 列出推荐模板：P50 = 1.02ms
- 获取提示词详情：P50 = 1.34ms
- 列出个人提示词：P50 = 1.41ms
- 创建提示词：P50 = 3.44ms

### 详细文档

- 📖 [开发者指南](docs/prompt_library_guide.md)
- 📝 [需求说明书](feature修改说明书/openmanus_prompt_library_integration.md)
- 🚀 [实施计划](feature修改说明书/openmanus_prompt_library_implementation_plan.md)

### 测试

运行提示词库相关测试：

```bash
# API 集成测试
python test_prompt_api.py

# E2E 测试（Agent + /run 接口）
python test_prompt_e2e.py

# 性能测试
python test_prompt_performance.py
```

### 配置说明

提示词库数据存储在 `prompt_library/` 目录：

```
prompt_library/
├── index.json          # 索引文件
└── prompts/            # 提示词内容文件
    ├── {uuid1}.json
    └── {uuid2}.json
```

推荐模板存储在 `assets/prompts/recommended.json`

---

**注意**：将以上内容添加到 README.md 的 Features 或 Usage 章节中。
