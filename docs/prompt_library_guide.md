# OpenManus 提示词库 - 开发者指南

**版本**: v1.0
**最后更新**: 2025-12-06

---

## 📚 目录

- [1. 功能概述](#1-功能概述)
- [2. 快速开始](#2-快速开始)
- [3. API 使用指南](#3-api-使用指南)
- [4. Agent 工具集成](#4-agent-工具集成)
- [5. 推荐模板管理](#5-推荐模板管理)
- [6. 扩展与迁移](#6-扩展与迁移)
- [7. 性能优化](#7-性能优化)
- [8. 故障排查](#8-故障排查)

---

## 1. 功能概述

提示词库为 OpenManus 系统提供了统一的提示词管理能力，包括：

### 1.1 核心功能

- **推荐模板管理**：系统预置的高质量提示词模板（只读）
- **个人提示词管理**：用户自定义的 CRUD 操作
- **变量替换**：支持 `{variable}` 占位符动态替换
- **Agent 工具集成**：通过 PromptLibraryTool 提供工具调用能力
- **/run 接口集成**：支持 promptId 注入和变量合并

### 1.2 技术特点

- **文件存储**：基于 JSON 文件的轻量级存储方案
- **并发安全**：文件锁机制确保多进程安全
- **高性能缓存**：推荐模板内存缓存，P50 延迟 < 2ms
- **完整权限控制**：基于 ownerId 的资源隔离
- **版本控制**：乐观锁机制防止并发冲突

---

## 2. 快速开始

### 2.1 环境要求

- Python >= 3.8
- FastAPI
- 依赖包：`pydantic`, `fcntl` (Unix-like系统)

### 2.2 目录结构

```
ai_bridge/
├── app/
│   ├── api/
│   │   ├── routes/
│   │   │   └── prompt.py          # 提示词路由
│   │   ├── schemas_prompt.py      # 数据模型
│   │   └── error_handlers.py      # 错误处理
│   ├── services/
│   │   ├── prompt_service.py      # 业务逻辑层
│   │   └── prompt_storage.py      # 存储层
│   └── tool/
│       └── prompt_library.py      # Agent 工具
├── assets/
│   └── prompts/
│       └── recommended.json       # 推荐模板数据
└── prompt_library/                # 运行时数据目录
    ├── index.json                 # 索引文件
    └── prompts/                   # 提示词内容文件
        ├── {uuid1}.json
        └── {uuid2}.json
```

### 2.3 启动服务

```bash
# 启动 FastAPI 服务
uvicorn app.app:app --reload --port 8000

# 验证接口可用
curl http://localhost:8000/console/api/prompt/overview?type=recommended
```

---

## 3. API 使用指南

### 3.1 获取推荐模板列表

**请求示例：**
```bash
curl -X GET "http://localhost:8000/console/api/prompt/overview?type=recommended&page=1&pageSize=10"
```

**响应示例：**
```json
{
  "items": [
    {
      "id": "f6f2e4e2-0d22-4a1f-9c11-8a3c9a12e7f2",
      "name": "通用结构",
      "description": "适用于多种场景的提示词结构"
    }
  ],
  "total": 12,
  "page": 1,
  "pageSize": 10
}
```

### 3.2 创建个人提示词

**请求示例：**
```bash
curl -X POST "http://localhost:8000/console/api/prompts" \
  -H "Content-Type: application/json" \
  -H "X-User-Id: user123" \
  -d '{
    "name": "我的提示词",
    "description": "用于数据分析的提示词",
    "prompt": "你是{role}，你的任务是{task}",
    "ownerId": "user123"
  }'
```

**响应示例：**
```json
{
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "我的提示词"
  },
  "message": "创建成功"
}
```

### 3.3 使用 /run 接口注入提示词

**请求示例：**
```bash
curl -X POST "http://localhost:8000/run" \
  -H "Content-Type: application/json" \
  -d '{
    "promptId": "f6f2e4e2-0d22-4a1f-9c11-8a3c9a12e7f2",
    "promptType": "recommended",
    "mergeVars": {
      "role": "数据分析师",
      "goal": "分析Q4销售数据",
      "constraints": "只使用Python和Pandas"
    },
    "prompt": "请重点关注增长率"
  }'
```

**处理流程：**
1. 加载 promptId 对应的模板
2. 使用 mergeVars 替换模板中的 `{variable}`
3. 将替换后的模板与 prompt 字段合并
4. 传递给 Agent 执行

---

## 4. Agent 工具集成

### 4.1 使用 PromptLibraryTool

Agent 可以通过工具调用提示词库的所有功能。

**工具初始化（已自动注册）：**
```python
from app.tool.prompt_library import PromptLibraryTool

tool = PromptLibraryTool()
```

**支持的操作：**

#### 4.1.1 列出推荐模板
```python
result = await tool.execute(
    action="list_recommended",
    page=1,
    page_size=10
)
```

#### 4.1.2 获取模板详情
```python
result = await tool.execute(
    action="get_prompt",
    prompt_type="recommended",
    prompt_id="f6f2e4e2-0d22-4a1f-9c11-8a3c9a12e7f2"
)
```

#### 4.1.3 创建个人提示词
```python
import os
os.environ["CURRENT_USER_ID"] = "user123"  # 设置当前用户

result = await tool.execute(
    action="create_personal",
    name="Agent创建的提示词",
    prompt="这是内容，包含{variable}",
    description="描述信息"
)
```

#### 4.1.4 更新个人提示词
```python
result = await tool.execute(
    action="update_personal",
    prompt_id="550e8400-e29b-41d4-a716-446655440000",
    name="更新后的名称",
    version=1  # 用于并发控制
)
```

#### 4.1.5 删除个人提示词
```python
result = await tool.execute(
    action="delete_personal",
    prompt_id="550e8400-e29b-41d4-a716-446655440000"
)
```

### 4.2 在 Manus Agent 中调用

PromptLibraryTool 已自动注册到 Manus 和 SandboxManus Agent。

**示例对话：**
```
User: 帮我查找名为"代码生成助手"的推荐模板

Agent: 我会使用 prompt_library 工具查找该模板
[调用工具: list_recommended, name="代码生成助手"]

Agent: 找到了！该模板适用于编程任务辅助...
```

---

## 5. 推荐模板管理

### 5.1 添加新的推荐模板

**步骤 1：编辑推荐模板文件**

编辑 `assets/prompts/recommended.json`：

```json
[
  {
    "id": "新的UUID",
    "name": "模板名称",
    "description": "简短描述（≤50字）",
    "prompt": "# 角色\n你是{role}\n\n# 任务\n{task}\n\n# 要求\n{requirements}"
  }
]
```

**步骤 2：生成唯一 ID**

```python
import uuid
print(str(uuid.uuid4()))  # 例如：f6f2e4e2-0d22-4a1f-9c11-8a3c9a12e7f2
```

**步骤 3：设计变量占位符**

使用 `{variable_name}` 语法定义可替换的变量：
- ✅ 好的命名：`{role}`, `{task}`, `{data_source}`
- ❌ 避免使用：`{x}`, `{temp}`, `{value1}`

**步骤 4：重启服务**

```bash
# 推荐模板使用了 @lru_cache，需要重启服务生效
uvicorn app.app:app --reload
```

### 5.2 模板设计最佳实践

#### 5.2.1 结构规范

推荐使用以下结构：
```
# 角色
你是{role}

# 任务/目标
{task}

# 要求/约束
- 要求1
- 要求2

# 输出格式（可选）
{output_format}
```

#### 5.2.2 变量命名规范

| 变量名 | 用途 | 示例 |
|--------|------|------|
| `{role}` | 角色定位 | "数据分析师"、"产品经理" |
| `{task}` | 具体任务 | "分析Q4销售数据" |
| `{goal}` | 目标描述 | "提升转化率" |
| `{constraints}` | 约束条件 | "只使用Python" |
| `{language}` | 编程语言 | "Python"、"JavaScript" |
| `{style}` | 风格要求 | "专业"、"轻松" |

#### 5.2.3 质量检查清单

- [ ] 模板名称清晰，≤20字
- [ ] 描述准确，≤50字
- [ ] 变量命名语义化
- [ ] 提供使用示例
- [ ] 格式符合 Markdown 规范
- [ ] ID 全局唯一（UUID格式）

---

## 6. 扩展与迁移

### 6.1 迁移到数据库

当数据量增长或需要更强的查询能力时，可以迁移到数据库存储。

#### 6.1.1 数据库表设计

**prompts 表：**
```sql
CREATE TABLE prompts (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(20) NOT NULL,
    description VARCHAR(50),
    prompt TEXT NOT NULL,
    owner_id VARCHAR(100) NOT NULL,
    version INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_owner_name (owner_id, name),
    INDEX idx_created_at (created_at)
);
```

**recommended_prompts 表：**
```sql
CREATE TABLE recommended_prompts (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(20) NOT NULL UNIQUE,
    description VARCHAR(50),
    prompt TEXT NOT NULL,
    category VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 6.1.2 迁移步骤

**步骤 1：创建新的 Storage 实现**

```python
# app/services/prompt_storage_db.py
from sqlalchemy import create_engine
from app.services.prompt_storage import PromptStorage

class PromptStorageDB(PromptStorage):
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        # ... 实现数据库操作

    def create(self, name, prompt, owner_id, description=None):
        # 使用 SQL INSERT
        pass

    def get(self, prompt_id, owner_id):
        # 使用 SQL SELECT
        pass
```

**步骤 2：数据迁移脚本**

```python
# scripts/migrate_to_db.py
import json
from pathlib import Path
from app.services.prompt_storage_db import PromptStorageDB

def migrate_file_to_db():
    # 读取文件数据
    index_file = Path("prompt_library/index.json")
    with open(index_file) as f:
        data = json.load(f)

    # 写入数据库
    db_storage = PromptStorageDB("postgresql://user:pass@localhost/db")
    for prompt_id, prompt_meta in data["prompts"].items():
        # ... 插入数据
        pass

if __name__ == "__main__":
    migrate_file_to_db()
```

**步骤 3：切换存储实现**

```python
# app/services/prompt_service.py
from app.services.prompt_storage_db import PromptStorageDB

class PromptService:
    def __init__(self):
        # 从环境变量选择存储方式
        if config.use_database:
            self.storage = PromptStorageDB(config.database_url)
        else:
            self.storage = PromptStorage()
```

### 6.2 添加新功能

#### 6.2.1 实现软删除

修改 `PromptStorage.delete()` 方法：

```python
def delete(self, prompt_id: str, owner_id: str) -> bool:
    # 不删除文件，只标记删除状态
    index = self._load_index()

    if prompt_id in index["prompts"]:
        index["prompts"][prompt_id]["deleted"] = True
        index["prompts"][prompt_id]["deleted_at"] = datetime.now().isoformat()
        self._save_index(index)
        return True

    return False
```

#### 6.2.2 添加标签功能

扩展数据模型：

```python
# app/api/schemas_prompt.py
class PromptCreate(BaseModel):
    name: str
    prompt: str
    ownerId: str
    description: Optional[str] = None
    tags: Optional[List[str]] = []  # 新增标签字段
```

---

## 7. 性能优化

### 7.1 当前性能指标

基于性能测试结果（100次请求）：

| 操作 | P50 | P95 | P99 |
|------|-----|-----|-----|
| 列出推荐模板 | 1.02ms | 1.41ms | 1.60ms |
| 获取提示词详情 | 1.34ms | 1.89ms | 2.20ms |
| 列出个人提示词 | 1.41ms | 1.85ms | 2.22ms |
| 创建提示词 | 3.44ms | 3.82ms | 3.94ms |
| Service层调用 | 0.02ms | 0.02ms | - |

### 7.2 优化建议

#### 7.2.1 大数据量场景（>10000条）

**问题**：内存分页效率低

**解决方案**：迁移到数据库，使用 SQL LIMIT/OFFSET

```python
def list_personal(self, owner_id, page, page_size):
    offset = (page - 1) * page_size
    query = f"""
        SELECT * FROM prompts
        WHERE owner_id = %s
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
    # 执行查询...
```

#### 7.2.2 高并发场景

**问题**：文件锁可能成为瓶颈

**解决方案 1**：使用数据库连接池
**解决方案 2**：引入 Redis 缓存热点数据

```python
import redis

class PromptService:
    def __init__(self):
        self.redis = redis.Redis(host='localhost', port=6379)
        self.cache_ttl = 300  # 5分钟

    def get_prompt_detail(self, prompt_id):
        # 先查缓存
        cached = self.redis.get(f"prompt:{prompt_id}")
        if cached:
            return json.loads(cached)

        # 缓存未命中，查询存储
        result = self.storage.get(prompt_id)
        self.redis.setex(f"prompt:{prompt_id}", self.cache_ttl, json.dumps(result))
        return result
```

---

## 8. 故障排查

### 8.1 常见问题

#### 问题 1：推荐模板加载失败

**症状**：
```
WARNING: Recommended prompts file not found
```

**解决方案**：
```bash
# 检查文件是否存在
ls -la assets/prompts/recommended.json

# 检查 JSON 格式是否正确
python -m json.tool assets/prompts/recommended.json
```

#### 问题 2：版本冲突错误

**症状**：
```json
{
  "error": {
    "code": "CONFLICT",
    "message": "Version mismatch"
  }
}
```

**原因**：并发更新时版本号不匹配

**解决方案**：
1. 重新获取最新数据（包含当前 version）
2. 使用最新 version 重新提交更新

```python
# 正确的更新流程
detail = service.get_prompt_detail("personal", prompt_id, owner_id)
current_version = detail["version"]

service.update_personal_prompt(
    prompt_id=prompt_id,
    owner_id=owner_id,
    name="新名称",
    version=current_version  # 使用当前版本号
)
```

#### 问题 3：权限被拒绝

**症状**：
```json
{
  "error": {
    "code": "FORBIDDEN",
    "message": "Access denied"
  }
}
```

**原因**：尝试访问其他用户的提示词

**解决方案**：
- 检查 `X-User-Id` header 是否正确
- 确认 `ownerId` 与当前用户匹配

#### 问题 4：性能下降

**症状**：P50 延迟 > 100ms

**排查步骤**：
1. 检查数据量：`ls prompt_library/prompts/ | wc -l`
2. 查看日志中的慢查询警告
3. 检查磁盘 I/O 性能
4. 考虑迁移到数据库

### 8.2 日志分析

**启用详细日志：**
```python
# app/logger.py
import logging
logging.basicConfig(level=logging.DEBUG)
```

**查看性能日志：**
```bash
# 查找慢操作（>500ms）
grep "Slow operation" logs/app.log

# 示例输出：
# [PromptService] Slow operation: list_prompts {"latency_ms": 523.45, "success": true}
```

---

## 9. 测试指南

### 9.1 运行单元测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试文件
pytest test_prompt_api.py
pytest test_prompt_e2e.py

# 运行性能测试
python test_prompt_performance.py
```

### 9.2 API 测试脚本

参考文件：
- `test_prompt_api.py` - HTTP 接口集成测试
- `test_prompt_e2e.py` - E2E 测试（Agent + /run）
- `test_prompt_performance.py` - 性能基准测试

---

## 10. 参考资料

### 10.1 相关文档

- **需求说明书**: `feature修改说明书/openmanus_prompt_library_integration.md`
- **实施计划**: `feature修改说明书/openmanus_prompt_library_implementation_plan.md`
- **API 文档**: `API DOC.md`

### 10.2 关键代码文件

| 文件路径 | 说明 |
|---------|------|
| `app/api/routes/prompt.py` | HTTP 路由 |
| `app/api/schemas_prompt.py` | 数据模型 |
| `app/services/prompt_service.py` | 业务逻辑 |
| `app/services/prompt_storage.py` | 存储层 |
| `app/tool/prompt_library.py` | Agent 工具 |
| `assets/prompts/recommended.json` | 推荐模板数据 |

### 10.3 技术栈

- **Web框架**: FastAPI
- **数据验证**: Pydantic
- **文件锁**: fcntl (Unix) / msvcrt (Windows)
- **缓存**: functools.lru_cache
- **日志**: structlog
- **测试**: pytest, FastAPI TestClient

---

**文档结束**

如有疑问或需要帮助，请查阅相关代码或联系开发团队。
