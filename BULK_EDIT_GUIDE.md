# 批量修改功能指南

## 功能概述

批量修改功能允许用户一次性修改文档中的多处内容，支持：
- **精确词替换**：将所有"旧词"替换为"新词"
- **正则表达式替换**：使用正则表达式匹配和替换
- **范围限制**：限制在特定章节或块类型中修改
- **预览确认**：修改前预览所有变更，确认后执行

## 使用场景

1. **统一术语**：将文档中的旧术语统一替换为新术语
2. **格式规范**：批量修改格式不一致的内容
3. **错误修正**：批量修正重复出现的错误
4. **版本更新**：批量更新版本号、日期等信息

## API 接口

### 1. 发起批量修改

**端点**: `POST /v1/chat/bulk-edit`

**请求格式**:
```json
{
  "session_id": "uuid",
  "doc_id": "uuid",
  "message": "将所有'旧词'替换为'新词'",
  "match_type": "exact_term",
  "scope_filter": {
    "term": "旧词",
    "replacement": "新词",
    "heading": "可选：限制在某个章节",
    "block_type": "可选：限制块类型（paragraph/heading/list）"
  }
}
```

**match_type 选项**:
- `exact_term`: 精确词匹配（默认）
- `regex`: 正则表达式匹配
- `semantic`: 语义匹配（暂未实现）

**响应格式**:
```json
{
  "status": "need_confirm",
  "message": "将修改 5 处内容，请确认",
  "preview": {
    "diffs": [
      {
        "block_id": "uuid",
        "op_type": "replace",
        "before_snippet": "这是第一段内容，包含旧词。",
        "after_snippet": "这是第一段内容，包含新词。",
        "heading_context": "第一章",
        "char_diff": 0
      }
    ],
    "total_changes": 5,
    "estimated_impact": "medium",
    "grouped_by_heading": {
      "第一章": 2,
      "第二章": 3
    },
    "total_chars_added": 0,
    "total_chars_removed": 0
  },
  "confirm_token": "uuid",
  "preview_hash": "hash"
}
```

### 2. 确认批量修改

**端点**: `POST /v1/chat/bulk-confirm`

**请求格式**:
```json
{
  "session_id": "uuid",
  "doc_id": "uuid",
  "confirm_token": "uuid",
  "preview_hash": "hash",
  "action": "apply"
}
```

**action 选项**:
- `apply`: 应用修改
- `cancel`: 取消修改

**响应格式**:
```json
{
  "status": "applied",
  "message": "已成功修改 5 处内容",
  "new_rev_id": "uuid",
  "new_rev_no": 2,
  "new_version": 2,
  "changes_applied": 5
}
```

## 使用示例

### 示例 1: 精确词替换

```python
import requests

API_BASE = "http://localhost:8001"

# 1. 发起批量修改
response = requests.post(
    f"{API_BASE}/v1/chat/bulk-edit",
    json={
        "session_id": session_id,
        "doc_id": doc_id,
        "message": "将所有'旧词'替换为'新词'",
        "match_type": "exact_term",
        "scope_filter": {
            "term": "旧词",
            "replacement": "新词"
        }
    }
)

result = response.json()
print(f"将修改 {result['preview']['total_changes']} 处内容")

# 2. 确认修改
confirm_response = requests.post(
    f"{API_BASE}/v1/chat/bulk-confirm",
    json={
        "session_id": session_id,
        "doc_id": doc_id,
        "confirm_token": result['confirm_token'],
        "preview_hash": result['preview_hash'],
        "action": "apply"
    }
)

print(confirm_response.json()['message'])
```

### 示例 2: 限制在特定章节

```python
# 只在"第一章"中替换
response = requests.post(
    f"{API_BASE}/v1/chat/bulk-edit",
    json={
        "session_id": session_id,
        "doc_id": doc_id,
        "message": "在第一章中将'关键词'替换为'新关键词'",
        "match_type": "exact_term",
        "scope_filter": {
            "term": "关键词",
            "replacement": "新关键词",
            "heading": "第一章"
        }
    }
)
```

### 示例 3: 正则表达式替换

```python
# 将所有日期格式从 YYYY-MM-DD 改为 YYYY/MM/DD
response = requests.post(
    f"{API_BASE}/v1/chat/bulk-edit",
    json={
        "session_id": session_id,
        "doc_id": doc_id,
        "message": "将日期格式改为斜杠分隔",
        "match_type": "regex",
        "scope_filter": {
            "pattern": r"(\d{4})-(\d{2})-(\d{2})",
            "replacement": r"\1/\2/\3"
        }
    }
)
```

### 示例 4: 限制块类型

```python
# 只在段落中替换（不修改标题）
response = requests.post(
    f"{API_BASE}/v1/chat/bulk-edit",
    json={
        "session_id": session_id,
        "doc_id": doc_id,
        "message": "在段落中替换术语",
        "match_type": "exact_term",
        "scope_filter": {
            "term": "旧术语",
            "replacement": "新术语",
            "block_type": "paragraph"
        }
    }
)
```

## 安全机制

### 1. 数量限制

- 默认最多修改 100 处内容
- 超过限制会返回错误，提示缩小范围

### 2. 预览确认

- 所有批量修改都需要预览确认
- 显示每处修改的前后对比
- 按章节分组统计

### 3. 版本控制

- 每次批量修改创建新版本
- 支持回滚到任意历史版本
- 完整的审计日志

### 4. 三重校验

- **preview_hash**: 确保预览内容未被篡改
- **confirm_token**: 防止重放攻击
- **version**: 防止并发冲突

### 5. 超时保护

- confirm_token 有效期 15 分钟
- 超时后需要重新发起批量修改

## 工作流程

```
用户发起批量修改
  ↓
批量发现节点 (BulkDiscoverNode)
  ├─ 使用 Meilisearch 搜索
  ├─ 按 scope_filter 过滤
  └─ 限制最大数量
  ↓
批量预览节点 (BulkPreviewNode)
  ├─ 生成每处修改的 diff
  ├─ 按章节分组统计
  └─ 评估影响等级
  ↓
生成 confirm_token
  ├─ 计算 preview_hash
  ├─ 存储到 Redis（15 分钟）
  └─ 返回预览给用户
  ↓
用户确认
  ↓
批量应用节点 (BulkApplyNode)
  ├─ 验证 token 和 hash
  ├─ 检查版本冲突
  ├─ 创建新 revision
  ├─ 应用所有修改
  ├─ 写入审计日志
  └─ 更新 active_revision
  ↓
重新索引（Meilisearch + Embeddings）
  ↓
返回结果
```

## 性能考虑

### 1. 搜索性能

- 使用 Meilisearch 加速搜索
- 支持分页拉取（每次 100 个）
- 最多召回 1000 个候选

### 2. 预览生成

- 只生成前 200 字符的 snippet
- 按需计算字符变化
- 轻量级 diff 生成

### 3. 应用性能

- 批量插入新 block_versions
- 单次事务提交
- 异步重新索引

### 4. 缓存策略

- confirm_token 存储在 Redis
- 15 分钟自动过期
- 使用后立即删除

## 错误处理

### 1. 超过数量限制

```json
{
  "status": "error",
  "message": "将影响 150 处，超过限制 100，请缩小范围"
}
```

**解决方案**:
- 添加 heading 限制
- 添加 block_type 限制
- 使用更精确的匹配词

### 2. 未找到匹配

```json
{
  "status": "no_matches",
  "message": "未找到匹配的内容",
  "candidates": []
}
```

**解决方案**:
- 检查匹配词是否正确
- 检查 scope_filter 是否过于严格
- 尝试使用更宽松的匹配条件

### 3. 版本冲突

```json
{
  "status": "error",
  "message": "文档版本已变更，预览已失效"
}
```

**解决方案**:
- 重新发起批量修改
- 获取最新的预览

### 4. Token 过期

```json
{
  "status": "error",
  "message": "确认令牌无效或已过期"
}
```

**解决方案**:
- 重新发起批量修改
- 在 15 分钟内完成确认

## 最佳实践

### 1. 先小范围测试

```python
# 先在一个章节中测试
response = requests.post(
    f"{API_BASE}/v1/chat/bulk-edit",
    json={
        "scope_filter": {
            "term": "测试词",
            "replacement": "新词",
            "heading": "第一章"  # 限制范围
        }
    }
)

# 确认无误后再全文替换
```

### 2. 仔细检查预览

```python
result = response.json()
preview = result['preview']

# 检查修改数量
print(f"总修改数: {preview['total_changes']}")

# 检查按章节分组
for heading, count in preview['grouped_by_heading'].items():
    print(f"{heading}: {count} 处")

# 检查前几处修改
for diff in preview['diffs'][:5]:
    print(f"修改前: {diff['before_snippet']}")
    print(f"修改后: {diff['after_snippet']}")
```

### 3. 使用正则表达式时要小心

```python
# 测试正则表达式
import re

pattern = r"(\d{4})-(\d{2})-(\d{2})"
test_text = "日期是 2024-01-22"

# 先在本地测试
result = re.sub(pattern, r"\1/\2/\3", test_text)
print(result)  # 日期是 2024/01/22

# 确认无误后再使用
```

### 4. 保留历史版本

```python
# 批量修改前，记录当前版本号
current_rev = get_current_revision(doc_id)

# 执行批量修改
apply_bulk_edit(...)

# 如果需要回滚
rollback_to_revision(doc_id, current_rev)
```

## 监控指标

### 1. 业务指标

- 批量修改请求数
- 平均修改数量
- 确认率（apply / total）
- 取消率（cancel / total）

### 2. 性能指标

- 发现阶段耗时
- 预览生成耗时
- 应用修改耗时
- 重新索引耗时

### 3. 错误指标

- 超过数量限制次数
- 版本冲突次数
- Token 过期次数
- 正则表达式错误次数

## 测试

运行测试脚本：

```bash
python test_bulk_edit.py
```

测试内容：
- ✅ 精确词替换
- ✅ 范围限制（按章节）
- ✅ 预览生成
- ✅ 确认应用
- ✅ 版本管理
- ✅ 导出验证

## 常见问题

### Q: 批量修改会影响格式吗？

A: 不会。批量修改只替换文本内容，保留原有的 Markdown 格式。

### Q: 可以撤销批量修改吗？

A: 可以。使用版本回滚功能回滚到修改前的版本。

### Q: 批量修改有数量限制吗？

A: 有。默认最多修改 100 处内容，可以通过添加范围限制来减少匹配数量。

### Q: 正则表达式支持哪些语法？

A: 支持 Python re 模块的所有语法，包括捕获组、前后断言等。

### Q: 批量修改会生成 embeddings 吗？

A: 会。应用修改后会自动重新生成受影响块的 embeddings。

## 参考资料

- [API 文档](README.md)
- [版本管理](README.md#版本管理)
- [测试脚本](test_bulk_edit.py)
