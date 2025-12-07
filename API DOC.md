## 一、prompt提示词库 API 文档

基础信息
- Base URL: https://api.example.com
- 格式：JSON（UTF-8）
- 认证：在 Header 中携带 `Authorization: Bearer <token>`（示例均已包含）。

响应规范
- 统一结构：`{ data: any, message?: string }`
- 成功与失败以 HTTP 状态码为准：
  - 200 成功，返回 `data`（可选 `message`）。
  - 201 创建成功；204 删除成功无内容。
  - 400/401/403/404/409/500 等错误，返回 `{ error: { code?: string, message: string, details?: any } }`。

错误码规范
- 400 `VALIDATION_ERROR`：参数校验失败（如必填缺失、长度超限、格式错误）。message 提示具体原因。
- 401 `UNAUTHORIZED`：认证失败或令牌过期。检查 `Authorization: Bearer <token>`。
- 403 `FORBIDDEN`：无权限访问或主体不匹配。
- 404 `NOT_FOUND`：资源不存在或已删除（如分类键或提示词 ID 无效）。
- 409 `CONFLICT`：资源冲突（如名称唯一性冲突、版本冲突）。
- 429 `TOO_MANY_REQUESTS`：请求频率过高，建议退避重试。
- 500 `INTERNAL_SERVER_ERROR`：服务端异常。可在 `details` 附带错误上下文。
- 503 `SERVICE_UNAVAILABLE`：依赖服务不可用或暂时失败，建议稍后重试。





1) 获取分类、默认模板及个人提示词
- GET /console/api/prompt/overview
- 描述：同时返回分类与其默认模板文本，以及当前用户的个人提示词列表。
- Query：
  - `type`: `recommended` | `personal`（必选，用于分类部分）
  - `name`: string（可选，按名称对个人提示词进行模糊搜索）
  - `page`: number（可选，默认 `1`）
  - `pageSize`: number（可选，默认 `20`，最大 `100`）
- 成功返回（根据 `type` 条件返回）：
 - `type=recommended`：`data: { items: Array<{ id: string, name: string, description: string, prompt: string }>, total: number, page: number, pageSize: number }`
 - `type=personal`：`data: { items: Prompt[], total: number, page: number, pageSize: number }`
  - 说明：
    - 统一返回为单一 `items` 列表；`type=recommended` 时 `items` 为分类与默认模板；`type=personal` 时 `items` 为当前用户个人提示词。

示例 cURL：
```
curl -X GET "https://api.example.com/console/api/prompt/overview?type=recommended&page=1&pageSize=20" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer <token>"

curl -X GET "https://api.example.com/console/api/prompt/overview?type=personal&page=1&pageSize=20&name=复盘" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer <token>"
```

示例响应：
```
{
  "data": {
    "items": [
      {
        "id": "6634e532-8ea0-4d8a-9d6f-8a4f6ef7d9a2",
        "name": "季度复盘模板",
        "description": "覆盖目标/过程/结论",
        "prompt": "# 目标\n...",
        "ownerId": "3d0e3f9e-6383-4b2f-8c6d-8fd2f3c1aaf9"
      }
    ],
    "total": 1,
    "page": 1,
    "pageSize": 20
  }
}
```


失败示例：
```
{
  "error": { "code": "UNAUTHORIZED", "message": "认证失败或令牌已过期" }
}
```

- 通过 `type` 参数区分数据范围：`recommended` 返回分类与默认模板（items 列表）；`personal` 返回个人提示词（items 列表，仅一类数据）。




2) 创建个人提示词
- POST /console/api/prompts
- 描述：创建新的个人提示词（页面“新增提示词”）。
- Body（JSON）：
  - `name`: string（必填，≤20 字）
  - `description`: string（可选，≤50 字）
  - `prompt`: string（必填）
  - `ownerId`: string（必填）
    - 语义：应与当前认证用户标识一致；服务端需校验与令牌主体一致，否则返回 `403 FORBIDDEN`。
- 成功返回：`data: { id: string }`

示例 cURL：
```
curl -X POST "https://api.example.com/console/api/prompts" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "name": "季度复盘模板",
    "description": "覆盖目标/过程/结论",
    "prompt": "# 目标\n...",
    "ownerId": "3d0e3f9e-6383-4b2f-8c6d-8fd2f3c1aaf9"
  }'
```

示例响应：
```
{
  "data": { "id": "6634e532-8ea0-4d8a-9d6f-8a4f6ef7d9a2" },
  "message": "创建成功"
}

失败示例：
```
{
  "error": { "code": "VALIDATION_ERROR", "message": "name 长度超过 20 字" }
}
```

3) 更新个人提示词
- PUT /console/api/prompts/:id
- 描述：更新提示词名称/简介/正文等。
- Path：`id` 提示词 ID。
- Body（JSON）：与 `POST` 同字段，均可选（至少一项）。
- 成功返回：`data: { id: string }`

示例 cURL：
```
curl -X PUT "https://api.example.com/console/api/prompts/6634e532-8ea0-4d8a-9d6f-8a4f6ef7d9a2" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "name": "季度复盘模板（修订版）",
    "description": "覆盖目标/过程/结论",
    "prompt": "# 目标\n...更新内容"
  }'
```

示例响应：
```
{
  "data": { "id": "6634e532-8ea0-4d8a-9d6f-8a4f6ef7d9a2" },
  "message": "更新成功"
}

失败示例：
```
{
  "error": { "code": "NOT_FOUND", "message": "提示词不存在" }
}
```

4) 删除个人提示词
- DELETE /console/api/prompts/:id
- 描述：删除指定个人提示词。
- Path：`id` 提示词 ID。
- 成功返回：`data: { id: string }`

示例 cURL：
```
curl -X DELETE "https://api.example.com/console/api/prompts/6634e532-8ea0-4d8a-9d6f-8a4f6ef7d9a2" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer <token>"
```

示例响应：
```
{
  "data": { "id": "6634e532-8ea0-4d8a-9d6f-8a4f6ef7d9a2" },
  "message": "删除成功"
}

失败示例：
```
{
  "error": { "code": "NOT_FOUND", "message": "提示词不存在" }
}
```
5) 获取模板/提示词详情
- GET /console/api/prompt/detail
- 描述：按 `type` 与 `id` 返回对应详情。
- Query：
  - `type`: `recommended` | `personal`（必选）
  - `id`: string（必选，UUID）
- 成功返回（根据 `type`）：
  - `type=recommended`：`data: { id: string, name: string, description: string, prompt: string }`
  - `type=personal`：`data: Prompt`

示例 cURL：
```
curl -X GET "https://api.example.com/console/api/prompt/detail?type=recommended&id=f6f2e4e2-0d22-4a1f-9c11-8a3c9a12e7f2" \
  -H "Accept: application/json"

curl -X GET "https://api.example.com/console/api/prompt/detail?type=personal&id=6634e532-8ea0-4d8a-9d6f-8a4f6ef7d9a2" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer <token>"
```

示例响应（type=recommended）：
```
{
  "data": {
    "id": "f6f2e4e2-0d22-4a1f-9c11-8a3c9a12e7f2",
    "name": "通用结构",
    "description": "适用于多种场景的提示词结构，可模板化复用。",
    "prompt": "# 角色\n你是{InputSlot ...}"
  }
}
```

示例响应（type=personal）：
```
{
  "data": {
    "id": "6634e532-8ea0-4d8a-9d6f-8a4f6ef7d9a2",
    "name": "季度复盘模板",
    "description": "覆盖目标/过程/结论",
    "prompt": "# 目标\n...",
    "ownerId": "3d0e3f9e-6383-4b2f-8c6d-8fd2f3c1aaf9"
  }
}
```

失败示例：
```
{
  "error": { "code": "NOT_FOUND", "message": "指定的资源不存在或不可用" }
}
```