# OpenManus 提示词库集成需求说明书（v1.0）

- 文档状态：草案
- 最近更新：2025-12-06
- 负责人：待定
- 相关代码仓库：OpenManus（本仓库）

## 1. 背景与目标
OpenManus 当前提示词以静态常量形式定义在 `app/prompt/*.py`。随着使用场景扩展，需要：
- 支持“推荐模板”（只读）与“个人提示词”（可 CRUD）；
- 提供统一的 HTTP 接口与前端对接；
- 允许 Manus/SandboxManus 在运行期直接读取、搜索与写入提示词；
- 保持与现有服务架构风格一致，降低引入成本，可平滑演进到数据库。

本次集成引入“提示词库”子系统，采用 storage → service → api 三层，优先落地文件存储（JSON 索引 + 内容文件）。

## 2. 范围
- 在后端实现提示词库：内置推荐模板、个人提示词 CRUD、分页检索、详情查询、变量占位解析；
- 暴露与前端一致的接口（参考《API DOC.md》）；
- 为 Agent 提供可调用工具（PromptLibraryTool）与 `/run` 的 promptId 注入能力；
- 认证/授权最小实现（Bearer 解析占位、owner 校验）；
- 日志与基础错误封装；
- 不包含复杂权限体系、审计报表、跨租户隔离、DB 迁移（列为后续）。

## 3. 名词与对象
- 推荐模板（recommended）：系统预置的只读提示词集合。
- 个人提示词（personal）：用户自建/维护的提示词条目，按 `ownerId` 隔离。
- Prompt 对象：`{ id, name, description?, prompt, ownerId, version, createdAt, updatedAt }`。

## 4. 业务流程概述
1) 前端列表页调用 `GET /console/api/prompt/overview` 获取推荐或个人提示词分页结果；
2) 个人提示词新增/编辑/删除分别调用 `POST/PUT/DELETE /console/api/prompts`；
3) 详情页调用 `GET /console/api/prompt/detail` 获取 `recommended|personal` 指定 `id` 的详细信息；
4) Agent 运行：
   - 方式：在 ReAct 过程中通过工具 `prompt_library` 调用存取提示词；

## 5. 功能需求
- 分类：支持 `recommended` 与 `personal` 两类；
- 创建个人提示词：校验 `name(≤20)`、`description(≤50)`、`prompt(必填)`、`ownerId(必填)`；
- 更新个人提示词：任意字段可选（至少一项），支持 `version` 并发控制（返回 409）；
- 删除个人提示词：软/硬删除本期采用硬删除；
- 分页与搜索：`page` 默认 1，`pageSize` 默认 20、最大 100；`name` 模糊搜索；
- 详情：按 `type + id` 返回对应结构；
- 变量占位：支持 `{var}` 简单替换，替换源来自 `mergeVars`；
- 推荐模板来源：`assets/prompts/recommended.json`（只读）；
- 返回结构：统一 `{ data, message? }` 或 `{ error: { code, message, details? } }`。

## 6. 非功能需求
- 性能：单次列表请求 ≤ 100 条，服务端响应 P50 ≤ 150ms（本地文件存储场景）；
- 可用性：接口幂等（DELETE 除外），错误可观测；
- 兼容性：不破坏现有 `/run` 与 `/api/*` 路由；
- 安全：最小可用鉴权与 owner 校验；
- 可扩展：后续平滑切换 DB（SQLite/Postgres）。

## 7. 接口设计（与前端对接）
- Base URL：沿用现有服务，如 `http://localhost:10000`
- 路由前缀：遵循前端文档 `/api/*`
- 鉴权：Header `Authorization: Bearer <token>`（开发阶段可放宽或使用占位解析）

### 7.1 获取分类、默认模板及个人提示词
- GET `/console/api/prompt/overview?type=recommended|personal&name=&page=&pageSize=`
- 成功返回：
```
{ "data": { "items": [...], "total": 1, "page": 1, "pageSize": 20 } }
```
- 失败返回：
```
{ "error": { "code": "UNAUTHORIZED", "message": "认证失败或令牌已过期" } }
```

### 7.2 创建个人提示词
- POST `/console/api/prompts`
- Body：`{ name, description?, prompt, ownerId }`
- 成功：201，`{ "data": { "id": "..." }, "message": "创建成功" }`
- 失败：400/401/403/409

### 7.3 更新个人提示词
- PUT `/console/api/prompts/:id`
- Body：同 POST 字段均可选，支持 `version`
- 成功：200，`{ "data": { "id": "..." }, "message": "更新成功" }`

### 7.4 删除个人提示词
- DELETE `/console/api/prompts/:id`
- 成功：200，`{ "data": { "id": "..." }, "message": "删除成功" }`

### 7.5 获取模板/提示词详情
- GET `/console/api/prompt/detail?type=recommended|personal&id=...`
- 成功：返回与《API DOC.md》一致的 `data` 结构

### 7.6 错误码与校验
- 400 VALIDATION_ERROR、401 UNAUTHORIZED、403 FORBIDDEN、404 NOT_FOUND、409 CONFLICT、429、500、503（与文档一致）。

## 8. 后端实现方案
### 8.1 目录与组件
- 新增文件与目录：
  - `assets/prompts/recommended.json`（内置推荐模板）
  - `app/services/prompt_storage.py`（文件存储与索引）
  - `app/services/prompt_service.py`（业务逻辑与权限校验）
  - `app/api/schemas_prompt.py`（Pydantic 模型）
  - `app/api/routes/prompt.py`（HTTP 路由）
  - `app/api/deps/auth.py`（鉴权依赖：解析 Bearer，导出 `ownerId`）
  - `app/api/error_handlers.py`（统一错误封装）
  - `app/tool/prompt_library.py`（Agent 工具）
- 修改：
  - `app/app.py` 注册新路由 `prompt_router`
  - `app/agent/manus.py`、`app/agent/sandbox_agent.py` 的 `available_tools` 增加 `PromptLibraryTool()`
  - `app/api/schemas.py`（如需 `/run` 请求体扩展，可新增可选字段而不破坏现有）

### 8.2 存储设计（文件）
- 根目录：`config.workspace_root / "prompt_library"`
- 索引：`index.json`
```
{
  "prompts": {
    "<id>": { "id": "...", "name": "...", "description": "...", "ownerId": "...",
               "file": "prompts/<id>.json", "version": 3, "createdAt": "iso", "updatedAt": "iso" }
  },
  "owners": { "<ownerId>": ["<id>", ...] }
}
```
- 内容文件：`prompts/<id>.json`，结构 `{ "prompt": "..." }`
- 推荐模板：`assets/prompts/recommended.json` 数组形式，结构 `{ id, name, description?, prompt }`

### 8.3 数据模型（Pydantic 摘要）
- `Prompt`：`id:str(UUID)`, `name:str(<=20)`, `description?:str(<=50)`, `prompt:str`, `ownerId:str`, `version:int`, `createdAt:str(iso)`, `updatedAt:str(iso)`
- `RecommendedPrompt`：`id,name,description?,prompt`
- `OverviewResponse`：`{ items:list, total:int, page:int, pageSize:int }`

### 8.4 服务与校验
- 创建/更新时做长度校验、必填校验、同 owner 下 `name` 唯一；
- PUT 支持 `version` 并发控制（不带则跳过；带上后不一致返回 409）；
- 个人数据按 `ownerId` 隔离；推荐模板只读。

### 8.5 鉴权与主体
- `get_current_user()` 从 `Authorization` 解析 `sub` 作为 `ownerId`；开发模式允许回退 `X-User-Id`；
- POST/PUT/DELETE 校验 body.ownerId 与主体一致，否则 403；
- `recommended` 类型接口允许匿名只读（按需配置）。

### 8.6 错误封装
- 将内部异常映射为 `{ error: { code, message, details? } }`；
- 在 `app/app.py` 注册异常处理器。

## 9. Agent 集成方案
### 9.1 工具（PromptLibraryTool）
- 工具名：`prompt_library`
- 能力：
  - `get_prompt(type, id)`
  - `list_personal(name?, page?, pageSize?)`
  - `create_personal(name, description?, prompt, ownerId)`
  - `update_personal(id, name?, description?, prompt?, version?)`
  - `delete_personal(id)`
- 返回：字符串或结构化 JSON，遵循工具调用的约定。
- 集成：在 `Manus` 与 `SandboxManus` 的 `available_tools` 中加入。

### 9.2 /run 注入（可选增强，向后兼容）
- 扩展请求体（可选字段）：
```
{
  "prompt": "...",                       // 原字段，保留
  "promptId": "uuid?",                   // 可选
  "promptType": "recommended|personal?", // 可选
  "mergeVars": { "topic": "季度 OKR" }   // 可选
}
```
- 逻辑：若提供 `promptId` → 查询详情 → 执行 `{var}` 替换 → 与 `prompt` 合并（约定前置/后置，默认前置）→ 传给 `run_manus_flow`。

### 9.3 变量占位
- 语法：`{var}`；以 `str.format_map(SafeDict)` 实现，缺失变量保留原样或替换为空（默认原样）。
- 后续可升级 Jinja2 以支持条件与循环。

## 10. 监控与日志
- 在 `app/services/execution_log_service.py` 记录变化事件：create/update/delete/detail/overview；
- 关键字段：`actor(ownerId)`, `promptId`, `op`, `status`, `latency`；
- 错误打点与栈追踪（限制内容大小）。

## 11. 测试与验收
### 11.1 单元测试
- storage：索引创建、CRUD、分页、并发版本冲突、异常路径；
- service：校验、owner 隔离、搜索；
- api：schema 校验、状态码、错误封装。

### 11.2 集成测试
- 通过 HTTP 调用覆盖《API DOC.md》所有示例；
- `pageSize` 边界（100、101）；`name` 搜索大小写/中文；
- 推荐/个人详情跨类型校验。

### 11.3 Agent E2E
- 工具检索 + 执行：`get_prompt` → 拼装 → `POST /run` → 成功返回；
- `/run` 注入：`promptId + mergeVars` 全链路。

### 11.4 验收标准
- 所有接口返回结构与文档一致；
- 基准数据 100 条以内 P50 ≤ 150ms；
- 关键用例均通过；
- 无破坏现有路由与行为。

## 12. 里程碑与计划
- M1（2–3 天）：存储/服务/路由/错误封装/鉴权占位，联调 overview/detail/CRUD；
- M2（1–2 天）：`PromptLibraryTool` 与 `/run` 注入；
- M3（1–2 天）：日志审计、导入导出、版本并发完善、边界与压测。

## 13. 风险与缓解
- 鉴权对接不确定：先用占位解析与 `X-User-Id` 回退，后续替换为统一认证；
- 文件存储一致性：引入文件写锁/原子写，添加 `version` 控制；
- 模板变量复杂度：先提供 `{var}`，评估后升级 Jinja2；
- 路由前缀冲突：新路由置于 `/console/api/*`，与现有 `/api/*` 并行。

## 14. 交付物
- 代码：`assets/prompts/recommended.json`、`app/services/prompt_*.py`、`app/api/schemas_prompt.py`、`app/api/routes/prompt.py`、`app/api/deps/auth.py`、`app/api/error_handlers.py`、`app/tool/prompt_library.py`、`app/app.py` 路由注册修改；
- 文档：本说明书；
- 测试：单元与集成测试用例。

---

> 附：`recommended.json` 示例
```
[
  {
    "id": "f6f2e4e2-0d22-4a1f-9c11-8a3c9a12e7f2",
    "name": "通用结构",
    "description": "适用于多种场景的提示词结构",
    "prompt": "# 角色\n你是{role}\n# 目标\n{goal}\n# 约束\n{constraints}"
  }
]
```

> 附：PromptLibraryTool 功能签名（草案）
```
- get_prompt(type: "recommended"|"personal", id: str) -> { id, name, description?, prompt }
- list_personal(name?: str, page?: int, pageSize?: int) -> { items, total, page, pageSize }
- create_personal(name: str, prompt: str, description?: str, ownerId: str) -> { id }
- update_personal(id: str, name?: str, description?: str, prompt?: str, version?: int) -> { id }
- delete_personal(id: str) -> { id }
```
