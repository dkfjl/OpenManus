# MinIO + 报告文件存储系统 - 快速开始

## 什么是MinIO？

MinIO是一个高性能的**S3兼容**对象存储服务，可以**自托管**部署，非常适合：
- ✅ 本地开发测试
- ✅ 私有云部署
- ✅ 无需依赖云服务商
- ✅ 完全免费开源

## 快速开始

### 1. 启动MinIO服务

#### 方式1：使用Docker（推荐）

```bash
# 创建数据目录
mkdir -p ~/minio/data

# 启动MinIO
docker run -d \
  -p 9000:9000 \
  -p 9001:9001 \
  --name minio \
  -v ~/minio/data:/data \
  -e "MINIO_ROOT_USER=minioadmin" \
  -e "MINIO_ROOT_PASSWORD=minioadmin" \
  quay.io/minio/minio server /data --console-address ":9001"
```

#### 方式2：使用Docker Compose

创建 `docker-compose.yml`:

```yaml
version: '3.8'

services:
  minio:
    image: quay.io/minio/minio
    container_name: minio
    ports:
      - "9000:9000"  # API端口
      - "9001:9001"  # Web控制台端口
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - ./minio/data:/data
    command: server /data --console-address ":9001"
    restart: unless-stopped
```

启动：
```bash
docker-compose up -d
```

#### 方式3：直接安装

```bash
# macOS
brew install minio/stable/minio

# Linux
wget https://dl.min.io/server/minio/release/linux-amd64/minio
chmod +x minio
./minio server /data --console-address ":9001"
```

### 2. 访问MinIO控制台

打开浏览器访问：**http://localhost:9001**

- **用户名**: `minioadmin`
- **密码**: `minioadmin`

### 3. 创建存储桶（Bucket）

在MinIO控制台中：

1. 点击左侧菜单 **"Buckets"**
2. 点击右上角 **"Create Bucket"**
3. 输入桶名称：`reports`
4. 点击 **"Create Bucket"**

或者使用命令行（需要安装mc客户端）：

```bash
# 安装mc客户端
brew install minio/stable/mc  # macOS
# 或者下载: https://dl.min.io/client/mc/release/

# 配置mc
mc alias set local http://localhost:9000 minioadmin minioadmin

# 创建bucket
mc mb local/reports

# 设置bucket为私有（默认）
mc anonymous set none local/reports
```

### 4. 配置 config.toml

编辑 `config/config.toml`，确保使用MinIO配置：

```toml
[storage]
type = "minio"                                  # 使用MinIO
bucket = "reports"                              # 刚才创建的桶
region = "us-east-1"                           # 任意值即可
access_key = "admin"                       # 默认用户名
secret_key = "Admin123456!"                       # 默认密码
endpoint = "http://localhost:9000"              # MinIO API地址
presign_expire_seconds = 3600                   # URL过期时间：1小时
file_expire_days = 30                          # 文件过期：30天

[storage.security]
private_storage = true                          # 私有存储
enable_cdn = false                             # 本地部署不需要CDN
max_downloads = 0                              # 不限制下载次数
enable_access_log = true                       # 记录访问日志
```

### 5. 启动应用

```bash
# 安装依赖（如果还没安装）
pip install boto3~=1.37.18 aiosqlite~=0.20.0

# 启动服务
uvicorn app.app:app --reload
```

### 6. 测试上传和预览

#### 测试文件上传

```python
from pathlib import Path
from app.services.report_file_service import ReportFileService
from app.api.deps.report_file_deps import get_storage_service
from app.report_storage_db.session import get_report_db_session

async def test_upload():
    # 创建一个测试文件
    test_file = Path("test_report.docx")
    test_file.write_bytes(b"test content")

    storage_service = get_storage_service()

    async for db_session in get_report_db_session():
        service = ReportFileService(storage_service, db_session)
        file_uuid = await service.upload_report_file(
            file_path=test_file,
            original_filename="测试报告.docx",
            user_id="test_user",
            expire_days=30
        )
        print(f"✅ 文件上传成功！UUID: {file_uuid}")
        return file_uuid

# 运行测试
import asyncio
file_uuid = asyncio.run(test_upload())
```

#### 获取预览URL

```bash
curl http://localhost:8000/api/reports/{file_uuid}/preview
```

## MinIO配置说明

### 基本配置

| 参数 | 说明 | 示例 |
|------|------|------|
| `type` | 存储类型 | `minio` |
| `bucket` | 存储桶名称 | `reports` |
| `endpoint` | MinIO服务地址 | `http://localhost:9000` |
| `access_key` | 访问密钥 | `minioadmin` |
| `secret_key` | 私密密钥 | `minioadmin` |
| `region` | 区域（任意值） | `us-east-1` |

### 高级配置

#### 使用HTTPS

如果MinIO配置了SSL证书：

```toml
endpoint = "https://minio.example.com:9000"
```

#### 自定义访问密钥

在MinIO控制台创建新的访问密钥：

1. 进入 **"Identity"** → **"Service Accounts"**
2. 点击 **"Create Service Account"**
3. 复制生成的 Access Key 和 Secret Key
4. 更新 config.toml

```toml
access_key = "your-custom-access-key"
secret_key = "your-custom-secret-key"
```

## MinIO管理命令

### 使用mc客户端管理

```bash
# 配置别名
mc alias set myminio http://localhost:9000 minioadmin minioadmin

# 列出所有bucket
mc ls myminio

# 列出bucket中的文件
mc ls myminio/reports

# 查看文件
mc cat myminio/reports/reports/20241210/test.docx

# 下载文件
mc cp myminio/reports/reports/20241210/test.docx ./

# 删除文件
mc rm myminio/reports/reports/20241210/test.docx

# 设置bucket策略（公开读取，不推荐）
mc anonymous set download myminio/reports

# 设置bucket为私有（推荐）
mc anonymous set none myminio/reports

# 查看bucket统计
mc du myminio/reports
```

### 使用Web控制台

访问 http://localhost:9001

- **查看文件**：Buckets → reports → Browse
- **上传文件**：点击 Upload 按钮
- **下载文件**：点击文件 → Download
- **删除文件**：选择文件 → Delete
- **分享链接**：点击文件 → Share（生成临时访问链接）

## 生产环境部署建议

### 1. 修改默认密码

```bash
docker run -d \
  -p 9000:9000 \
  -p 9001:9001 \
  --name minio \
  -v ~/minio/data:/data \
  -e "MINIO_ROOT_USER=your-admin-username" \
  -e "MINIO_ROOT_PASSWORD=your-strong-password" \
  quay.io/minio/minio server /data --console-address ":9001"
```

### 2. 配置SSL/TLS

```bash
# 准备证书
mkdir -p ~/.minio/certs
cp public.crt ~/.minio/certs/
cp private.key ~/.minio/certs/

# 重启MinIO
```

### 3. 使用持久化存储

```yaml
volumes:
  - /data/minio:/data  # 使用绝对路径，确保数据持久化
```

### 4. 配置反向代理（Nginx）

```nginx
upstream minio {
    server localhost:9000;
}

upstream minio_console {
    server localhost:9001;
}

server {
    listen 80;
    server_name minio.example.com;

    location / {
        proxy_pass http://minio;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

server {
    listen 80;
    server_name console.minio.example.com;

    location / {
        proxy_pass http://minio_console;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 5. 设置备份

```bash
# 定期备份数据目录
tar -czf minio-backup-$(date +%Y%m%d).tar.gz ~/minio/data

# 或使用mc mirror命令同步到另一个MinIO
mc mirror myminio/reports remote-minio/reports-backup
```

## 常见问题

### 1. 无法连接到MinIO

**检查服务是否运行：**
```bash
docker ps | grep minio
```

**检查端口是否占用：**
```bash
lsof -i :9000
lsof -i :9001
```

### 2. Access Denied错误

**检查bucket权限：**
```bash
mc anonymous get myminio/reports
```

确保是private模式（使用预签名URL访问）。

### 3. 预签名URL无法访问

**检查配置：**
- `private_storage = true`
- `endpoint` 必须是可访问的地址（如果是Docker容器，不能用localhost）

**Docker部署注意**：
如果应用和MinIO都在Docker中，endpoint应该使用容器名：
```toml
endpoint = "http://minio:9000"  # 使用容器名而不是localhost
```

### 4. 文件上传后找不到

**检查日志：**
```bash
docker logs minio
```

**验证文件是否存在：**
```bash
mc ls myminio/reports/reports/
```

## 性能优化

### 1. 启用多磁盘

```bash
# 使用多个磁盘提高性能
minio server /data1 /data2 /data3 /data4
```

### 2. 配置内存限制

```yaml
services:
  minio:
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 1G
```

### 3. 启用分布式模式

```bash
# 4个节点的分布式部署
minio server http://host{1...4}/export/set{1...4}
```

## 监控

### Prometheus指标

MinIO提供Prometheus指标：

```bash
curl http://localhost:9000/minio/v2/metrics/cluster
```

### 查看服务器信息

```bash
mc admin info myminio
```

## 迁移到MinIO

### 从OSS/S3迁移

使用mc工具：

```bash
# 从阿里云OSS迁移
mc mirror aliyun-oss/openmanus-reports myminio/reports

# 从AWS S3迁移
mc mirror aws-s3/openmanus-reports myminio/reports
```

### 数据库无需修改

数据库中存储的是文件路径和UUID，切换存储后端不影响数据库。

## 总结

MinIO提供了：
- ✅ **零成本**：完全免费开源
- ✅ **易部署**：Docker一键启动
- ✅ **S3兼容**：支持所有S3 API
- ✅ **高性能**：比公有云更快的本地访问
- ✅ **完全掌控**：数据完全在自己手中
- ✅ **Web界面**：友好的管理控制台

非常适合开发、测试和私有化部署！
