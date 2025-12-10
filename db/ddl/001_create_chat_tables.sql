-- Chat data core tables DDL
-- MySQL 8.0+ / InnoDB / utf8mb4

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- conversations
CREATE TABLE IF NOT EXISTS conversations (
  id               VARCHAR(36)   NOT NULL PRIMARY KEY,
  app_id           VARCHAR(64)   NOT NULL,
  name             VARCHAR(255)  NOT NULL,
  status           ENUM('normal','archived','deleted') NOT NULL DEFAULT 'normal',
  inputs           JSON          NOT NULL,
  from_end_user_id VARCHAR(64)   NOT NULL,
  from_source      VARCHAR(32)   NOT NULL DEFAULT 'api',
  mode             VARCHAR(32)   NOT NULL DEFAULT 'chat',
  dialogue_count   INT           NOT NULL DEFAULT 0,
  created_at       TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_conv_app_created (app_id, created_at),
  KEY idx_conv_user_created (from_end_user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- messages
CREATE TABLE IF NOT EXISTS messages (
  id                        VARCHAR(36)  NOT NULL PRIMARY KEY,
  conversation_id           VARCHAR(36)  NOT NULL,
  app_id                    VARCHAR(64)  NOT NULL,
  model_provider            VARCHAR(64)  NOT NULL,
  model_id                  VARCHAR(128) NOT NULL,
  inputs                    JSON         NOT NULL,
  query                     LONGTEXT     NOT NULL,
  message                   JSON         NULL,
  message_tokens            INT          NOT NULL DEFAULT 0,
  answer                    LONGTEXT     NOT NULL,
  answer_tokens             INT          NOT NULL DEFAULT 0,
  provider_response_latency DECIMAL(10,3) NOT NULL DEFAULT 0.000,
  total_price               DECIMAL(18,6) NOT NULL DEFAULT 0.000000,
  message_unit_price        DECIMAL(18,6) NOT NULL DEFAULT 0.000000,
  answer_unit_price         DECIMAL(18,6) NOT NULL DEFAULT 0.000000,
  from_source               VARCHAR(32)   NOT NULL DEFAULT 'api',
  currency                  VARCHAR(8)   NOT NULL DEFAULT 'USD',
  status                    ENUM('normal','error') NOT NULL DEFAULT 'normal',
  error                     TEXT         NULL,
  message_metadata          JSON         NULL,
  created_at                TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at                TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_msg_conv FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
  KEY idx_msg_conv_created (conversation_id, created_at),
  -- removed client_message_id for remote DB compatibility
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- message_files
CREATE TABLE IF NOT EXISTS message_files (
  id              VARCHAR(36)  NOT NULL PRIMARY KEY,
  message_id      VARCHAR(36)  NOT NULL,
  type            ENUM('document','image','audio','video','other') NOT NULL DEFAULT 'document',
  transfer_method ENUM('local_file','remote_url') NOT NULL DEFAULT 'local_file',
  url             VARCHAR(2048) NOT NULL,
  belongs_to      ENUM('user','assistant','system') NOT NULL DEFAULT 'user',
  upload_file_id  VARCHAR(128) NULL,
  created_by_role ENUM('end_user','assistant','system') NOT NULL DEFAULT 'end_user',
  created_by      VARCHAR(64)  NOT NULL,
  created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_file_msg FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
  KEY idx_file_msg (message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET FOREIGN_KEY_CHECKS = 1;
