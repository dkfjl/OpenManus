# 报告生成 + 对象存储集成 - 完整指南

## 功能说明

`/api/docx/generate` 接口现在**自动集成了对象存储上传功能**：

1. ✅ 生成DOCX报告
2. ✅ 自动上传到MinIO（或其他配置的对象存储）
3. ✅ 返回预览和下载URL
4. ✅ 即使对象存储未配置也能正常工作

## API使用

### 请求

```bash
POST /api/docx/generate
Content-Type: application/x-www-form-urlencoded

topic=人工智能发展趋势分析
language=zh
file_uuids=uuid1,uuid2  # 可选
user_id=test_user       # 可选，默认为default_user
```

### 响应

#### 成功响应（配置了对象存储）

```json
{
  "status": "success",
  "filepath": "/path/to/report.docx",
  "title": "人工智能发展趋势分析",
  "agent_summary": null,
  "file_uuid": "550e8400-e29b-41d4-a716-446655440000",
  "preview_url": "/api/reports/550e8400-e29b-41d4-a716-446655440000/preview",
  "download_url": "/api/reports/550e8400-e29b-41d4-a716-446655440000/download",
  "storage_enabled": true
}
```

#### 成功响应（未配置对象存储）

```json
{
  "status": "success",
  "filepath": "/path/to/report.docx",
  "title": "人工智能发展趋势分析",
  "agent_summary": null,
  "file_uuid": null,
  "preview_url": null,
  "download_url": null,
  "storage_enabled": false
}
```

## 使用流程

### 1. 配置MinIO（如果还没配置）

确保 `config/config.toml` 中配置了存储：

```toml
[storage]
type = "minio"
bucket = "zbank"
region = "us-east-1"
access_key = "minioadmin"
secret_key = "minioadmin"
endpoint = "http://172.16.1.120:9000"
presign_expire_seconds = 3600
file_expire_days = 30

[storage.security]
private_storage = true
enable_cdn = false
max_downloads = 0
enable_access_log = true
```

### 2. 启动MinIO

```bash
docker run -d \
  -p 9000:9000 \
  -p 9001:9001 \
  --name minio \
  -v ~/minio/data:/data \
  -e "MINIO_ROOT_USER=minioadmin" \
  -e "MINIO_ROOT_PASSWORD=minioadmin" \
  quay.io/minio/minio server /data --console-address ":9001"
```

### 3. 创建Bucket

访问 http://172.16.1.120:9001，创建名为 `zbank` 的bucket。

或使用命令行：

```bash
mc alias set myminio http://172.16.1.120:9000 minioadmin minioadmin
mc mb myminio/zbank
```

### 4. 调用API生成报告

```bash
curl -X POST http://localhost:8000/api/docx/generate \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "topic=2024年度工作总结报告" \
  -d "language=zh" \
  -d "user_id=user123"
```

### 5. 获取预览URL

从响应中获取 `preview_url`，然后调用：

```bash
curl http://localhost:8000/api/reports/550e8400-e29b-41d4-a716-446655440000/preview
```

响应：

```json
{
  "preview_url": "http://172.16.1.120:9000/zbank/reports/20241210/550e8400-e29b-41d4-a716-446655440000.docx?X-Amz-...",
  "expire_at": "2024-12-10T16:00:00Z",
  "file_info": {
    "file_uuid": "550e8400-e29b-41d4-a716-446655440000",
    "filename": "report.docx",
    "file_size": 1024000,
    "created_at": "2024-12-10T15:00:00Z"
  }
}
```

### 6. 在前端预览

使用 `preview_url` 中的实际MinIO签名URL进行预览：

```javascript
// 前端代码示例
async function generateAndPreviewReport(topic) {
  // 1. 生成报告
  const response = await fetch('/api/docx/generate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: new URLSearchParams({
      topic: topic,
      language: 'zh',
      user_id: 'current_user'
    })
  });

  const result = await response.json();

  if (result.storage_enabled && result.preview_url) {
    // 2. 获取预签名URL
    const previewResponse = await fetch(result.preview_url);
    const previewData = await previewResponse.json();

    // 3. 使用docx-preview预览
    const docxUrl = previewData.preview_url;

    // 下载文件并预览
    const docxResponse = await fetch(docxUrl);
    const arrayBuffer = await docxResponse.arrayBuffer();

    // 使用docx-preview渲染
    const container = document.getElementById('docx-preview');
    docx.renderAsync(arrayBuffer, container);
  } else {
    console.warn('对象存储未配置或上传失败');
    // 降级处理：直接下载本地文件
    window.location.href = `/download?filepath=${result.filepath}`;
  }
}
```

## Python客户端示例

```python
import requests

# 1. 生成报告
response = requests.post(
    'http://localhost:8000/api/docx/generate',
    data={
        'topic': 'Python最佳实践指南',
        'language': 'zh',
        'user_id': 'developer_123'
    }
)

result = response.json()
print(f"报告生成成功！")
print(f"本地路径: {result['filepath']}")

if result['storage_enabled']:
    print(f"文件UUID: {result['file_uuid']}")
    print(f"预览URL: {result['preview_url']}")
    print(f"下载URL: {result['download_url']}")

    # 2. 获取预签名URL
    preview_response = requests.get(
        f"http://localhost:8000{result['preview_url']}"
    )
    preview_data = preview_response.json()

    print(f"\n预签名URL: {preview_data['preview_url']}")
    print(f"过期时间: {preview_data['expire_at']}")

    # 3. 下载文件
    docx_response = requests.get(preview_data['preview_url'])
    with open('downloaded_report.docx', 'wb') as f:
        f.write(docx_response.content)
    print("\n文件已下载到: downloaded_report.docx")
else:
    print("⚠️  对象存储未启用")
```

## 工作流程说明

```
1. 客户端调用 /api/docx/generate
   ↓
2. 后端生成DOCX文件（保存到本地临时目录）
   ↓
3. 检查是否配置了对象存储
   ↓
4. 如果配置了：
   - 上传文件到MinIO
   - 生成file_uuid
   - 删除本地临时文件
   - 返回预览和下载URL路径
   ↓
5. 如果未配置：
   - 保留本地文件
   - 返回本地文件路径
   - storage_enabled = false
   ↓
6. 客户端根据storage_enabled决定预览方式
```

## 响应字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 状态，通常为"success" |
| `filepath` | string | 本地文件路径 |
| `title` | string | 报告标题 |
| `agent_summary` | string | 代理摘要（可选） |
| `file_uuid` | string | 对象存储中的文件UUID（如果上传成功） |
| `preview_url` | string | 预览URL路径（相对路径，需要调用此接口获取实际的预签名URL） |
| `download_url` | string | 下载URL路径（相对路径） |
| `storage_enabled` | boolean | 是否启用了对象存储 |

## 注意事项

### 1. 本地文件会被删除

如果对象存储上传成功，**本地临时文件会被自动删除**。如果需要保留本地文件，有两种方式：

- **方式1**：不配置对象存储（注释掉config.toml中的[storage]部分）
- **方式2**：修改代码，在上传后不删除本地文件

### 2. 对象存储失败不影响报告生成

即使MinIO上传失败，接口也会正常返回报告生成结果，只是：
- `storage_enabled = false`
- `file_uuid = null`
- `preview_url = null`

### 3. 预览URL是两步操作

1. **第一步**：调用 `/api/reports/{uuid}/preview` 获取预签名URL
2. **第二步**：使用预签名URL下载文件内容

这样设计是为了：
- 验证用户权限
- 记录访问日志
- 生成临时的预签名URL（1小时过期）

### 4. 用户ID和权限

当前 `user_id` 默认为 `default_user`，生产环境应该：
- 从JWT Token或Session中获取真实用户ID
- 在预览时验证用户权限（只能预览自己生成的报告）

## 故障排查

### 问题1：返回 `storage_enabled = false`

**原因**：对象存储未配置或初始化失败

**解决方案**：
1. 检查 `config/config.toml` 中的 `[storage]` 配置
2. 检查MinIO服务是否运行：`docker ps | grep minio`
3. 检查bucket是否存在：`mc ls myminio/zbank`
4. 查看应用日志，搜索 "Storage service" 相关信息

### 问题2：文件上传失败

**日志中出现**：`Failed to upload report to object storage`

**解决方案**：
1. 检查MinIO endpoint是否可访问
2. 检查access_key和secret_key是否正确
3. 检查bucket权限：`mc anonymous get myminio/zbank`
4. 确保bucket是私有的：`mc anonymous set none myminio/zbank`

### 问题3：预签名URL无法访问

**原因**：endpoint配置问题

**解决方案**：
- 如果应用和MinIO在不同的容器，不能用localhost
- 确保endpoint是客户端可以访问的地址

```toml
# ❌ 错误（如果前端无法访问localhost）
endpoint = "http://localhost:9000"

# ✅ 正确（使用IP或域名）
endpoint = "http://172.16.1.120:9000"
```

### 问题4：文件找不到

**原因**：本地临时文件路径错误

**解决方案**：
检查 `generate_report_from_steps` 返回的 `filepath` 是否正确

## 性能优化

### 1. 异步上传

当前实现会等待上传完成才返回。对于大文件，可以改为后台上传：

```python
# 返回后异步上传（需要实现后台任务队列）
import asyncio

asyncio.create_task(upload_to_storage(filepath, user_id))
```

### 2. 并发处理

如果有多个报告同时生成，确保数据库连接池足够大：

```python
# session.py中调整
_engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,  # 增加连接池大小
    max_overflow=10
)
```

### 3. 文件清理

定期清理过期的文件：

```bash
# 使用mc工具清理30天前的文件
mc rm --recursive --force --older-than 30d myminio/zbank/reports/
```

或在代码中实现定时任务。

## 总结

现在 `/api/docx/generate` 接口已经**完全集成了对象存储功能**：

- ✅ 自动上传到MinIO
- ✅ 返回预览和下载URL
- ✅ 兼容未配置对象存储的场景
- ✅ 上传失败不影响报告生成
- ✅ 记录访问日志
- ✅ 支持权限验证

你只需要：
1. 配置好MinIO
2. 创建bucket
3. 调用接口即可！
