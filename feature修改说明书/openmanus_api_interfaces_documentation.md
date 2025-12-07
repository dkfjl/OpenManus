# API接口文档

## 目录
1. [文件上传接口 `/api/files/upload`](#文件上传接口)
2. [PPT大纲生成接口 `/api/ppt-outline/generate`](#ppt大纲生成接口)
3. [增强版PPT大纲接口](#增强版ppt大纲接口)
4. [DOCX文档生成接口 `/api/docx/generate`](#docx文档生成接口)
5. [辅助接口](#辅助接口)
6. [错误处理](#错误处理)
7. [使用示例](#使用示例)

---

## 文件上传接口

### 接口信息
- **端点**: `POST /api/files/upload`
- **功能**: 上传文件并生成UUID，支持最多5个文件同时上传
- **内容类型**: `multipart/form-data`

### 请求参数

| 参数名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| `upload_files` | `File[]` | 是 | 上传的文件列表，支持pdf、docx、txt、jpg、jpeg、png、html、htm格式 |

### 支持的文件格式

| 文件类型 | 扩展名 | 最大大小 | 处理说明 |
|----------|--------|----------|----------|
| PDF文档 | `.pdf` | 10MB | 文本提取 |
| Word文档 | `.docx` | 10MB | 段落和表格提取 |
| 文本文件 | `.txt` | 10MB | 直接读取 |
| JPEG图片 | `.jpg/.jpeg` | 10MB | OCR文字识别 |
| PNG图片 | `.png` | 10MB | OCR文字识别 |
| HTML文档 | `.html/.htm` | 10MB | 正文提取 |

### 成功响应 (200 OK)

```json
{
  "status": "success",
  "uuids": ["550e8400-e29b-41d4-a716-446655440000", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"],
  "files": [
    {
      "uuid": "550e8400-e29b-41d4-a716-446655440000",
      "original_name": "市场分析报告.pdf",
      "saved_name": "550e8400-e29b-41d4-a716-446655440000_市场分析报告.pdf",
      "size": 2048576,
      "type": "application/pdf"
    },
    {
      "uuid": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      "original_name": "数据统计.xlsx",
      "saved_name": "6ba7b810-9dad-11d1-80b4-00c04fd430c8_数据统计.xlsx",
      "size": 1024000,
      "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    }
  ],
  "message": "成功上传2个文件"
}
```

### 错误响应

#### 400 Bad Request
```json
{
  "status": "error",
  "uuids": [],
  "files": [],
  "message": "上传文件数量超过限制，最多支持5个文件"
}
```

#### 400 Bad Request - 文件格式不支持
```json
{
  "status": "error",
  "uuids": [],
  "files": [],
  "message": "不支持的文件格式: .exe。支持的格式: .pdf, .docx, .txt, .jpg, .jpeg, .png, .html, .htm"
}
```

#### 400 Bad Request - 文件过大
```json
{
  "status": "error",
  "uuids": [],
  "files": [],
  "message": "文件过大: 15.2MB。最大允许: 10.0MB"
}
```

### 使用示例

#### 上传单个文件
```bash
curl -X POST "http://localhost:10000/api/files/upload" \
  -F "upload_files=@/path/to/document.pdf"
```

#### 上传多个文件
```bash
curl -X POST "http://localhost:10000/api/files/upload" \
  -F "upload_files=@/path/to/report.pdf" \
  -F "upload_files=@/path/to/data.xlsx" \
  -F "upload_files=@/path/to/chart.png"
```

#### 格式化查看响应
```bash
curl -X POST "http://localhost:10000/api/files/upload" \
  -F "upload_files=@document.pdf" | python -m json.tool
```

---

## PPT大纲生成接口

### 接口信息
- **端点**: `POST /api/ppt-outline/generate`
- **功能**: 根据主题和参考文件生成PPT制作过程大纲，同时异步生成增强版专业PPT内容大纲
- **内容类型**: `multipart/form-data`

### 请求参数

| 参数名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| `topic` | `string` | 是 | PPT主题，最大长度500字符 |
| `language` | `string` | 否 | 输出语言，默认为"zh"（中文），支持"en"（英文） |
| `file_uuids` | `string` | 否 | 已上传文件的UUID列表，用逗号分隔，最多5个UUID |

### 成功响应 (200 OK)

```json
{
  "status": "success",
  "outline": [
    {
      "key": "0",
      "title": "需求分析与任务拆解",
      "description": "我来为你制作一份专业的人工智能发展趋势PPT。让我先分析你的需求",
      "detailType": "markdown",
      "meta": {
        "summary": "自动从输入中提炼目标与约束，形成可执行列表",
        "substeps": [
          {
            "key": "0-1",
            "text": "分析用户意图与上下文",
            "showDetail": false
          },
          {
            "key": "0-2",
            "text": "拆解任务及依赖关系",
            "showDetail": false
          },
          {
            "key": "0-3",
            "text": "待办清单",
            "showDetail": true,
            "detailType": "markdown",
            "detailPayload": {
              "type": "markdown",
              "data": "### 待办清单\n- [ ] 拟定标题与副标题\n- [ ] 生成PPT目录\n- [ ] 生成各章大纲\n- [ ] 构建PPT主体\n- [ ] 优化版式与内容"
            }
          }
        ]
      }
    },
    {
      "key": "1",
      "title": "拟定题目与标题页",
      "description": "规划标题页，确定主标题、副标题与基调",
      "detailType": "markdown",
      "meta": {
        "summary": "统一主题与视觉风格，设置标题页核心元素",
        "substeps": [
          {
            "key": "1-1",
            "text": "正在拟定题目与副标题",
            "showDetail": true,
            "detailType": "markdown",
            "detailPayload": {
              "type": "markdown",
              "data": "# 人工智能发展趋势\n\n- 副标题：智能引领未来 · 科技改变生活\n- 作者：AI研究团队\n- 日期：2024-12"
            }
          }
        ]
      }
    }
  ],
  "enhanced_outline_status": "processing",
  "enhanced_outline_uuid": "550e8400-e29b-41d4-a716-446655440000",
  "topic": "人工智能发展趋势",
  "language": "zh",
  "execution_time": 3.25,
  "reference_sources": ["市场分析报告.pdf", "技术趋势文档.docx"]
}
```

#### 增强版大纲状态说明

新增字段说明：
- **`enhanced_outline_status`**: 增强版大纲生成状态
  - `pending`: 等待生成
  - `processing`: 正在生成中
  - `completed`: 生成完成
  - `failed`: 生成失败
- **`enhanced_outline_uuid`**: 增强版大纲的唯一标识符，可用于后续获取增强版内容

当增强版大纲状态为`completed`时，可以使用`enhanced_outline_uuid`通过[获取增强版PPT大纲接口](#获取增强版ppt大纲)获取专业的PPT内容大纲。

### 大纲结构说明

### 大纲结构说明

每个大纲项目包含：
- **key**: 步骤唯一标识符
- **title**: 步骤标题
- **description**: 步骤描述
- **detailType**: 详情类型（markdown/ppt）
- **meta**: 元数据包含摘要和子步骤
  - **summary**: 该步骤的摘要说明
  - **substeps**: 子步骤列表，每个包含：
    - **key**: 子步骤标识
    - **text**: 子步骤描述
    - **showDetail**: 是否显示详细信息
    - **detailType**: 详情类型（可选）
    - **detailPayload**: 详细内容负载（可选）

### 错误响应

#### 400 Bad Request - 主题为空
```json
{
  "status": "error",
  "outline": [],
  "topic": "",
  "language": "zh",
  "execution_time": 0.1,
  "reference_sources": [],
  "error": "PPT主题不能为空"
}
```

#### 400 Bad Request - UUID过多
```json
{
  "status": "error",
  "outline": [],
  "topic": "测试主题",
  "language": "zh",
  "execution_time": 0.1,
  "reference_sources": [],
  "error": "最多支持引用5个文件"
}
```

#### 500 Internal Server Error
```json
{
  "status": "error",
  "outline": [],
  "topic": "人工智能发展趋势",
  "language": "zh",
  "execution_time": 0.5,
  "reference_sources": [],
  "error": "PPT大纲生成失败: LLM服务异常"
}
```

### 使用示例

#### 基础PPT大纲生成（无文件）
```bash
curl -X POST "http://localhost:10000/api/ppt-outline/generate" \
  -F "topic=人工智能发展趋势" \
  -F "language=zh"
```

#### 使用单个UUID引用文件
```bash
curl -X POST "http://localhost:10000/api/ppt-outline/generate" \
  -F "topic=基于市场调研的营销策略" \
  -F "language=zh" \
  -F "file_uuids=550e8400-e29b-41d4-a716-446655440000"
```

#### 使用多个UUID引用文件
```bash
curl -X POST "http://localhost:10000/api/ppt-outline/generate" \
  -F "topic=综合数据分析报告" \
  -F "language=zh" \
  -F "file_uuids=550e8400-e29b-41d4-a716-446655440000,6ba7b810-9dad-11d1-80b4-00c04fd430c8"
```

#### 英文PPT大纲生成
```bash
curl -X POST "http://localhost:10000/api/ppt-outline/generate" \
  -F "topic=Digital Marketing Strategy" \
  -F "language=en"
```

#### 格式化查看响应
```bash
curl -X POST "http://localhost:10000/api/ppt-outline/generate" \
  -F "topic=公司年度总结报告" \
  -F "language=zh" | python -m json.tool
```

---

## 增强版PPT大纲接口

新增的增强版PPT大纲接口提供了专业、完整的PPT内容大纲生成功能，采用异步处理架构。

### 获取增强版PPT大纲 `/api/ppt-outline/enhanced/{uuid}`

#### 接口信息
- **端点**: `GET /api/ppt-outline/enhanced/{uuid}`
- **功能**: 获取之前异步生成的增强版PPT内容大纲
- **内容类型**: `application/json`

#### 路径参数

| 参数名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| `uuid` | `string` | 是 | 增强版大纲的唯一标识符 |

#### 成功响应 (200 OK)

```json
{
  "status": "success",
  "outline": [
    {
      "type": "cover",
      "data": {
        "title": "人工智能在医疗领域的应用",
        "text": "技术创新与临床实践的完美融合"
      }
    },
    {
      "type": "contents",
      "data": {
        "items": ["概述", "核心技术", "应用案例", "发展前景", "总结展望"]
      }
    },
    {
      "type": "transition",
      "data": {
        "title": "概述",
        "text": "了解AI医疗的基本概念和发展背景"
      }
    },
    {
      "type": "content",
      "data": {
        "title": "AI医疗概述",
        "items": [
          {
            "title": "定义与内涵",
            "text": "人工智能医疗是指利用AI技术辅助医疗诊断、治疗和管理的综合应用体系。"
          },
          {
            "title": "发展背景",
            "text": "随着大数据、云计算和机器学习技术的发展，AI在医疗领域展现出巨大潜力。"
          }
        ]
      }
    },
    {
      "type": "content",
      "data": {
        "title": "核心技术解析",
        "items": [
          {
            "title": "机器学习算法",
            "text": "深度学习、神经网络等算法在医学影像识别中发挥重要作用。"
          },
          {
            "title": "自然语言处理",
            "text": "NLP技术用于电子病历分析和医学文献智能检索。"
          },
          {
            "title": "计算机视觉",
            "text": "CV技术辅助医生进行影像诊断，提高诊断准确率。"
          }
        ]
      }
    },
    {
      "type": "transition",
      "data": {
        "title": "应用案例",
        "text": "探索AI医疗的实际应用场景"
      }
    },
    {
      "type": "content",
      "data": {
        "title": "典型应用场景",
        "items": [
          {
            "title": "医学影像诊断",
            "text": "AI辅助X光、CT、MRI等医学影像的自动分析和病灶检测。"
          },
          {
            "title": "药物研发加速",
            "text": "利用AI算法加速新药发现和临床试验过程。"
          }
        ]
      }
    },
    {
      "type": "transition",
      "data": {
        "title": "发展前景",
        "text": "展望AI医疗的未来发展方向"
      }
    },
    {
      "type": "content",
      "data": {
        "title": "未来发展趋势",
        "items": [
          {
            "title": "技术融合深化",
            "text": "AI与生物技术、基因组学等前沿技术的深度融合。"
          },
          {
            "title": "个性化医疗",
            "text": "基于个体基因和健康数据的精准医疗服务。"
          }
        ]
      }
    },
    {
      "type": "transition",
      "data": {
        "title": "总结展望",
        "text": "回顾核心内容并展望未来"
      }
    },
    {
      "type": "content",
      "data": {
        "title": "总结与展望",
        "items": [
          {
            "title": "核心要点回顾",
            "text": "AI医疗技术正在重塑医疗行业的服务模式和质量标准。"
          },
          {
            "title": "发展机遇",
            "text": "政策支持、技术突破和市场需求为AI医疗发展提供强劲动力。"
          }
        ]
      }
    },
    {
      "type": "end",
      "data": {}
    }
  ],
  "topic": "人工智能在医疗领域的应用",
  "language": "zh",
  "created_at": "2025-12-05T10:30:00",
  "reference_sources": [],
  "message": "增强版大纲获取成功"
}
```

#### 页面类型说明

增强版大纲包含以下页面类型：

1. **封面页 (cover)**: 主标题和副标题
2. **目录页 (contents)**: 章节列表导航
3. **过渡页 (transition)**: 章节间的过渡和简介
4. **内容页 (content)**: 主要内容页面，包含2-4个要点
5. **结束页 (end)**: 简洁的结束页面

#### 处理中响应 (200 OK)

当增强版大纲正在生成中时：

```json
{
  "status": "processing",
  "outline": null,
  "topic": "人工智能在医疗领域的应用",
  "language": "zh",
  "created_at": "2025-12-05T10:30:00",
  "reference_sources": [],
  "message": "增强版大纲正在生成中，请稍后再试"
}
```

#### 错误响应

##### 404 Not Found
```json
{
  "detail": "增强版大纲未找到"
}
```

##### 500 Internal Server Error
```json
{
  "detail": "获取增强版大纲失败: 具体错误信息"
}
```

### 获取增强版大纲状态 `/api/ppt-outline/enhanced/{uuid}/status`

#### 接口信息
- **端点**: `GET /api/ppt-outline/enhanced/{uuid}/status`
- **功能**: 查询增强版PPT大纲的生成状态，不返回具体内容
- **内容类型**: `application/json`

#### 路径参数

| 参数名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| `uuid` | `string` | 是 | 增强版大纲的唯一标识符 |

#### 成功响应 (200 OK)

```json
{
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "topic": "人工智能在医疗领域的应用",
  "language": "zh",
  "created_at": "2025-12-05T10:30:00",
  "updated_at": "2025-12-05T10:30:15",
  "reference_sources": [],
  "message": "增强版大纲已生成完成"
}
```

#### 状态说明

| 状态值 | 含义 | 说明 |
|--------|------|------|
| `pending` | 等待生成 | 增强版大纲等待开始生成 |
| `processing` | 正在生成 | 增强版大纲正在后台生成中 |
| `completed` | 生成完成 | 增强版大纲已成功生成，可以获取内容 |
| `failed` | 生成失败 | 增强版大纲生成过程中出现错误 |

#### 不同状态的响应示例

##### 等待中状态
```json
{
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "topic": "人工智能在医疗领域的应用",
  "language": "zh",
  "created_at": "2025-12-05T10:30:00",
  "updated_at": "2025-12-05T10:30:00",
  "reference_sources": [],
  "message": "增强版大纲等待生成中"
}
```

##### 处理中状态
```json
{
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "topic": "人工智能在医疗领域的应用",
  "language": "zh",
  "created_at": "2025-12-05T10:30:00",
  "updated_at": "2025-12-05T10:30:10",
  "reference_sources": [],
  "message": "增强版大纲正在生成中"
}
```

##### 失败状态
```json
{
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "status": "failed",
  "topic": "人工智能在医疗领域的应用",
  "language": "zh",
  "created_at": "2025-12-05T10:30:00",
  "updated_at": "2025-12-05T10:30:20",
  "reference_sources": [],
  "message": "增强版大纲生成失败"
}
```

#### 错误响应

##### 404 Not Found
```json
{
  "detail": "增强版大纲未找到"
}
```

##### 500 Internal Server Error
```json
{
  "detail": "查询状态失败: 具体错误信息"
}
```

### 列出增强版PPT大纲 `/api/ppt-outline/enhanced`

#### 接口信息
- **端点**: `GET /api/ppt-outline/enhanced`
- **功能**: 列出系统中所有的增强版大纲记录，支持状态过滤和分页
- **内容类型**: `application/json`

#### 查询参数

| 参数名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| `status` | `string` | 否 | 过滤状态（pending/processing/completed/failed） |
| `limit` | `integer` | 否 | 返回数量限制，默认50，最大100 |
| `offset` | `integer` | 否 | 偏移量，默认0 |

#### 成功响应 (200 OK)

```json
{
  "total_count": 25,
  "outlines": [
    {
      "uuid": "550e8400-e29b-41d4-a716-446655440000",
      "topic": "人工智能在医疗领域的应用",
      "language": "zh",
      "status": "completed",
      "created_at": "2025-12-05T10:30:00",
      "updated_at": "2025-12-05T10:30:15",
      "reference_sources": []
    },
    {
      "uuid": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      "topic": "区块链技术发展趋势",
      "language": "zh",
      "status": "processing",
      "created_at": "2025-12-05T10:25:00",
      "updated_at": "2025-12-05T10:25:30",
      "reference_sources": ["区块链白皮书.pdf"]
    }
  ],
  "limit": 50,
  "offset": 0
}
```

#### 使用示例

##### 获取所有增强版大纲
```bash
curl "http://localhost:10000/api/ppt-outline/enhanced"
```

##### 按状态过滤
```bash
# 获取已完成的增强版大纲
curl "http://localhost:10000/api/ppt-outline/enhanced?status=completed"

# 获取正在处理的增强版大纲
curl "http://localhost:10000/api/ppt-outline/enhanced?status=processing"
```

##### 分页查询
```bash
# 获取第2页，每页10个
curl "http://localhost:10000/api/ppt-outline/enhanced?limit=10&offset=10"
```

##### 组合查询
```bash
# 获取已完成的第1页，每页20个
curl "http://localhost:10000/api/ppt-outline/enhanced?status=completed&limit=20&offset=0"
```

##### 获取增强版大纲完整流程
```bash
# 1. 首先生成PPT大纲并获取增强版UUID
response=$(curl -s -X POST "http://localhost:10000/api/ppt-outline/generate" \
  -F "topic=人工智能在医疗领域的应用" \
  -F "language=zh")

# 提取增强版大纲UUID
enhanced_uuid=$(echo $response | python -c "import json, sys; data=json.load(sys.stdin); print(data['enhanced_outline_uuid'])")
echo "增强版大纲UUID: $enhanced_uuid"

# 2. 定期检查增强版大纲状态（轮询直到完成）
while true; do
  status_response=$(curl -s "http://localhost:10000/api/ppt-outline/enhanced/$enhanced_uuid/status")
  status=$(echo $status_response | python -c "import json, sys; data=json.load(sys.stdin); print(data['status'])")

  echo "当前状态: $status"

  if [ "$status" = "completed" ]; then
    echo "增强版大纲生成完成！"
    break
  elif [ "$status" = "failed" ]; then
    echo "增强版大纲生成失败"
    break
  fi

  sleep 5  # 等待5秒后再次检查
done

# 3. 获取增强版大纲内容（如果生成完成）
if [ "$status" = "completed" ]; then
  enhanced_outline=$(curl -s "http://localhost:10000/api/ppt-outline/enhanced/$enhanced_uuid")
  echo "增强版大纲获取成功"
  # 可以保存或进一步处理增强版大纲数据
fi

# 4. 或者直接一步获取（如果已知已完成）
# enhanced_outline=$(curl -s "http://localhost:10000/api/ppt-outline/enhanced/$enhanced_uuid")
```

---

## DOCX文档生成接口

### 接口信息
- **端点**: `POST /api/docx/generate`
- **功能**: 根据主题和参考文件生成结构化DOCX文档报告
- **内容类型**: `multipart/form-data`

### 请求参数

| 参数名 | 类型 | 必填 | 描述 |
|--------|------|------|------|
| `topic` | `string` | 是 | 报告主题，最大长度500字符 |
| `language` | `string` | 否 | 输出语言，例如"zh"（中文）、"en"（英文），默认从配置读取 |
| `file_uuids` | `string` | 否 | 已上传文件的UUID列表，用逗号分隔，最多5个UUID，例如: "uuid1,uuid2,uuid3" |

### 成功响应 (200 OK)

```json
{
  "status": "completed",
  "filepath": "/Users/fuchen/Documents/Software/Github/ai_bridge/reports/人工智能发展趋势报告_20241204_143022.docx",
  "title": "人工智能发展趋势报告",
  "agent_summary": "并行生成了5个章节，包含目录、正文、参考概述和参考文献"
}
```

### 文档结构
生成的DOCX文档包含以下结构：
1. **内容目录** - 自动生成的章节导航
2. **章节正文** - 5-8个主要章节，每个章节包含：
   - 章节标题和编号
   - 详细的内容分析
   - 子章节划分
3. **参考内容概述** - 基于上传文件的摘要（如果有）
4. **参考文献** - 引用的文件源列表

### 错误响应

#### 400 Bad Request - 主题为空
```json
{
  "status": "error",
  "filepath": "",
  "title": "",
  "agent_summary": null
}
```

#### 400 Bad Request - UUID过多
```json
{
  "status": "error",
  "filepath": "",
  "title": "",
  "agent_summary": null
}
```

#### 500 Internal Server Error
```json
{
  "status": "error",
  "filepath": "",
  "title": "",
  "agent_summary": null
}
```

### 使用示例

#### 基础文档生成（无文件）
```bash
curl -X POST "http://localhost:10000/api/docx/generate" \
  -F "topic=人工智能发展趋势" \
  -F "language=zh"
```

#### 使用单个UUID引用文件
```bash
curl -X POST "http://localhost:10000/api/docx/generate" \
  -F "topic=基于市场调研的营销策略" \
  -F "language=zh" \
  -F "file_uuids=550e8400-e29b-41d4-a716-446655440000"
```

#### 使用多个UUID引用文件
```bash
curl -X POST "http://localhost:10000/api/docx/generate" \
  -F "topic=综合数据分析报告" \
  -F "language=zh" \
  -F "file_uuids=550e8400-e29b-41d4-a716-446655440000,6ba7b810-9dad-11d1-80b4-00c04fd430c8"
```

#### 英文文档生成
```bash
curl -X POST "http://localhost:10000/api/docx/generate" \
  -F "topic=Digital Marketing Strategy" \
  -F "language=en"
```

#### 格式化查看响应
```bash
curl -X POST "http://localhost:10000/api/docx/generate" \
  -F "topic=公司年度总结报告" \
  -F "language=zh" | python -m json.tool
```

---

## 辅助接口

### 获取支持的文件格式 `/api/files/upload-formats`
- **方法**: `GET`
- **功能**: 获取支持的文件上传格式信息

#### 响应示例
```json
{
  "supported_extensions": [".pdf", ".docx", ".txt", ".jpg", ".jpeg", ".png", ".html", ".htm"],
  "max_file_size_mb": 10.0,
  "max_file_count": 5,
  "description": {
    ".pdf": "PDF文档",
    ".docx": "Word文档",
    ".txt": "纯文本文件",
    ".jpg/.jpeg": "JPEG图片（OCR识别）",
    ".png": "PNG图片（OCR识别）",
    ".html/.htm": "HTML文档（提取正文）"
  }
}
```

### 健康检查 `/health`
- **方法**: `GET`
- **功能**: 检查服务状态

#### 响应示例
```json
{
  "status": "ok"
}
```

---

## 错误处理

### 常见错误码

| HTTP状态码 | 错误类型 | 说明 |
|------------|----------|------|
| 200 | 成功 | 请求处理成功 |
| 400 | 客户端错误 | 请求参数错误，如文件格式不支持、文件过大等 |
| 413 | 请求实体过大 | 上传文件超过大小限制 |
| 415 | 不支持的媒体类型 | 文件MIME类型不支持 |
| 422 | 无法处理的实体 | 请求格式正确但内容无效 |
| 500 | 服务器内部错误 | 服务器处理请求时发生错误 |

### 错误响应格式
所有错误响应都遵循相同的格式：
```json
{
  "status": "error",
  "message": "具体的错误信息",
  "error_code": "可选的错误代码"
}
```

---

## 使用示例

### 完整工作流程

#### 1. 上传文件并获取UUID
```bash
# 上传文件
upload_response=$(curl -s -X POST "http://localhost:10000/api/files/upload" \
  -F "upload_files=@./annual_report.pdf")

# 提取UUID
uuid=$(echo $upload_response | python -c "import json, sys; data=json.load(sys.stdin); print(data['uuids'][0])")
echo "获取UUID: $uuid"
```

#### 2. 使用UUID生成PPT大纲
```bash
# 生成PPT大纲
curl -X POST "http://localhost:10000/api/ppt-outline/generate" \
  -F "topic=2024年公司年度总结" \
  -F "language=zh" \
  -F "file_uuids=$uuid"
```

#### 3. 使用UUID生成DOCX文档
```bash
# 生成DOCX文档
curl -X POST "http://localhost:10000/api/docx/generate" \
  -F "topic=2024年公司年度总结报告" \
  -F "language=zh" \
  -F "file_uuids=$uuid"
```

### Python代码示例

```python
import requests
import json

# 1. 上传文件
with open('market_report.pdf', 'rb') as f:
    files = {'upload_files': f}
    upload_response = requests.post(
        'http://localhost:10000/api/files/upload',
        files=files
    )

if upload_response.status_code == 200:
    upload_data = upload_response.json()
    if upload_data['status'] == 'success':
        file_uuid = upload_data['uuids'][0]
        print(f"文件上传成功，UUID: {file_uuid}")

        # 2. 使用UUID生成PPT大纲（包含增强版功能）
        outline_response = requests.post(
            'http://localhost:10000/api/ppt-outline/generate',
            data={
                'topic': '基于市场调研的营销策略',
                'language': 'zh',
                'file_uuids': file_uuid
            }
        )

        if outline_response.status_code == 200:
            outline_data = outline_response.json()
            print(f"PPT大纲生成成功，包含{len(outline_data['outline'])}个步骤")
            print(f"增强版大纲状态: {outline_data['enhanced_outline_status']}")

            # 获取增强版大纲UUID
            enhanced_uuid = outline_data.get('enhanced_outline_uuid')
            if enhanced_uuid:
                print(f"增强版大纲UUID: {enhanced_uuid}")

                # 等待并获取增强版大纲
                enhanced_outline = wait_and_get_enhanced_outline(enhanced_uuid)
                if enhanced_outline:
                    print(f"增强版大纲获取成功，包含 {len(enhanced_outline)} 页幻灯片")
                    # 处理增强版大纲数据...

        # 3. 使用相同的UUID生成DOCX文档
        docx_response = requests.post(
            'http://localhost:10000/api/docx/generate',
            data={
                'topic': '基于市场调研的营销策略分析报告',
                'language': 'zh',
                'file_uuids': file_uuid
            }
        )

        if docx_response.status_code == 200:
            docx_data = docx_response.json()
            print(f"DOCX文档生成成功，文件路径: {docx_data['filepath']}")
            print(f"文档标题: {docx_data['title']}")
            print(f"生成摘要: {docx_data['agent_summary']}")

def wait_and_get_enhanced_outline(enhanced_uuid, max_wait=60, check_interval=5):
    """等待并获取增强版大纲"""
    import time

    start_time = time.time()

    while time.time() - start_time < max_wait:
        # 检查状态
        status_response = requests.get(
            f'http://localhost:10000/api/ppt-outline/enhanced/{enhanced_uuid}/status'
        )

        if status_response.status_code == 200:
            status_data = status_response.json()
            status = status_data['status']
            print(f"增强版大纲状态: {status}")

            if status == 'completed':
                # 获取增强版大纲内容
                enhanced_response = requests.get(
                    f'http://localhost:10000/api/ppt-outline/enhanced/{enhanced_uuid}'
                )

                if enhanced_response.status_code == 200:
                    enhanced_data = enhanced_response.json()
                    print(f"增强版大纲获取成功！")
                    print(f"包含 {len(enhanced_data['outline'])} 页幻灯片")
                    # 处理增强版大纲数据...
                    return enhanced_data['outline']
                else:
                    print("获取增强版大纲失败")
                    return None

            elif status == 'failed':
                print("增强版大纲生成失败")
                return None

        time.sleep(check_interval)

    print("等待超时，增强版大纲仍未生成完成")
    return None
```

### JavaScript/前端示例

```javascript
// 文件上传
async function uploadFile(file) {
    const formData = new FormData();
    formData.append('upload_files', file);

    try {
        const response = await fetch('http://localhost:10000/api/files/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();
        if (data.status === 'success') {
            return data.uuids[0]; // 返回第一个UUID
        }
    } catch (error) {
        console.error('文件上传失败:', error);
    }
}

// 生成PPT大纲（包含增强版功能）
async function generatePPTOutline(topic, language, fileUuid) {
    const formData = new FormData();
    formData.append('topic', topic);
    formData.append('language', language);
    formData.append('file_uuids', fileUuid);

    try {
        const response = await fetch('http://localhost:10000/api/ppt-outline/generate', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();
        if (data.status === 'success') {
            console.log('PPT大纲生成成功:', data.outline);
            console.log('增强版大纲状态:', data.enhanced_outline_status);

            // 如果有增强版大纲UUID，等待并获取
            if (data.enhanced_outline_uuid) {
                console.log('增强版大纲UUID:', data.enhanced_outline_uuid);
                const enhancedOutline = await waitAndGetEnhancedOutline(
                    data.enhanced_outline_uuid,
                    topic,
                    language
                );
                if (enhancedOutline) {
                    console.log('增强版大纲获取成功:', enhancedOutline);
                }
            }

            return data.outline;
        }
    } catch (error) {
        console.error('PPT大纲生成失败:', error);
    }
}

// 等待并获取增强版大纲
async function waitAndGetEnhancedOutline(enhancedUuid, topic, language, maxWait = 60, checkInterval = 5) {
    const startTime = Date.now();

    while (Date.now() - startTime < maxWait * 1000) {
        try {
            // 检查状态
            const statusResponse = await fetch(`http://localhost:10000/api/ppt-outline/enhanced/${enhancedUuid}/status`);
            const statusData = await statusResponse.json();
            const status = statusData.status;

            console.log(`增强版大纲状态: ${status}`);

            if (status === 'completed') {
                // 获取增强版大纲内容
                const enhancedResponse = await fetch(`http://localhost:10000/api/ppt-outline/enhanced/${enhancedUuid}`);
                const enhancedData = await enhancedResponse.json();

                if (enhancedData.status === 'success') {
                    console.log('增强版大纲获取成功！');
                    console.log(`包含 ${enhancedData.outline.length} 页幻灯片`);
                    return enhancedData.outline;
                } else {
                    console.log('获取增强版大纲失败');
                    return null;
                }
            } else if (status === 'failed') {
                console.log('增强版大纲生成失败');
                return null;
            }

        } catch (error) {
            console.error('检查增强版大纲状态失败:', error);
            return null;
        }

        await new Promise(resolve => setTimeout(resolve, checkInterval * 1000));
    }

    console.log('等待超时，增强版大纲仍未生成完成');
    return null;
}

// 使用示例
const fileInput = document.getElementById('fileInput');
fileInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (file) {
        const uuid = await uploadFile(file);
        if (uuid) {
            const outline = await generatePPTOutline('人工智能发展趋势', 'zh', uuid);
            // 处理大纲数据...

            // 生成DOCX文档
            const docxResult = await generateDOCXDocument('人工智能发展趋势分析报告', 'zh', uuid);
            if (docxResult) {
                console.log('DOCX文档生成成功:', docxResult.filepath);
            }
        }
}

// 生成DOCX文档
async function generateDOCXDocument(topic, language, fileUuid) {
    const formData = new FormData();
    formData.append('topic', topic);
    formData.append('language', language);
    formData.append('file_uuids', fileUuid);

    try {
        const response = await fetch('http://localhost:10000/api/docx/generate', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();
        if (data.status === 'completed') {
            console.log('DOCX文档生成成功:', data);
            return data;
        }
    } catch (error) {
        console.error('DOCX文档生成失败:', error);
    }
}
    }
});
```

---

## 性能说明

- **文件上传**: 支持异步处理，大文件上传流畅
- **PPT大纲生成**: 平均响应时间2-5秒，取决于主题复杂度和参考文件大小
- **DOCX文档生成**: 平均响应时间10-30秒，取决于文档长度和参考文件数量
- **并发处理**: 支持多用户同时上传和生成
- **内存优化**: 流式文件处理，避免内存溢出

## 安全考虑

- **文件验证**: 严格的文件类型和大小验证
- **UUID保护**: 使用UUID避免直接文件路径访问
- **存储隔离**: 文件存储在受控目录，防止目录遍历攻击
- **内容检查**: 建议在生产环境中添加文件内容安全检查

## 最佳实践

1. **文件上传后立即使用**: 避免UUID过期或文件被清理
2. **合理控制文件数量**: 建议单个请求不超过3-4个文件
3. **错误重试**: 实现适当的重试机制处理网络异常
4. **进度显示**: 大文件上传时显示上传进度
5. **缓存策略**: 对频繁访问的UUID结果进行客户端缓存
