# OpenManus 提示词库 - API 使用示例

本文档提供提示词库 API 的详细使用示例，涵盖所有常见场景。

---

## 📚 目录

1. [推荐模板相关](#1-推荐模板相关)
2. [个人提示词 CRUD](#2-个人提示词-crud)
3. [搜索与分页](#3-搜索与分页)
4. [变量替换与合并](#4-变量替换与合并)
5. [Agent 工具调用](#5-agent-工具调用)
6. [错误处理](#6-错误处理)

---

## 1. 推荐模板相关

### 1.1 列出所有推荐模板

**请求：**
```bash
curl -X GET "http://localhost:8000/console/api/prompt/overview?type=recommended&page=1&pageSize=20"
```

**响应示例：**
```json
{
  "items": [
    {
      "id": "f6f2e4e2-0d22-4a1f-9c11-8a3c9a12e7f2",
      "name": "通用结构",
      "description": "适用于多种场景的提示词结构"
    },
    {
      "id": "a3b5c7d9-1e2f-4a5b-8c9d-0e1f2a3b4c5d",
      "name": "需求分析模板",
      "description": "产品需求文档撰写"
    }
  ],
  "total": 12,
  "page": 1,
  "pageSize": 20
}
```

### 1.2 获取推荐模板详情

**请求：**
```bash
curl -X GET "http://localhost:8000/console/api/prompt/detail?type=recommended&id=f6f2e4e2-0d22-4a1f-9c11-8a3c9a12e7f2"
```

**响应示例：**
```json
{
  "data": {
    "id": "f6f2e4e2-0d22-4a1f-9c11-8a3c9a12e7f2",
    "name": "通用结构",
    "description": "适用于多种场景的提示词结构",
    "prompt": "# 角色\n你是{role}\n\n# 目标\n{goal}\n\n# 约束\n{constraints}"
  },
  "message": "获取成功"
}
```

### 1.3 按名称搜索推荐模板

**请求：**
```bash
curl -X GET "http://localhost:8000/console/api/prompt/overview?type=recommended&name=代码"
```

**响应示例：**
```json
{
  "items": [
    {
      "id": "b4c6d8e0-2f3a-5b6c-9d0e-1f2a3b4c5d6e",
      "name": "代码生成助手",
      "description": "编程任务辅助"
    },
    {
      "id": "d2e4f6a8-0b1c-3d4e-7f8a-9b0c1d2e3f4a",
      "name": "代码审查助手",
      "description": "代码质量检查与改进建议"
    }
  ],
  "total": 2,
  "page": 1,
  "pageSize": 20
}
```

---

## 2. 个人提示词 CRUD

### 2.1 创建个人提示词

**请求：**
```bash
curl -X POST "http://localhost:8000/console/api/prompts" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: user_alice" \
  -d '{
    "name": "Python单元测试生成",
    "description": "为Python函数生成单元测试",
    "prompt": "# 角色\n你是Python测试专家\n\n# 任务\n为以下{language}函数生成完整的单元测试：\n\n```{language}\n{code}\n```\n\n# 要求\n- 使用pytest框架\n- 覆盖正常情况和边界情况\n- 添加必要的注释\n- 测试代码清晰易读",
    "ownerId": "user_alice"
  }'
```

**响应示例：**
```json
{
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Python单元测试生成"
  },
  "message": "创建成功"
}
```

### 2.2 列出个人提示词

**请求：**
```bash
curl -X GET "http://localhost:8000/console/api/prompt/overview?type=personal&page=1&pageSize=10" \
  -H "X-User-Id: user_alice"
```

**响应示例：**
```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Python单元测试生成",
      "description": "为Python函数生成单元测试"
    }
  ],
  "total": 1,
  "page": 1,
  "pageSize": 10
}
```

### 2.3 获取个人提示词详情

**请求：**
```bash
curl -X GET "http://localhost:8000/console/api/prompt/detail?type=personal&id=550e8400-e29b-41d4-a716-446655440000" \
  -H "X-User-Id: user_alice"
```

**响应示例：**
```json
{
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Python单元测试生成",
    "description": "为Python函数生成单元测试",
    "prompt": "# 角色\n你是Python测试专家\n\n# 任务\n...",
    "ownerId": "user_alice",
    "version": 1,
    "createdAt": "2025-12-06T10:30:00Z",
    "updatedAt": "2025-12-06T10:30:00Z"
  },
  "message": "获取成功"
}
```

### 2.4 更新个人提示词

**请求：**
```bash
curl -X PUT "http://localhost:8000/console/api/prompts/550e8400-e29b-41d4-a716-446655440000" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: user_alice" \
  -d '{
    "name": "Python单元测试生成器（增强版）",
    "description": "生成高质量的Python单元测试，支持多种框架",
    "version": 1
  }'
```

**响应示例：**
```json
{
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "version": 2
  },
  "message": "更新成功"
}
```

### 2.5 删除个人提示词

**请求：**
```bash
curl -X DELETE "http://localhost:8000/console/api/prompts/550e8400-e29b-41d4-a716-446655440000" \
  -H "X-User-Id: user_alice"
```

**响应示例：**
```json
{
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000"
  },
  "message": "删除成功"
}
```

---

## 3. 搜索与分页

### 3.1 名称模糊搜索

**请求：**
```bash
curl -X GET "http://localhost:8000/console/api/prompt/overview?type=personal&name=测试&page=1&pageSize=10" \
  -H "X-User-Id: user_alice"
```

**说明**：返回名称包含"测试"的所有个人提示词

### 3.2 分页查询

**第一页：**
```bash
curl -X GET "http://localhost:8000/console/api/prompt/overview?type=personal&page=1&pageSize=5" \
  -H "X-User-Id: user_alice"
```

**第二页：**
```bash
curl -X GET "http://localhost:8000/console/api/prompt/overview?type=personal&page=2&pageSize=5" \
  -H "X-User-Id: user_alice"
```

### 3.3 限制返回数量

**请求：**
```bash
# 只返回前3条
curl -X GET "http://localhost:8000/console/api/prompt/overview?type=recommended&page=1&pageSize=3"
```

---

## 4. 变量替换与合并

### 4.1 使用 /run 接口注入提示词

**场景：使用推荐模板 + 变量替换**

**请求：**
```bash
curl -X POST "http://localhost:8000/run" \
  -H "Content-Type: application/json" \
  -d '{
    "promptId": "f6f2e4e2-0d22-4a1f-9c11-8a3c9a12e7f2",
    "promptType": "recommended",
    "mergeVars": {
      "role": "数据分析师",
      "goal": "分析Q4季度的销售数据，找出增长点",
      "constraints": "只使用Python和Pandas，不使用外部API"
    },
    "prompt": "另外，请特别关注北京地区的数据"
  }'
```

**处理流程：**
1. 加载模板：`# 角色\n你是{role}\n\n# 目标\n{goal}\n\n# 约束\n{constraints}`
2. 替换变量后：`# 角色\n你是数据分析师\n\n# 目标\n分析Q4季度的销售数据，找出增长点\n\n# 约束\n只使用Python和Pandas，不使用外部API`
3. 合并额外prompt：`# 角色\n你是数据分析师\n\n# 目标\n分析Q4季度的销售数据，找出增长点\n\n# 约束\n只使用Python和Pandas，不使用外部API\n\n另外，请特别关注北京地区的数据`
4. 传递给 Agent 执行

### 4.2 使用个人提示词

**请求：**
```bash
curl -X POST "http://localhost:8000/run" \
  -H "Content-Type: application/json" \
  -d '{
    "promptId": "550e8400-e29b-41d4-a716-446655440000",
    "promptType": "personal",
    "mergeVars": {
      "language": "Python",
      "code": "def add(a, b):\n    return a + b"
    }
  }'
```

### 4.3 变量缺失处理

如果模板中有 `{variable}` 但 mergeVars 中没有提供，占位符会保留：

**模板：**
```
你是{role}，任务是{task}，约束是{constraints}
```

**mergeVars：**
```json
{
  "role": "开发工程师",
  "task": "编写代码"
}
```

**替换后：**
```
你是开发工程师，任务是编写代码，约束是{constraints}
```

---

## 5. Agent 工具调用

### 5.1 Python 代码示例

```python
import os
from app.tool.prompt_library import PromptLibraryTool

async def agent_use_prompt_library():
    # 设置当前用户（Agent 使用时需要）
    os.environ["CURRENT_USER_ID"] = "user_alice"

    # 创建工具实例
    tool = PromptLibraryTool()

    # 1. 列出推荐模板
    result = await tool.execute(
        action="list_recommended",
        page=1,
        page_size=5
    )
    print(result.output)

    # 2. 创建个人提示词
    result = await tool.execute(
        action="create_personal",
        name="我的提示词",
        prompt="内容包含{variable}",
        description="测试"
    )
    print(result.output)

    # 3. 获取详情
    result = await tool.execute(
        action="get_prompt",
        prompt_type="recommended",
        prompt_id="f6f2e4e2-0d22-4a1f-9c11-8a3c9a12e7f2"
    )
    print(result.output)
```

### 5.2 Agent 对话示例

**用户请求：**
```
帮我找一个用于代码生成的提示词模板
```

**Agent 执行：**
```python
# Agent 内部调用
tool.execute(
    action="list_recommended",
    name="代码生成"
)
```

**Agent 响应：**
```
我找到了"代码生成助手"模板，适用于编程任务辅助。
该模板支持的变量有：
- {language}: 编程语言
- {task}: 具体任务描述
```

---

## 6. 错误处理

### 6.1 提示词不存在（404）

**请求：**
```bash
curl -X GET "http://localhost:8000/console/api/prompt/detail?type=personal&id=non-existent-id" \
  -H "X-User-Id: user_alice"
```

**响应：**
```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Prompt not found with id: non-existent-id"
  }
}
```

### 6.2 权限被拒绝（403）

**场景：尝试访问其他用户的提示词**

**请求：**
```bash
curl -X GET "http://localhost:8000/console/api/prompt/detail?type=personal&id=550e8400-e29b-41d4-a716-446655440000" \
  -H "X-User-Id: user_bob"  # 该提示词属于 user_alice
```

**响应：**
```json
{
  "error": {
    "code": "FORBIDDEN",
    "message": "Access denied: you don't have permission to access this prompt"
  }
}
```

### 6.3 版本冲突（409）

**场景：并发更新导致版本不匹配**

**请求：**
```bash
curl -X PUT "http://localhost:8000/console/api/prompts/550e8400-e29b-41d4-a716-446655440000" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: user_alice" \
  -d '{
    "name": "新名称",
    "version": 1
  }'
```

**响应（如果当前版本已是2）：**
```json
{
  "error": {
    "code": "CONFLICT",
    "message": "Version mismatch: expected version 2, got 1"
  }
}
```

**解决方案：**
```bash
# 1. 先获取最新版本
curl -X GET "http://localhost:8000/console/api/prompt/detail?type=personal&id=550e8400-e29b-41d4-a716-446655440000" \
  -H "X-User-Id: user_alice"

# 2. 使用最新版本号重新提交
curl -X PUT "http://localhost:8000/console/api/prompts/550e8400-e29b-41d4-a716-446655440000" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: user_alice" \
  -d '{
    "name": "新名称",
    "version": 2
  }'
```

### 6.4 数据验证错误（400）

**场景：名称过长**

**请求：**
```bash
curl -X POST "http://localhost:8000/console/api/prompts" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: user_alice" \
  -d '{
    "name": "这是一个超级超级超级超级长的名称",
    "prompt": "内容",
    "ownerId": "user_alice"
  }'
```

**响应：**
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Name length exceeds maximum 20 characters"
  }
}
```

### 6.5 缺少必填字段（422）

**请求：**
```bash
curl -X POST "http://localhost:8000/console/api/prompts" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: user_alice" \
  -d '{
    "name": "测试"
  }'
```

**响应：**
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "prompt"],
      "msg": "Field required"
    }
  ]
}
```

---

## 7. 完整使用流程示例

### 场景：创建并使用一个数据分析提示词

**步骤 1：创建提示词**
```bash
curl -X POST "http://localhost:8000/console/api/prompts" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: analyst_001" \
  -d '{
    "name": "销售数据分析",
    "description": "分析销售数据的专用模板",
    "prompt": "# 角色\n你是{role}\n\n# 数据源\n{data_source}\n\n# 分析维度\n{dimensions}\n\n# 输出要求\n1. 数据概览\n2. 关键指标\n3. 趋势分析\n4. 建议",
    "ownerId": "analyst_001"
  }'
```

**步骤 2：获取创建的ID并验证**
```bash
# 假设返回的ID是：abc123
curl -X GET "http://localhost:8000/console/api/prompt/detail?type=personal&id=abc123" \
  -H "X-User-Id: analyst_001"
```

**步骤 3：在 /run 接口中使用**
```bash
curl -X POST "http://localhost:8000/run" \
  -H "Content-Type: application/json" \
  -d '{
    "promptId": "abc123",
    "promptType": "personal",
    "mergeVars": {
      "role": "高级数据分析师",
      "data_source": "2024年Q4销售数据（CSV格式）",
      "dimensions": "地区、产品类别、销售渠道"
    },
    "prompt": "重点关注同比增长率超过20%的产品"
  }'
```

**步骤 4：根据需要更新模板**
```bash
curl -X PUT "http://localhost:8000/console/api/prompts/abc123" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: analyst_001" \
  -d '{
    "description": "分析销售数据的专用模板（支持多维度分析）",
    "version": 1
  }'
```

---

## 8. 最佳实践

### 8.1 命名规范

- ✅ 好的名称：`Python单元测试生成`、`产品需求文档模板`
- ❌ 不好的名称：`模板1`、`test`、`我的提示词`

### 8.2 变量设计

- 使用语义化的变量名：`{role}` > `{r}`
- 在描述中说明需要哪些变量
- 提供变量使用示例

### 8.3 版本控制

- 更新时始终传递 version 参数
- 处理版本冲突异常并重试
- 在高并发场景下特别注意

### 8.4 性能优化

- 推荐模板自动缓存，访问速度极快
- 个人提示词分页查询，避免一次性加载过多数据
- 使用名称搜索缩小结果范围

---

**文档结束**

更多详细信息请参考 [开发者指南](prompt_library_guide.md)
