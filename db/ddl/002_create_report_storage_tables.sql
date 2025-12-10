-- 报告文件存储功能的数据库DDL
-- 需求：MySQL 8.0+, InnoDB, utf8mb4

-- =============================
-- 1. 报告文件元数据表
-- =============================
CREATE TABLE IF NOT EXISTS report_files (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    uuid VARCHAR(36) UNIQUE NOT NULL COMMENT '文件唯一标识',
    original_filename VARCHAR(255) NOT NULL COMMENT '原始文件名',
    file_size BIGINT NOT NULL COMMENT '文件大小(字节)',
    storage_key VARCHAR(500) NOT NULL COMMENT '存储路径key',
    storage_type VARCHAR(50) DEFAULT 'oss' NOT NULL COMMENT '存储类型',
    content_type VARCHAR(100) DEFAULT 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' NOT NULL COMMENT 'MIME类型',
    created_by VARCHAR(100) COMMENT '创建用户',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '创建时间',
    expires_at TIMESTAMP NULL COMMENT '过期时间',
    download_count INT DEFAULT 0 NOT NULL COMMENT '下载次数',
    status ENUM('active', 'expired', 'deleted') DEFAULT 'active' NOT NULL COMMENT '状态',
    metadata JSON COMMENT '扩展元数据',

    INDEX idx_uuid (uuid),
    INDEX idx_created_by (created_by),
    INDEX idx_created_at (created_at),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='报告文件元数据表';

-- =============================
-- 2. 文件访问日志表
-- =============================
CREATE TABLE IF NOT EXISTS file_access_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    file_uuid VARCHAR(36) NOT NULL COMMENT '文件UUID',
    user_id VARCHAR(100) COMMENT '访问用户',
    access_type ENUM('preview', 'download') NOT NULL COMMENT '访问类型',
    access_ip VARCHAR(45) COMMENT '访问IP',
    user_agent TEXT COMMENT '用户代理',
    presign_url VARCHAR(1000) COMMENT '临时URL',
    expire_at TIMESTAMP NULL COMMENT '过期时间',
    access_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL COMMENT '访问时间',

    INDEX idx_file_uuid (file_uuid),
    INDEX idx_user_id (user_id),
    INDEX idx_access_at (access_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文件访问日志表';
