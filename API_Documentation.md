# OpenManus API 端点文档

## 概述

本文档详细介绍了 OpenManus 服务中的两个核心API端点：`/thinking/steps` 和 `/generating/report`。这两个端点配合使用，可以实现从任务规划到文档生成的完整工作流。

---

## `/thinking/steps` 端点

### 功能概述

生成结构化的思考过程步骤数组，用于将复杂任务分解为可执行的步骤序列。该端点使用AI智能体分析任务目标，并生成15-20个逻辑清晰的执行步骤。

### 请求格式

**HTTP方法**: `POST`
**Content-Type**: `application/json`
**端点**: `/thinking/steps`

#### 请求参数

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| goal | string | 否 | null | 任务目标或主题描述，用于个性化生成步骤内容 |
| count | integer | 否 | 17 | 期望生成的步骤数量，系统会自动限制在15-20范围内 |

#### 请求体示例

```json
{
  "goal": "开发一个移动端电商应用",
  "count": 18
}
```

或者简化版本：

```json
{
  "goal": "制定年度营销策略"
}
```

### 响应格式

**Content-Type**: `application/json`

响应为一个JSON数组，包含多个步骤对象，每个对象包含以下字段：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| key | integer | 步骤序号（从1开始递增） |
| title | string | 步骤标题，从预定义主题中选择 |
| descirption | string | 步骤描述，中文说明该步骤的具体内容 |
| showDetail | boolean | 是否展示详细信息 |
| detailType | string | 当showDetail为true时显示，可选值：image/table/list/code/diagram |

#### 预定义主题类别

系统使用以下7个主题类别：
- 理解与界定
- 规划与拆解
- 信息收集
- 方案设计
- 实现与验证
- 风险与合规
- 总结与交付

#### 响应示例

```json
[
  {
    "key": 1,
    "title": "理解与界定",
    "descirption": "明确移动端电商应用的核心功能需求和目标用户群体。",
    "showDetail": false
  },
  {
    "key": 2,
    "title": "规划与拆解",
    "descirption": "制定项目开发计划，拆解各模块功能和技术架构。",
    "showDetail": true,
    "detailType": "table"
  },
  {
    "key": 3,
    "title": "信息收集",
    "descirption": "调研市场同类产品，分析竞品优势和用户体验。",
    "showDetail": true,
    "detailType": "list"
  }
]
```

### 错误处理

| HTTP状态码 | 错误类型 | 说明 |
|------------|----------|------|
| 500 | Internal Server Error | 智能体处理失败时使用本地备用方案 |
| 422 | Unprocessable Entity | 请求参数格式错误 |

### 技术实现

- **智能体**: `ThinkingStepsAgent`
- **备用机制**: 当AI生成失败时，使用确定性算法生成基础步骤
- **日志记录**: 完整的执行过程日志
- **参数验证**: 自动将count限制在15-20范围内

---

## `/generating/report` 端点

### 功能概述

基于思考步骤生成完整的报告文档。支持Word文档(.docx)和PowerPoint幻灯片(.pptx)两种格式，并可上传参考材料辅助内容生成。

### 请求格式

**HTTP方法**: `POST`
**Content-Type**: `multipart/form-data`
**端点**: `/generating/report`

#### 请求参数

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| topic | string | 是 | - | 报告主题或标题 |
| format | string | 否 | docx | 输出格式，支持"docx"或"pptx" |
| steps_file | File | 是 | - | `/thinking/steps`生成的JSON步骤文件 |
| language | string | 否 | zh | 输出语言，如"zh"、"EN"等 |
| filepath | string | 否 | - | 自定义保存路径（相对于workspace） |
| upload_files | File[] | 否 | - | 参考资料文件，最多3个 |

#### 请求示例（使用curl）

```bash
curl -X POST "http://localhost:10000/generating/report" \
  -F "topic=人工智能在医疗领域的应用前景" \
  -F "format=docx" \
  -F "steps_file=@steps.json" \
  -F "language=zh" \
  -F "filepath=reports/ai_medical_report.docx" \
  -F "upload_files=@reference1.pdf" \
  -F "upload_files=@reference2.docx"
```

#### steps.json文件格式

上传的步骤文件应该是`/thinking/steps`端点返回的JSON数组：

```json
[
  {
    "key": 1,
    "title": "理解与界定",
    "descirption": "明确人工智能在医疗领域的应用范围和研究目标。",
    "showDetail": false
  },
  {
    "key": 2,
    "title": "信息收集",
    "descirption": "收集最新的AI医疗应用案例和技术发展趋势。",
    "showDetail": true,
    "detailType": "list"
  }
]
```

### 响应格式

**Content-Type**: `application/json`

响应为`ReportResult`对象：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| status | string | 生成状态，通常为"completed" |
| filepath | string | 生成文件的绝对路径 |
| title | string | 报告标题 |
| agent_summary | string | 智能体执行摘要（可选） |

#### 响应示例

```json
{
  "status": "completed",
  "filepath": "/Users/fuchen/Documents/Software/Github/ai_bridge/workspace/reports/人工智能在医疗领域的应用前景.docx",
  "title": "人工智能在医疗领域的应用前景",
  "agent_summary": "报告生成完成，包含15个章节，涵盖了AI医疗应用的技术现状、典型案例和未来发展趋势。"
}
```

### 工作流程

#### 1. DOCX文档生成流程

1. **步骤解析**: 解析上传的steps.json文件
2. **目录生成**: 基于步骤生成报告目录结构
3. **智能体分类**: 将步骤分类到不同的专业智能体
   - `ReportSearchAgent`: 处理信息收集、搜索相关步骤
   - `ReportResearchAgent`: 处理研究、分析相关步骤
   - `ReportWriterAgent`: 负责最终文档撰写
4. **多智能体协作**: 使用`PlanningFlow`协调各智能体执行
5. **文档生成**: 使用`WordDocumentTool`生成最终文档
6. **参考资料处理**: 自动提取URL和上传文件信息生成附录

#### 2. PPTX幻灯片生成流程

1. **Marp Markdown生成**: 先生成Marp格式的Markdown文件
2. **智能体协作**: 使用专门的`MdSlideWriterAgent`
3. **模板应用**: 支持自定义Marp模板和背景图片
4. **格式转换**: 使用Marp CLI将MD转换为PPTX
5. **文件清理**: 转换成功后删除临时MD文件

### 支持的文件格式

#### 上传参考材料

- PDF文档
- Word文档 (.doc, .docx)
- 文本文件 (.txt)
- 图片文件 (.jpg, .png等)

#### 输出格式

- **DOCX**: 标准Word文档格式
- **PPTX**: PowerPoint幻灯片格式（通过Marp转换）

### 错误处理

| HTTP状态码 | 错误类型 | 说明 |
|------------|----------|------|
| 400 | Bad Request | topic为空或steps_file格式错误 |
| 400 | Bad Request | 文件解析失败 |
| 500 | Internal Server Error | 智能体执行失败 |
| 503 | Service Unavailable | 服务正在初始化 |

### 技术特性

#### 安全机制
- **服务锁**: 使用`asyncio.Lock`确保并发安全
- **文件路径验证**: 自动解析和验证文件路径
- **大小限制**: 限制上传文件大小和数量

#### 日志记录
- **执行日志**: 完整记录每个步骤的执行过程
- **错误追踪**: 详细的错误信息和堆栈跟踪
- **性能监控**: 记录处理时间和资源使用

#### 备用机制
- **文档生成备用**: 当主要生成失败时，使用基础模板创建文档
- **Marp转换备用**: 当Marp CLI不可用时，保留MD文件

---

## 使用建议和最佳实践

### 1. 端点协作使用

推荐的工作流程：

```bash
# 步骤1: 生成思考步骤
curl -X POST "http://localhost:10000/thinking/steps" \
  -H "Content-Type: application/json" \
  -d '{"goal": "制定企业数字化转型战略", "count": 18}' \
  > steps.json

# 步骤2: 基于步骤生成报告
curl -X POST "http://localhost:10000/generating/report" \
  -F "topic=企业数字化转型战略规划" \
  -F "format=docx" \
  -F "steps_file=@steps.json" \
  -F "language=zh"
```

### 2. 参数优化建议

#### thinking/steps端点
- **goal参数**: 提供具体明确的任务描述，有助于生成更精准的步骤
- **count参数**: 一般使用默认值17，复杂任务可设为20

#### generating/report端点
- **language参数**: 根据目标读者设置合适的语言
- **filepath参数**: 建议使用有意义的文件名，便于后续管理
- **upload_files**: 上传相关参考资料可显著提升内容质量

### 3. 性能考虑

- **处理时间**: 报告生成通常需要1-5分钟，取决于步骤数量和复杂度
- **并发限制**: 服务同时只能处理一个报告生成请求
- **资源使用**: 建议在服务器资源充足时使用

### 4. 故障排除

#### 常见问题

**Q: steps.json文件格式错误**
A: 确保文件是有效的JSON数组，包含必要的字段

**Q: 生成的文档内容不完整**
A: 检查steps.json中的步骤描述是否清晰明确

**Q: PPTX生成失败**
A: 确保系统已安装Marp CLI工具

**Q: 服务返回503错误**
A: 等待当前任务完成后重试，或检查服务状态

#### 调试方法

1. 查看执行日志了解详细处理过程
2. 检查workspace目录下的生成文件
3. 使用简化的参数测试端点功能

---

## 版本信息

- **API版本**: v1.0.0
- **最后更新**: 2024年
- **兼容性**: 支持FastAPI和Uvicorn

## 联系支持

如遇到技术问题或需要功能增强建议，请查看项目文档或提交Issue。
