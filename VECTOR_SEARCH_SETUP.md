# 向量检索设置指南

本文档说明如何启用和使用向量检索功能。

## 功能概述

向量检索系统提供：
- **语义搜索**：理解查询意图，而不仅仅是关键词匹配
- **混合检索**：结合 BM25（关键词）和向量（语义）检索
- **RRF 融合**：使用 Reciprocal Rank Fusion 算法融合多个检索结果
- **智能降级**：向量检索失败时自动降级到 BM25 搜索

## 架构说明

```
用户查询
    ↓
混合检索器 (HybridRetriever)
    ↓
    ├─→ BM25 检索 (Meilisearch)
    │   └─→ 关键词匹配结果
    │
    └─→ 向量检索 (pgvector)
        └─→ 语义相似度结果
    ↓
RRF 融合算法
    ↓
最终排序结果
```

## 前置要求

1. **PostgreSQL 11+** 支持 pgvector 扩展
2. **Qwen API Key** 用于生成 embeddings
3. **足够的数据库存储空间** (每个块约 6KB embedding 数据)

## 安装步骤

### 1. 添加向量支持到数据库

运行迁移脚本：

```bash
python scripts/add_vector_support.py
```

此脚本将：
- ✅ 启用 `pgvector` 扩展
- ✅ 添加 `embedding vector(1536)` 列到 `block_versions` 表
- ✅ 创建 HNSW 索引用于快速向量搜索

### 2. 为现有文档生成 embeddings

如果你已经有文档数据，需要重新生成 embeddings：

```bash
# 为所有文档生成 embeddings
python scripts/regenerate_embeddings.py

# 或者只为特定文档生成
python scripts/regenerate_embeddings.py <doc_id>
```

**注意**：
- 生成 embeddings 需要调用 Qwen API，可能需要一些时间
- 建议在低峰期运行
- 脚本会自动批量处理（每批 50 个块）

### 3. 验证安装

检查数据库：

```sql
-- 检查 pgvector 扩展
SELECT * FROM pg_extension WHERE extname = 'vector';

-- 检查 embedding 列
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'block_versions' 
AND column_name = 'embedding';

-- 检查 HNSW 索引
SELECT indexname 
FROM pg_indexes 
WHERE tablename = 'block_versions' 
AND indexname = 'idx_block_versions_embedding';

-- 检查已生成的 embeddings 数量
SELECT COUNT(*) 
FROM block_versions 
WHERE embedding IS NOT NULL;
```

## 使用方法

### 自动启用

向量检索已集成到系统中，无需额外配置。系统会自动：

1. **上传文档时**：自动生成 embeddings
2. **搜索时**：自动使用混合检索（BM25 + 向量）
3. **失败时**：自动降级到 BM25 搜索

### 手动控制

如果需要禁用向量检索：

```python
from app.services.retriever import HybridRetriever

# 只使用 BM25
retriever = HybridRetriever(db, use_meilisearch=True, use_vector=False)

# 只使用向量检索
retriever = HybridRetriever(db, use_meilisearch=False, use_vector=True)

# 使用混合检索（默认）
retriever = HybridRetriever(db, use_meilisearch=True, use_vector=True)
```

## 性能优化

### HNSW 索引参数

默认使用 `vector_cosine_ops`，适合大多数场景。如需调整：

```sql
-- 删除旧索引
DROP INDEX idx_block_versions_embedding;

-- 创建新索引（调整参数）
CREATE INDEX idx_block_versions_embedding 
ON block_versions 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

参数说明：
- `m`：每个节点的连接数（默认 16，范围 2-100）
- `ef_construction`：构建时的搜索深度（默认 64，范围 4-1000）
- 更大的值 = 更好的召回率，但更慢的构建和更大的索引

### 查询性能

调整查询时的搜索深度：

```sql
-- 设置会话级别参数
SET hnsw.ef_search = 100;  -- 默认 40

-- 然后执行查询
SELECT * FROM block_versions 
ORDER BY embedding <=> '[...]'::vector 
LIMIT 10;
```

### 批量生成优化

修改 `app/services/embedding.py` 中的批量大小：

```python
# 默认每批 50 个
embeddings = embedding_service.generate_embeddings_batch(texts, batch_size=100)
```

## 监控和维护

### 检查 embedding 覆盖率

```sql
-- 总块数
SELECT COUNT(*) as total_blocks FROM block_versions;

-- 有 embedding 的块数
SELECT COUNT(*) as embedded_blocks 
FROM block_versions 
WHERE embedding IS NOT NULL;

-- 覆盖率
SELECT 
    COUNT(*) FILTER (WHERE embedding IS NOT NULL) * 100.0 / COUNT(*) as coverage_percent
FROM block_versions;
```

### 索引大小

```sql
-- 查看索引大小
SELECT 
    schemaname,
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size
FROM pg_stat_user_indexes
WHERE indexname = 'idx_block_versions_embedding';
```

### 重建索引

如果索引损坏或性能下降：

```sql
-- 重建索引
REINDEX INDEX idx_block_versions_embedding;
```

## 故障排除

### 问题 1: pgvector 扩展安装失败

**错误**: `ERROR: could not open extension control file`

**解决**:
```bash
# Ubuntu/Debian
sudo apt-get install postgresql-15-pgvector

# macOS (Homebrew)
brew install pgvector

# 或从源码编译
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
```

### 问题 2: Embedding 生成失败

**错误**: `Embedding 生成失败: API key invalid`

**解决**:
1. 检查 `.env` 文件中的 `QWEN_API_KEY`
2. 确认 API key 有效且有足够配额
3. 检查网络连接

### 问题 3: 向量搜索返回空结果

**可能原因**:
1. Embeddings 未生成 → 运行 `regenerate_embeddings.py`
2. 索引未创建 → 运行 `add_vector_support.py`
3. 查询向量生成失败 → 检查 API key

**调试**:
```python
# 检查是否使用了向量检索
retriever = HybridRetriever(db)
results = retriever.search("测试查询", doc_id, rev_id)

# 查看日志
# 应该看到 "混合检索" 或 "向量检索" 相关日志
```

### 问题 4: 性能慢

**优化建议**:
1. 调整 HNSW 索引参数（见上文）
2. 增加 `hnsw.ef_search` 值
3. 使用更小的 `top_k` 值
4. 考虑使用缓存

## RRF 算法说明

Reciprocal Rank Fusion (RRF) 用于融合多个检索结果：

```
RRF(d) = Σ 1 / (k + rank(d))
```

其中：
- `d` 是文档
- `k` 是常数（默认 60）
- `rank(d)` 是文档在列表中的排名

**优点**:
- 不需要归一化分数
- 对不同检索系统的分数尺度不敏感
- 简单高效

**调整 k 值**:
```python
# 在 retriever.py 中
combined = self._reciprocal_rank_fusion(
    [bm25_results, vector_results],
    k=60  # 增大 k 会降低排名的影响
)
```

## 成本估算

### 存储成本

每个块的 embedding：
- 维度：1536 (float32)
- 大小：1536 × 4 bytes = 6KB
- 1000 个块 ≈ 6MB
- 10000 个块 ≈ 60MB

### API 成本

Qwen embedding API（假设）：
- 价格：约 ¥0.0001/1K tokens
- 平均每块 200 tokens
- 1000 个块 ≈ ¥0.02

## 最佳实践

1. **增量更新**：只为新增/修改的块生成 embeddings
2. **批量处理**：使用批量 API 降低成本
3. **缓存结果**：缓存常见查询的结果
4. **监控覆盖率**：定期检查 embedding 覆盖率
5. **定期维护**：定期重建索引以保持性能

## 参考资料

- [pgvector 文档](https://github.com/pgvector/pgvector)
- [HNSW 算法论文](https://arxiv.org/abs/1603.09320)
- [RRF 算法论文](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
