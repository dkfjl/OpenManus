# Chat Tables DDL

This folder contains MySQL DDL for the chat data insertion feature.

## Prerequisites

- MySQL 8.0+
- InnoDB, `utf8mb4`

## Tables

- `conversations`
  - Keys: `idx_conv_app_created (app_id, created_at)`, `idx_conv_user_created (from_end_user_id, created_at)`
- `messages`
  - Foreign key → `conversations(id)` (CASCADE)
  - Keys: `idx_msg_conv_created (conversation_id, created_at)`
  - Unique: `ux_msg_conv_client (conversation_id, client_message_id)`
- `message_files`
  - Foreign key → `messages(id)` (CASCADE)
  - Key: `idx_file_msg (message_id)`

## Apply DDL

```bash
mysql -h <host> -u <user> -p<password> <database> < db/ddl/001_create_chat_tables.sql
```

> Note: No data migration is performed. The script is idempotent.

