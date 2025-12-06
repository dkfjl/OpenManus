# Dify 知识库测试 - 快速开始

欢迎使用 Dify 知识库集成测试！本文档将帮助您快速开始测试。

## 🚀 快速开始（3 分钟）

### 步骤 1: 配置 Dify

编辑 `config/config.toml`，添加以下内容：

```toml
[dify]
api_base = "https://api.dify.ai/v1"
api_key = "your_actual_api_key_here"      # 替换为您的实际 API Key
dataset_id = "your_dataset_id_here"       # 替换为您的数据集 ID（可选）
retrieval_model = "search"
score_threshold = 0.5
top_k = 3
timeout = 5
max_retries = 3
```

### 步骤 2: 运行快速测试

```bash
# 快速测试连接
python tests/manual/test_dify_connection.py

# 如果连接成功，运行完整测试套件
python tests/manual/run_all_tests.py
```

### 步骤 3: 查看结果

测试完成后会在当前目录生成测试报告 `test_report_YYYYMMDD_HHMMSS.txt`

---

## 📚 详细测试指南

完整的测试指南和故障排查请参考: [DIFY_TEST_GUIDE.md](DIFY_TEST_GUIDE.md)

## 🧪 单独运行测试

如果您只想运行特定的测试：

```bash
# 测试 1: 基本连接
python tests/manual/test_dify_connection.py

# 测试 2: 工具功能
python tests/manual/test_dify_tool.py

# 测试 3: Agent 集成
python tests/manual/test_manus_integration.py

# 测试 4: 性能测试
python tests/manual/test_dify_performance.py
```

## ✅ 测试通过标准

所有测试通过后，您应该看到：

- ✅ 可以成功连接到 Dify API
- ✅ 能检索到知识库中的内容
- ✅ 工具输出格式正确
- ✅ 工具已注册到 Manus Agent
- ✅ 平均响应时间 < 2 秒
- ✅ 支持并发请求

## ❌ 常见问题

### "Knowledge base configuration is not properly set"
**解决**: 检查 `config/config.toml` 中是否有 `[dify]` 配置段，且 `api_key` 不为空

### "Dify API error 401"
**解决**: API Key 无效，请在 Dify 平台重新生成

### "Connection to knowledge base timed out"
**解决**: 检查网络连接，或增加 `timeout` 配置值

### "知识库中未找到相关信息"
**解决**:
1. 确认知识库中有测试数据
2. 尝试不同的查询关键词
3. 降低 `score_threshold` 值（如改为 0.3）

更多问题请参考: [DIFY_TEST_GUIDE.md](DIFY_TEST_GUIDE.md#故障排查)

## 📞 获取帮助

- 详细测试指南: [DIFY_TEST_GUIDE.md](DIFY_TEST_GUIDE.md)
- 实施计划: [implementation_plan.md](implementation_plan.md)
- 测试脚本说明: [tests/manual/README.md](tests/manual/README.md)

---

**祝测试顺利！** 🎉
