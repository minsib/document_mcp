# 向量检索启用清单

## 快速启用指南

按照以下步骤启用向量检索功能：

### ✅ 前置检查

- [ ] PostgreSQL 11+ 已安装
- [ ] 数据库正在运行
- [ ] Qwen API Key 已配置在 `.env` 文件中
- [ ] 系统已正常运行（可以上传和编辑文档）

### 📝 启用步骤

#### 1. 添加向量支持到数据库

```bash
python scripts/add_vector_support.py
```

**预期输出**:
```
🔧 开始添加向量搜索支持...
1️⃣ 启用 pgvector 扩展...
✅ pgvector 扩展已启用
2️⃣ 添加 embedding 列到 block_versions 表...
✅ embedding 列已添加
3️⃣ 创建 HNSW 索引（这可能需要几分钟）...
✅ HNSW 索引已创建

🎉 向量搜索支持添加完成！
```

**如果失败**:
- 检查 PostgreSQL 是否支持 pgvector 扩展
- 参考 `VECTOR_SEARCH_SETUP.md` 的故障排除部分

#### 2. 为现有文档生成 Embeddings（可选）

如果你已经有文档数据：

```bash
# 为所有文档生成
python scripts/regenerate_embeddings.py

# 或只为特定文档生成
python scripts/regenerate_embeddings.py <doc_id>
```

**预期输出**:
```
📚 找到 X 个文档需要处理

🔄 处理文档: 测试文档 (uuid)
   找到 Y 个块
   🤖 生成 embeddings...
   💾 保存到数据库...
   ✅ 完成 Y 个 embeddings

🎉 所有文档处理完成！
```

**注意**:
- 这个过程需要调用 Qwen API，可能需要几分钟
- 建议在低峰期运行
- 新上传的文档会自动生成 embeddings，无需手动运行

#### 3. 验证安装

```bash
# 检查 pgvector 扩展
psql -h localhost -p 5435 -U postgres -d document_edit -c "SELECT * FROM pg_extension WHERE extname = 'vector';"

# 检查 embedding 列
psql -h localhost -p 5435 -U postgres -d document_edit -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'block_versions' AND column_name = 'embedding';"

# 检查 HNSW 索引
psql -h localhost -p 5435 -U postgres -d document_edit -c "SELECT indexname FROM pg_indexes WHERE tablename = 'block_versions' AND indexname = 'idx_block_versions_embedding';"

# 检查已生成的 embeddings 数量
psql -h localhost -p 5435 -U postgres -d document_edit -c "SELECT COUNT(*) as embedded_blocks FROM block_versions WHERE embedding IS NOT NULL;"
```

**预期结果**:
- pgvector 扩展存在
- embedding 列类型为 `USER-DEFINED` (vector)
- HNSW 索引存在
- embedded_blocks > 0（如果有文档）

#### 4. 测试向量检索

```bash
python test_vector_search.py
```

**预期输出**:
```
🧪 测试向量检索功能

1️⃣ 上传测试文档...
✅ 文档已上传: <doc_id>

2️⃣ 等待 embeddings 生成（约 5-10 秒）...
✅ 完成

3️⃣ 测试语义搜索...

   测试 1: 关于项目背景的内容
   期望: 应该找到项目背景相关段落
   ✅ 找到 X 个候选:
      1. [项目背景] ...
      2. [系统概述] ...

4️⃣ 测试完成！
```

**验证要点**:
- 能找到语义相关的段落（即使关键词不完全匹配）
- 查看 API 日志中是否有 "混合检索" 相关信息

### 🎯 完成检查

- [ ] pgvector 扩展已启用
- [ ] embedding 列已添加
- [ ] HNSW 索引已创建
- [ ] 现有文档的 embeddings 已生成（如果有）
- [ ] 测试通过，能找到语义相关的内容

### 📊 监控指标

启用后，定期检查以下指标：

```bash
# Embedding 覆盖率
psql -h localhost -p 5435 -U postgres -d document_edit -c "SELECT COUNT(*) FILTER (WHERE embedding IS NOT NULL) * 100.0 / COUNT(*) as coverage_percent FROM block_versions;"

# 索引大小
psql -h localhost -p 5435 -U postgres -d document_edit -c "SELECT pg_size_pretty(pg_relation_size('idx_block_versions_embedding')) as index_size;"
```

**目标**:
- 覆盖率 > 95%
- 索引大小合理（约 6KB/块）

### 🔧 故障排除

#### 问题 1: pgvector 扩展安装失败

```bash
# Ubuntu/Debian
sudo apt-get install postgresql-15-pgvector

# macOS (Homebrew)
brew install pgvector
```

#### 问题 2: Embedding 生成失败

检查：
1. `.env` 文件中的 `QWEN_API_KEY` 是否正确
2. API key 是否有足够配额
3. 网络连接是否正常

#### 问题 3: 向量搜索返回空结果

可能原因：
1. Embeddings 未生成 → 运行 `regenerate_embeddings.py`
2. 索引未创建 → 运行 `add_vector_support.py`
3. 查询向量生成失败 → 检查 API key

### 📚 更多信息

- 详细设置指南: `VECTOR_SEARCH_SETUP.md`
- 实现总结: `VECTOR_SEARCH_IMPLEMENTATION.md`
- 功能对照表: `FEATURE_COMPARISON.md`

### 💡 提示

1. **新文档自动处理**: 上传新文档时会自动生成 embeddings，无需手动干预
2. **降级策略**: 即使向量检索失败，系统也会自动降级到 BM25 搜索
3. **性能优化**: 参考 `VECTOR_SEARCH_SETUP.md` 的性能优化部分
4. **成本控制**: 每 1000 个块约需 ¥0.02 API 费用 + 6MB 存储

### 🎉 完成！

向量检索已启用，系统现在支持：
- ✅ 语义搜索（理解查询意图）
- ✅ 混合检索（BM25 + 向量）
- ✅ RRF 融合（最优排序）
- ✅ 智能降级（确保稳定性）

**预期效果**:
- 定位准确率提升：85% → 90%+
- 支持模糊查询和语义理解
- 更好的用户体验
