-- 报告文件存储功能的SQLite数据库DDL
-- 需求：SQLite 3.9+ (支持JSON)

-- =============================
-- 1. 报告文件元数据表
-- =============================
CREATE TABLE IF NOT EXISTS report_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    original_filename TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    storage_key TEXT NOT NULL,
    storage_type TEXT DEFAULT 'oss' NOT NULL,
    content_type TEXT DEFAULT 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' NOT NULL,
    created_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at DATETIME,
    download_count INTEGER DEFAULT 0 NOT NULL,
    status TEXT DEFAULT 'active' NOT NULL CHECK(status IN ('active', 'expired', 'deleted')),
    extra_metadata TEXT  -- JSON data stored as TEXT (renamed from 'metadata' to avoid SQLAlchemy conflicts)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_report_files_uuid ON report_files(uuid);
CREATE INDEX IF NOT EXISTS idx_report_files_created_by ON report_files(created_by);
CREATE INDEX IF NOT EXISTS idx_report_files_created_at ON report_files(created_at);
CREATE INDEX IF NOT EXISTS idx_report_files_status ON report_files(status);

-- =============================
-- 2. 文件访问日志表
-- =============================
CREATE TABLE IF NOT EXISTS file_access_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_uuid TEXT NOT NULL,
    user_id TEXT,
    access_type TEXT NOT NULL CHECK(access_type IN ('preview', 'download')),
    access_ip TEXT,
    user_agent TEXT,
    presign_url TEXT,
    expire_at DATETIME,
    access_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_file_access_logs_file_uuid ON file_access_logs(file_uuid);
CREATE INDEX IF NOT EXISTS idx_file_access_logs_user_id ON file_access_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_file_access_logs_access_at ON file_access_logs(access_at);
