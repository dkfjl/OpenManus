# 报告文件存储系统 - 快速开始

## 概述

本系统已从MySQL迁移到**SQLite**，提供：
- ✅ 私有对象存储（阿里云OSS、AWS S3）
- ✅ 临时URL预签名访问
- ✅ SQLite本地数据库（自动初始化）
- ✅ 文件访问日志记录

## 快速开始

### 1. 安装依赖

```bash
pip install aiosqlite~=0.20.0 oss2~=2.18.0 boto3~=1.37.18
```

### 2. 配置对象存储

编辑 `config/config.toml`:

```toml
[storage]
type = "oss"                    # 或 "s3"
bucket = "your-bucket-name"
region = "cn-hangzhou"
access_key = "your-access-key"
secret_key = "your-secret-key"
presign_expire_seconds = 3600   # 1小时
file_expire_days = 30           # 30天
```

### 3. 启动服务

```bash
uvicorn app.app:app --reload
```

数据库会在首次启动时自动创建在 `db/report_storage.db`

## API使用

### 上传文件（集成到报告生成）

```python
from app.services.report_file_service import ReportFileService
from app.api.deps.report_file_deps import get_storage_service
from app.report_storage_db.session import get_report_db_session

async def upload_generated_report(file_path: Path, user_id: str):
    storage_service = get_storage_service()

    async for db_session in get_report_db_session():
        service = ReportFileService(storage_service, db_session)
        file_uuid = await service.upload_report_file(
            file_path=file_path,
            original_filename="报告.docx",
            user_id=user_id,
            expire_days=30
        )
        return file_uuid
```

### 获取预览URL

```bash
# HTTP GET
curl http://localhost:8000/api/reports/{file_uuid}/preview
```

响应：
```json
{
  "preview_url": "https://bucket.oss-cn-hangzhou.aliyuncs.com/...",
  "expire_at": "2024-01-10T11:00:00Z",
  "file_info": {
    "file_uuid": "550e8400-...",
    "filename": "报告.docx",
    "file_size": 1024000,
    "created_at": "2024-01-10T10:00:00Z"
  }
}
```

### 获取文件元数据

```bash
curl http://localhost:8000/api/reports/{file_uuid}/metadata
```

### 下载文件

```bash
curl http://localhost:8000/api/reports/{file_uuid}/download
```

### 删除文件

```bash
curl -X DELETE http://localhost:8000/api/reports/{file_uuid}
```

## 数据库

### 默认配置
- **类型**: SQLite
- **位置**: `db/report_storage.db`
- **自动初始化**: 是

### 自定义数据库

通过环境变量覆盖：

```bash
# SQLite（自定义路径）
export REPORT_DATABASE_URL="sqlite+aiosqlite:///path/to/custom.db"

# MySQL（如果需要）
export REPORT_DATABASE_URL="mysql+aiomysql://user:password@host:port/database"
```

### 手动初始化（可选）

```python
from app.report_storage_db.session import init_db
import asyncio

asyncio.run(init_db())
```

或使用SQLite命令行：

```bash
sqlite3 db/report_storage.db < db/ddl/003_create_report_storage_tables_sqlite.sql
```

## 数据库表结构

### report_files（文件元数据）
- id - 主键
- uuid - 文件唯一标识（索引）
- original_filename - 原始文件名
- file_size - 文件大小
- storage_key - 对象存储路径
- storage_type - 存储类型（oss/s3）
- created_at - 创建时间
- expires_at - 过期时间
- download_count - 下载次数
- status - 状态（active/expired/deleted）

### file_access_logs（访问日志）
- id - 主键
- file_uuid - 文件UUID（索引）
- user_id - 用户ID
- access_type - 访问类型（preview/download）
- access_ip - 访问IP
- user_agent - 用户代理
- presign_url - 临时URL
- expire_at - URL过期时间
- access_at - 访问时间

## 技术栈

- **数据库**: SQLite 3.9+
- **异步驱动**: aiosqlite
- **ORM**: SQLAlchemy 2.0
- **对象存储**: 阿里云OSS / AWS S3
- **框架**: FastAPI

## 优势

相比MySQL：
- ✅ 无需额外数据库服务器
- ✅ 零配置，开箱即用
- ✅ 文件级数据库，易于备份
- ✅ 适合中小规模应用
- ✅ 支持JSON字段
- ✅ ACID事务保证

## 注意事项

1. **并发写入**: SQLite适合读多写少的场景，如需高并发写入，建议迁移到MySQL
2. **备份**: 定期备份 `db/report_storage.db` 文件
3. **文件大小**: 建议单个文件不超过50MB
4. **清理**: 定期清理过期文件和日志

## 故障排查

### 数据库锁定错误

```python
# 可能原因：多个进程同时写入
# 解决方案：使用单进程或迁移到MySQL
```

### 表不存在错误

```bash
# 手动初始化数据库
python -c "from app.report_storage_db.session import init_db; import asyncio; asyncio.run(init_db())"
```

## 性能优化

1. **启用WAL模式**（已默认启用）
2. **定期VACUUM**清理碎片
3. **索引优化**（已创建必要索引）
4. **连接池**（已配置）

## 迁移回MySQL

如需迁移回MySQL：

1. 设置环境变量：
```bash
export REPORT_DATABASE_URL="mysql+aiomysql://user:password@host:port/database"
```

2. 执行MySQL DDL：
```bash
mysql -u user -p database < db/ddl/002_create_report_storage_tables.sql
```

3. 数据迁移（如需要）：
```python
# 使用SQLAlchemy或pandas进行数据迁移
```
