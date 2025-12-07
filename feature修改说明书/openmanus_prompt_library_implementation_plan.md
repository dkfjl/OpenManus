# OpenManus 提示词库集成 - 执行方案

**文档版本**: v1.0
**制定日期**: 2025-12-06
**预计工期**: 5-7 工作日
**优先级**: P0

---

## 一、需求文档分析

### 1.1 合理性评估

#### ✅ 优点
1. **架构设计合理**: 采用 storage → service → api 三层架构，职责清晰，易于维护
2. **渐进式演进**: 先使用文件存储，后续可平滑迁移到数据库，降低初期复杂度和风险
3. **功能划分清晰**: 推荐模板（只读）与个人提示词（CRUD）的分离设计合理
4. **接口设计完善**: 覆盖 CRUD、分页、搜索、详情等基础功能，符合 RESTful 规范
5. **Agent 集成周到**: 考虑了工具集成和 `/run` 接口注入，实用性强
6. **安全性考虑**: 包含基础鉴权、owner 隔离、版本并发控制
7. **错误处理统一**: 标准化的错误码和响应格式
8. **可扩展性**: 变量占位功能支持未来扩展到 Jinja2 模板引擎
9. **测试覆盖完整**: 包含单元测试、集成测试、E2E 测试

#### ⚠️ 需要明确的问题

| 问题 | 风险等级 | 建议 |
|------|---------|------|
| 路由前缀不一致 (`/api/*` vs `/console/api/*`) | 🟡 中 | 统一使用 `/console/api/*`，避免与现有路由冲突 |
| 鉴权方案描述模糊 ("开发阶段可放宽") | 🟡 中 | 明确开发/生产环境的鉴权策略 |
| 文件存储并发控制实现细节缺失 | 🟠 高 | 需要详细设计文件锁机制或原子写入方案 |
| 推荐模板更新机制未说明 | 🟢 低 | 建议增加热加载或重启提示 |
| 硬删除策略缺少回滚机制 | 🟡 中 | 建议改为软删除或增加备份机制 |
| PromptLibraryTool 中 ownerId 参数设计 | 🟡 中 | Agent 调用时应自动从上下文获取，而非手动传递 |

#### 📊 整体评价
**评分**: 8.5/10
**结论**: 这是一份高质量的需求说明书，架构设计合理，考虑全面。主要改进空间在于技术细节的明确化和边界情况的处理。

---

## 二、实施路线图

### 阶段一：基础设施搭建 (Day 1-2)

#### Phase 1.1: 存储层实现 (6-8h)
**目标**: 实现文件存储与索引管理

**任务清单**:
- [ ] 创建目录结构
  ```
  assets/prompts/
    └── recommended.json          # 推荐模板数据
  app/services/
    ├── prompt_storage.py         # 存储层
    └── prompt_service.py         # 业务逻辑层
  ```
- [ ] 实现 `PromptStorage` 类
  - [x] 索引文件管理 (`index.json` 读写)
  - [x] 提示词内容文件 CRUD (`prompts/<id>.json`)
  - [x] 原子写入机制 (使用临时文件 + os.rename)
  - [x] 文件锁机制 (使用 `fcntl.flock` 或 `filelock` 库)
  - [x] 推荐模板加载与缓存
- [ ] 实现搜索与分页逻辑
  - [x] Name 模糊匹配 (大小写不敏感)
  - [x] 基于内存的分页 (后续可优化)
- [ ] 实现版本并发控制
  - [x] Version 字段自增
  - [x] 更新时版本校验，冲突返回 409

**交付物**:
- `app/services/prompt_storage.py` (约 300-400 行)
- 单元测试: `tests/test_prompt_storage.py`

**验收标准**:
```python
# 测试用例示例
def test_create_and_get():
    storage = PromptStorage()
    prompt_id = storage.create(name="测试", prompt="内容", owner_id="user1")
    result = storage.get(prompt_id)
    assert result["name"] == "测试"

def test_concurrent_update():
    # 模拟并发更新，验证版本冲突检测
    pass
```

---

#### Phase 1.2: 业务逻辑层 (4-6h)
**目标**: 封装业务规则与数据校验

**任务清单**:
- [ ] 创建 `PromptService` 类
  - [x] 调用 Storage 层
  - [x] 数据校验 (name ≤ 20, description ≤ 50)
  - [x] Owner 权限校验
  - [x] Name 唯一性检查 (同一 owner 下)
- [ ] 实现变量占位替换
  - [x] 简单 `{var}` 替换 (使用 `str.format_map`)
  - [x] 缺失变量保留原样
  - [x] 预留 Jinja2 扩展接口
- [ ] 异常封装
  - [x] 定义业务异常类 (`PromptNotFound`, `PromptConflict`, `ValidationError`)

**交付物**:
- `app/services/prompt_service.py` (约 200-300 行)
- 单元测试: `tests/test_prompt_service.py`

---

#### Phase 1.3: 数据模型与错误处理 (3-4h)
**目标**: 定义 API 契约与统一错误响应

**任务清单**:
- [ ] 创建 Pydantic Schema (`app/api/schemas_prompt.py`)
  ```python
  class PromptCreate(BaseModel):
      name: str = Field(..., max_length=20)
      description: Optional[str] = Field(None, max_length=50)
      prompt: str
      ownerId: str

  class PromptUpdate(BaseModel):
      name: Optional[str] = Field(None, max_length=20)
      description: Optional[str] = Field(None, max_length=50)
      prompt: Optional[str] = None
      version: Optional[int] = None

  class PromptResponse(BaseModel):
      id: str
      name: str
      description: Optional[str]
      prompt: str
      ownerId: str
      version: int
      createdAt: str
      updatedAt: str
  ```
- [ ] 创建错误处理器 (`app/api/error_handlers.py`)
  - [x] 统一异常拦截
  - [x] 错误码映射 (400/401/403/404/409/500)
  - [x] 响应格式 `{ error: { code, message, details? } }`
- [ ] 在 `app.py` 注册异常处理器

**交付物**:
- `app/api/schemas_prompt.py`
- `app/api/error_handlers.py`

---

### 阶段二：API 接口实现 (Day 2-3)

#### Phase 2.1: 鉴权中间件 (3-4h)
**目标**: 实现 Bearer Token 解析与 Owner 识别

**任务清单**:
- [ ] 创建 `app/api/deps/auth.py`
  ```python
  async def get_current_user(
      authorization: Optional[str] = Header(None),
      x_user_id: Optional[str] = Header(None)
  ) -> str:
      # 1. 尝试解析 Authorization: Bearer <token>
      # 2. 开发模式回退到 X-User-Id
      # 3. 返回 ownerId
      pass
  ```
- [ ] 实现 JWT 解析 (使用 `PyJWT` 或占位实现)
- [ ] 环境变量配置 (`ENABLE_AUTH`, `JWT_SECRET`)

**交付物**:
- `app/api/deps/auth.py`

**验收标准**:
```bash
# 生产模式: 必须有有效 token
curl -H "Authorization: Bearer <token>" /console/api/prompts

# 开发模式: 可使用 X-User-Id
export ENABLE_AUTH=false
curl -H "X-User-Id: user123" /console/api/prompts
```

---

#### Phase 2.2: 路由实现 (6-8h)
**目标**: 实现 5 个核心 API 端点

**任务清单**:
- [ ] 创建 `app/api/routes/prompt.py`
- [ ] 实现接口:
  1. **GET** `/console/api/prompt/overview`
     - Query: `type`, `name`, `page`, `pageSize`
     - Response: `{ data: { items, total, page, pageSize } }`
  2. **GET** `/console/api/prompt/detail`
     - Query: `type`, `id`
     - Response: `{ data: PromptResponse }`
  3. **POST** `/console/api/prompts`
     - Body: `PromptCreate`
     - Response: `201 { data: { id }, message }`
  4. **PUT** `/console/api/prompts/:id`
     - Body: `PromptUpdate`
     - Response: `200 { data: { id }, message }`
  5. **DELETE** `/console/api/prompts/:id`
     - Response: `200 { data: { id }, message }`

- [ ] 在每个端点注入 `get_current_user` 依赖
- [ ] 在 `app/app.py` 注册路由
  ```python
  from app.api.routes.prompt import router as prompt_router
  app.include_router(prompt_router)
  ```

**交付物**:
- `app/api/routes/prompt.py` (约 200-300 行)
- 修改 `app/app.py`

**验收标准**:
- Swagger UI (`/docs`) 中可见所有接口
- 所有接口返回格式符合《API DOC.md》

---

#### Phase 2.3: 集成测试 (4h)
**目标**: 端到端验证 HTTP 接口

**任务清单**:
- [ ] 使用 `pytest` + `httpx` 编写集成测试
  ```python
  @pytest.fixture
  def client():
      return TestClient(app)

  def test_create_and_list(client):
      # 创建个人提示词
      resp = client.post("/console/api/prompts", json={...})
      assert resp.status_code == 201

      # 列表查询
      resp = client.get("/console/api/prompt/overview?type=personal")
      assert len(resp.json()["data"]["items"]) > 0
  ```
- [ ] 覆盖边界情况:
  - [x] pageSize 超过 100
  - [x] 重复 name (同一 owner)
  - [x] 版本冲突更新
  - [x] 跨 owner 访问 (403)
  - [x] 推荐模板修改尝试 (403)

**交付物**:
- `tests/integration/test_prompt_api.py`

---

### 阶段三：Agent 集成 (Day 4-5)

#### Phase 3.1: PromptLibraryTool 实现 (4-6h)
**目标**: 为 Agent 提供提示词操作工具

**任务清单**:
- [ ] 创建 `app/tool/prompt_library.py`
  ```python
  class PromptLibraryTool(BaseTool):
      name = "prompt_library"
      description = "管理和检索提示词模板"

      async def _run(self, action: str, **kwargs):
          # action: get_prompt, list_personal, create_personal, etc.
          pass
  ```
- [ ] 实现 5 个子功能:
  1. `get_prompt(type, id)` - 获取详情
  2. `list_personal(name?, page?, pageSize?)` - 列表查询
  3. `create_personal(name, prompt, description?, ownerId)` - 创建
  4. `update_personal(id, name?, description?, prompt?, version?)` - 更新
  5. `delete_personal(id)` - 删除

- [ ] **重要修改**: ownerId 自动注入
  ```python
  # 从 Agent 上下文自动获取 ownerId，而非让 Agent 传递
  def get_owner_id(self) -> str:
      # 从环境变量或请求上下文提取
      return os.getenv("CURRENT_USER_ID", "default_user")
  ```

- [ ] 在 `app/agent/manus.py` 和 `app/agent/sandbox_agent.py` 注册
  ```python
  from app.tool.prompt_library import PromptLibraryTool

  available_tools = [
      # ... 现有工具
      PromptLibraryTool(),
  ]
  ```

**交付物**:
- `app/tool/prompt_library.py`
- 修改 Agent 配置文件

---

#### Phase 3.2: /run 接口扩展 (3-4h)
**目标**: 支持 promptId 注入与变量替换

**任务清单**:
- [ ] 修改 `app/api/schemas.py` (或 `schemas_prompt.py`)
  ```python
  class RunRequest(BaseModel):
      prompt: Optional[str] = None
      promptId: Optional[str] = None
      promptType: Optional[Literal["recommended", "personal"]] = "recommended"
      mergeVars: Optional[Dict[str, str]] = None
      # ... 其他现有字段
  ```

- [ ] 修改 `/run` 路由逻辑 (`app/api/routes/run.py`)
  ```python
  async def run_endpoint(request: RunRequest):
      final_prompt = request.prompt or ""

      if request.promptId:
          # 1. 查询提示词详情
          prompt_data = prompt_service.get_detail(request.promptType, request.promptId)

          # 2. 变量替换
          template_prompt = prompt_data["prompt"]
          if request.mergeVars:
              template_prompt = template_prompt.format_map(SafeDict(request.mergeVars))

          # 3. 合并 (默认模板前置)
          final_prompt = f"{template_prompt}\n\n{final_prompt}"

      # 传递给 run_manus_flow
      await run_manus_flow(final_prompt, ...)
  ```

**交付物**:
- 修改 `app/api/routes/run.py`
- 修改 `app/api/schemas.py`

**验收标准**:
```bash
# 测试用例
curl -X POST /api/run -d '{
  "promptId": "f6f2e4e2-...",
  "promptType": "recommended",
  "mergeVars": {"role": "产品经理", "goal": "撰写需求文档"},
  "prompt": "请关注用户体验"
}'
# 预期: 最终传递给 Agent 的 prompt 已完成变量替换和合并
```

---

#### Phase 3.3: E2E 测试 (3-4h)
**目标**: 验证完整链路

**任务清单**:
- [ ] Agent 工具调用测试
  ```python
  async def test_agent_prompt_library():
      agent = Manus(...)
      result = await agent.run("帮我查找名为'通用结构'的推荐模板")
      assert "通用结构" in result
  ```

- [ ] /run 注入测试
  ```python
  def test_run_with_prompt_id(client):
      resp = client.post("/api/run", json={
          "promptId": "...",
          "mergeVars": {"topic": "AI"}
      })
      # 验证执行日志中包含替换后的 prompt
  ```

**交付物**:
- `tests/e2e/test_agent_prompt_integration.py`

---

### 阶段四：监控、日志与优化 (Day 5-6)

#### Phase 4.1: 日志审计 (3-4h)
**目标**: 记录关键操作与性能指标

**任务清单**:
- [ ] 在 `app/services/execution_log_service.py` 扩展
  ```python
  def log_prompt_operation(
      actor: str,
      operation: str,  # create, update, delete, get, list
      prompt_id: Optional[str],
      status: str,      # success, failure
      latency_ms: float,
      error: Optional[str] = None
  ):
      # 写入日志或数据库
      pass
  ```

- [ ] 在 Service 层关键方法注入日志
  ```python
  @log_execution_time
  async def create_prompt(self, data):
      start = time.time()
      try:
          result = self.storage.create(...)
          log_prompt_operation(actor=data.owner_id, operation="create",
                                prompt_id=result["id"], status="success",
                                latency_ms=(time.time()-start)*1000)
          return result
      except Exception as e:
          log_prompt_operation(..., status="failure", error=str(e))
          raise
  ```

**交付物**:
- 修改 `app/services/prompt_service.py`
- 扩展 `execution_log_service.py`

---

#### Phase 4.2: 性能测试与优化 (4-5h)
**目标**: 确保 P50 ≤ 150ms

**任务清单**:
- [ ] 使用 `locust` 或 `wrk` 进行压测
  ```python
  # locustfile.py
  class PromptUser(HttpUser):
      @task
      def list_prompts(self):
          self.client.get("/console/api/prompt/overview?type=recommended")
  ```

- [ ] 性能瓶颈分析
  - [x] 推荐模板缓存 (启动时加载到内存)
  - [x] 索引文件缓存 (使用 LRU Cache)
  - [x] 减少文件 I/O (批量读取)

- [ ] 优化措施
  ```python
  from functools import lru_cache

  @lru_cache(maxsize=1)
  def load_recommended_prompts():
      # 只加载一次
      pass
  ```

**交付物**:
- 性能测试报告 (Markdown)
- 优化代码提交

**验收标准**:
- 100 条数据下 P50 < 150ms
- P95 < 300ms
- 无明显内存泄漏

---

#### Phase 4.3: 推荐模板数据准备 (2-3h)
**目标**: 创建高质量的初始模板

**任务清单**:
- [ ] 编写 `assets/prompts/recommended.json`
  - [x] 至少 10 个通用模板
  - [x] 覆盖常见场景 (代码生成、文案撰写、数据分析等)
  - [x] 每个模板包含清晰的变量占位符

- [ ] 模板示例:
  ```json
  [
    {
      "id": "uuid-1",
      "name": "需求分析模板",
      "description": "产品需求文档撰写",
      "prompt": "# 角色\n你是资深产品经理\n\n# 任务\n针对{feature}功能,撰写需求文档\n\n# 输出\n1. 功能描述\n2. 用户故事\n3. 验收标准"
    }
  ]
  ```

**交付物**:
- `assets/prompts/recommended.json`

---

### 阶段五：文档与交付 (Day 6-7)

#### Phase 5.1: 文档完善 (3-4h)
**任务清单**:
- [ ] 更新 API 文档
  - [x] 在 Swagger 中添加示例
  - [x] 补充错误码说明
- [ ] 编写开发者指南
  - [x] 如何添加推荐模板
  - [x] 如何在 Agent 中使用工具
  - [x] 如何扩展到数据库
- [ ] 更新 README
  - [x] 新功能说明
  - [x] 配置项说明

**交付物**:
- `docs/prompt_library_guide.md`
- 更新 `README.md`

---

#### Phase 5.2: Code Review & 合并 (2-3h)
**任务清单**:
- [ ] 代码自查清单
  - [x] 所有测试通过
  - [x] 代码覆盖率 > 80%
  - [x] 无 lint 错误
  - [x] 无敏感信息泄露
- [ ] 提交 PR
  - [x] 详细的 PR 描述
  - [x] 附上测试截图/日志
  - [x] 标注 Breaking Changes (如有)

---

## 三、风险缓解策略

| 风险项 | 可能性 | 影响 | 缓解措施 |
|--------|--------|------|----------|
| 文件存储并发冲突 | 🟡 中 | 🟠 高 | 1. 使用文件锁 (`fcntl`/`filelock`)<br>2. 实现重试机制<br>3. 添加完善的并发测试 |
| 鉴权系统集成困难 | 🟢 低 | 🟡 中 | 1. 先实现占位方案 (`X-User-Id`)<br>2. 预留 JWT 解析接口<br>3. 与安全团队提前对齐 |
| 性能不达标 | 🟢 低 | 🟡 中 | 1. 提前引入缓存机制<br>2. 分阶段压测<br>3. 准备降级方案 (限流) |
| 推荐模板更新流程不明 | 🟢 低 | 🟢 低 | 1. 文档中明确更新需重启<br>2. 后续可增加热加载 |
| 硬删除误操作 | 🟡 中 | 🟠 高 | 1. 在 UI 增加二次确认<br>2. 后续改为软删除<br>3. 定期备份 `prompt_library` 目录 |

---

## 四、检查清单

### 开发前置条件
- [ ] 确认 Python 版本 ≥ 3.8
- [ ] 安装依赖: `fastapi`, `pydantic`, `filelock`, `PyJWT`
- [ ] 确认现有 `/api/run` 接口行为
- [ ] 准备开发环境配置文件

### 开发中检查点
- [ ] Day 1 结束: Storage 层单元测试全部通过
- [ ] Day 2 结束: API 接口在 Swagger 中可调用
- [ ] Day 3 结束: 集成测试覆盖率 > 80%
- [ ] Day 4 结束: Agent 可成功调用工具
- [ ] Day 5 结束: 性能测试达标
- [ ] Day 6 结束: 文档审核通过

### 最终验收标准
- [ ] 所有单元测试通过 (覆盖率 > 80%)
- [ ] 所有集成测试通过
- [ ] E2E 测试通过 (Agent 调用 + /run 注入)
- [ ] 性能测试达标 (P50 < 150ms, P95 < 300ms)
- [ ] API 文档与实现一致
- [ ] 代码 Review 通过
- [ ] 无现有功能回归问题

---

## 五、技术细节补充

### 5.1 文件存储并发控制方案

**问题**: 多进程同时读写 `index.json` 可能导致数据丢失

**解决方案**: 使用文件锁 + 原子写入

```python
import fcntl
import json
import tempfile
import os

class PromptStorage:
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.index_file = self.base_path / "index.json"
        self.lock_file = self.base_path / ".index.lock"

    def _atomic_write(self, data: dict):
        """原子写入"""
        with open(self.lock_file, 'w') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)  # 排他锁

            # 写入临时文件
            temp_file = self.index_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # 原子替换
            os.rename(temp_file, self.index_file)

            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
```

---

### 5.2 鉴权实现方案

**开发模式** (ENABLE_AUTH=false):
```python
async def get_current_user(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
) -> str:
    if not config.ENABLE_AUTH:
        return x_user_id or "default_user"

    if not authorization:
        raise HTTPException(401, detail="Missing authorization header")

    # 解析 Bearer Token
    token = authorization.replace("Bearer ", "")
    payload = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    return payload.get("sub")  # 返回 userId
```

**生产模式**:
- 集成现有 JWT 验证逻辑
- 从 Token 中提取 `sub` 作为 `ownerId`

---

### 5.3 变量占位实现

**阶段一**: 简单替换
```python
from string import Formatter

class SafeDict(dict):
    def __missing__(self, key):
        return f"{{{key}}}"  # 缺失变量保留原样

def replace_vars(template: str, vars: dict) -> str:
    return template.format_map(SafeDict(vars))

# 示例
template = "你是{role},目标是{goal},约束:{constraints}"
result = replace_vars(template, {"role": "助手", "goal": "回答问题"})
# 输出: "你是助手,目标是回答问题,约束:{constraints}"
```

**阶段二** (可选): Jinja2 升级
```python
from jinja2 import Template

def replace_vars_jinja(template: str, vars: dict) -> str:
    t = Template(template)
    return t.render(**vars)

# 支持条件/循环
template = """
{% if role %}你是{{ role }}{% endif %}
{% for item in tasks %}
- {{ item }}
{% endfor %}
"""
```

---

## 六、工作量估算

| 阶段 | 任务 | 预计工时 | 依赖 |
|------|------|----------|------|
| 阶段一 | 存储层实现 | 6-8h | - |
| 阶段一 | 业务逻辑层 | 4-6h | 存储层 |
| 阶段一 | 数据模型与错误处理 | 3-4h | - |
| 阶段二 | 鉴权中间件 | 3-4h | - |
| 阶段二 | 路由实现 | 6-8h | 存储层、业务层 |
| 阶段二 | 集成测试 | 4h | 路由实现 |
| 阶段三 | PromptLibraryTool | 4-6h | 业务层 |
| 阶段三 | /run 接口扩展 | 3-4h | 业务层 |
| 阶段三 | E2E 测试 | 3-4h | 工具实现 |
| 阶段四 | 日志审计 | 3-4h | - |
| 阶段四 | 性能测试与优化 | 4-5h | 路由实现 |
| 阶段四 | 推荐模板数据 | 2-3h | - |
| 阶段五 | 文档完善 | 3-4h | - |
| 阶段五 | Code Review | 2-3h | 所有阶段 |
| **总计** | - | **47-63h** | - |

**折合工作日**: 6-8 天 (按每天 8 小时计算)

---

## 七、后续演进规划

### 7.1 短期优化 (1-2 周内)
- [ ] 软删除 + 回收站功能
- [ ] 推荐模板热加载
- [ ] 提示词导入/导出 (JSON/CSV)
- [ ] 更丰富的搜索 (标签、分类)

### 7.2 中期演进 (1-2 月内)
- [ ] 迁移到 SQLite/PostgreSQL
- [ ] 提示词版本历史
- [ ] 协作功能 (分享、收藏)
- [ ] 使用统计与分析

### 7.3 长期规划 (季度级)
- [ ] 提示词市场 (公开分享)
- [ ] AI 辅助提示词优化
- [ ] 多租户隔离
- [ ] 审计日志与合规

---

## 八、参考资料

- [原需求文档] `feature修改说明书/openmanus_prompt_library_integration.md`
- [API 文档] `API DOC.md`
- [现有代码]
  - `app/app.py` - 路由注册
  - `app/api/routes/run.py` - /run 接口
  - `app/services/execution_log_service.py` - 日志服务
  - `app/agent/manus.py` - Agent 实现

---

## 九、FAQ

**Q1: 为什么先用文件存储而不是直接上数据库?**
A: 降低初期复杂度,快速验证功能可行性。文件存储足够支撑前期规模,且后续迁移成本可控。

**Q2: 硬删除是否有数据安全风险?**
A: 确实存在风险。建议:
1. UI 层增加二次确认
2. 定期备份 `prompt_library` 目录
3. 后续迭代改为软删除

**Q3: 如何保证推荐模板的质量?**
A:
1. 建立模板审核流程
2. 收集用户反馈
3. 定期更新优化

**Q4: 性能目标 150ms 是否合理?**
A: 对于文件存储 + 内存缓存场景,这是合理目标。如果数据量超过 10000 条,需考虑数据库优化。

**Q5: 如何处理跨环境的 ownerId 一致性?**
A: 使用统一的用户标识系统 (如 UUID),避免使用环境相关 ID。

---

**文档结束**
如有疑问或需要调整,请及时反馈。
