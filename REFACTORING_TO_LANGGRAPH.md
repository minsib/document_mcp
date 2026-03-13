# 项目重构规划：迁移到 LangGraph + DeepAgents 架构

## 📋 文档概述

**文档版本**: v1.0  
**创建日期**: 2026-01-26  
**目标**: 将现有的固定工作流架构重构为基于 LangGraph 的智能体架构  
**预期收益**: 提升系统灵活性、可维护性和智能化水平

---

## 🎯 重构目标

### 1. 核心目标
- **架构现代化**: 采用 LangGraph 状态机管理复杂工作流
- **智能体化**: 引入 DeepAgents 概念，每个节点成为独立的智能体
- **工具化**: 将数据库操作、检索、索引等封装为可复用工具
- **可观测性**: 完整集成 Langfuse 追踪，实现全链路监控
- **可扩展性**: 便于后期添加新功能和智能体

### 2. 技术亮点
- ✨ **LangGraph 状态机**: 声明式工作流定义，支持条件分支和循环
- ✨ **智能体架构**: 每个智能体专注单一职责，可独立优化
- ✨ **工具生态**: 统一的工具接口，支持动态组合
- ✨ **流式输出**: 支持 SSE 实时推送处理进度
- ✨ **人机协同**: 支持人工介入和确认机制

---

## 📊 现状分析

### 当前架构（固定工作流）

```
用户请求
   ↓
IntentParser (意图解析)
   ↓
IntentClarifier (意图澄清)
   ↓
HybridRetriever (混合检索) ← 检索和定位混在一起
   ↓
Verifier (验证选择)
   ↓
EditPlanner (计划生成)
   ↓
PreviewGenerator (预览生成)
   ↓
ApplyEdits (执行修改)
   ↓
返回结果
```

**优点**:
- ✅ 流程清晰，易于理解
- ✅ 性能可预测（2-3 秒）
- ✅ 成本可控（~¥0.02/请求）

**缺点**:
- ❌ 流程固定，难以处理复杂场景
- ❌ 节点间耦合度高
- ❌ 缺乏自适应能力
- ❌ 难以支持多轮对话
- ❌ 工具复用性差
- ❌ **检索和定位职责不清晰** ⭐
- ❌ **缺少完整的位置信息传递** ⭐

### 重构后架构（LangGraph + DeepAgents）

```
用户请求
   ↓
Intent Agent (意图理解) ← 智能体化
   ↓
Router Agent (路由决策) ← 智能路由
   ↓
   ├─→ Clarify Agent (澄清确认) → 返回澄清问题
   │
   └─→ Retrieval Agent (检索定位) ⭐ 新增独立智能体
          ↓
          - 多路检索（BM25 + Vector + Meilisearch）
          - 结果融合和验证
          - 收集完整位置信息（DB + Index + Context）
          ↓
       Edit Agent (编辑执行) ← 接收完整位置信息
          ↓
          - 基于位置信息生成计划
          - 执行数据库操作
          - 更新索引
          ↓
       返回结果
```

**改进点**:
- ✅ **职责分离**: Retrieval Agent 专注检索定位，Edit Agent 专注编辑执行
- ✅ **完整信息**: 传递 DB 位置 + Index 位置 + 上下文
- ✅ **智能路由**: 根据场景动态选择流程
- ✅ **工具化**: 所有操作封装为可复用工具
- ✅ **可扩展**: 轻松添加新智能体和工具

---

## 🏗️ 目标架构（LangGraph + DeepAgents）

### 整体架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                      LangGraph StateGraph                         │
│                                                                    │
│  ┌──────────────┐      ┌──────────────┐      ┌────────────────┐ │
│  │ Intent Agent │─────▶│ Router Agent │─────▶│Retrieval Agent │ │
│  │  (意图理解)  │      │  (路由决策)  │      │  (检索定位)    │ │
│  └──────────────┘      └──────────────┘      └────────────────┘ │
│         │                      │                      │           │
│         │                      ↓                      ↓           │
│         │              ┌──────────────┐      ┌──────────────┐   │
│         │              │Clarify Agent │      │  Edit Agent  │   │
│         │              │  (澄清确认)  │      │  (编辑执行)  │   │
│         │              └──────────────┘      └──────────────┘   │
│         │                                                         │
│         └────────────────┬──────────────────────────────────────┘
│                          ↓                                        │
│                  ┌──────────────┐                                 │
│                  │  Tool Layer  │                                 │
│                  │  (工具层)    │                                 │
│                  └──────────────┘                                 │
└──────────────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┬──────────────────┐
        ↓                 ↓                 ↓                  ↓
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ DB Tools     │  │Search Tools  │  │ LLM Tools    │  │ Index Tools  │
│ (数据库工具) │  │ (检索工具)   │  │ (LLM工具)    │  │ (索引工具)   │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
```

### 核心组件

#### 1. LangGraph StateGraph
- **职责**: 管理整个工作流的状态和流转
- **特性**: 
  - 声明式定义节点和边
  - 支持条件路由
  - 支持循环和重试
  - 内置检查点机制

#### 2. 智能体层（Agents）

##### 2.1 Intent Agent（意图理解智能体）
- **职责**: 理解用户意图，提取关键信息
- **工具**:
  - `llm_parse_intent`: 调用 LLM 解析意图
  - `db_get_document`: 获取文档信息
  - `db_get_revision`: 获取版本信息
- **输出**: Intent 对象（操作类型、目标描述、新内容等）

##### 2.2 Router Agent（路由决策智能体）
- **职责**: 根据意图决定下一步动作
- **决策逻辑**:
  - 意图模糊 → Clarify Agent
  - 意图明确 → Retrieval Agent
- **工具**:
  - `check_ambiguity`: 检测意图模糊性
  - `check_cross_reference`: 检测跨段落引用
  - `check_large_scope`: 检测大范围修改

##### 2.3 Clarify Agent（澄清确认智能体）
- **职责**: 处理模糊意图，请求用户澄清
- **工具**:
  - `llm_generate_clarification`: 生成澄清问题
  - `resolve_cross_reference`: 解析跨段落引用
- **输出**: 澄清问题 + 选项

##### 2.4 Retrieval Agent（检索定位智能体）⭐ 新增
- **职责**: 查找和定位目标块，提供完整的位置信息
- **工具**:
  - `search_hybrid`: 混合检索（BM25 + 向量 + RRF）
  - `search_bm25`: BM25 关键词检索
  - `search_vector`: 向量语义检索
  - `search_meilisearch`: Meilisearch 全文检索
  - `db_get_blocks`: 获取块详细信息
  - `db_get_block_context`: 获取块上下文
  - `llm_verify_target`: 验证目标是否匹配意图
  - `llm_rank_candidates`: 对候选结果重排序
- **输出**: TargetLocation 对象
  ```python
  {
    "block_id": "uuid",           # 块 ID
    "block_version_id": "uuid",   # 块版本 ID
    "rev_id": "uuid",             # 版本 ID
    "order_index": 5,             # 在文档中的位置
    "content": "原文内容",         # 块的完整内容
    "plain_text": "纯文本",       # 纯文本内容
    "block_type": "paragraph",    # 块类型
    "heading_context": "第三章",  # 所属章节
    "db_location": {              # 数据库位置信息
      "table": "block_versions",
      "primary_key": "uuid"
    },
    "meilisearch_index": {        # Meilisearch 索引信息
      "index_name": "blocks",
      "document_id": "doc_uuid_block_uuid",
      "indexed_at": "2026-01-26T10:00:00Z"
    },
    "context": {                  # 上下文信息
      "before": "前一段内容",
      "after": "后一段内容"
    },
    "confidence": 0.95            # 匹配置信度
  }
  ```
- **流程**:
  1. 根据意图选择检索策略（关键词/语义/混合）
  2. 执行多路检索（BM25 + Vector + Meilisearch）
  3. 使用 RRF 融合排序
  4. LLM 验证候选结果
  5. 如需消歧，返回多个候选让用户选择
  6. 获取目标块的完整位置信息（DB + Index）
  7. 获取上下文信息（前后块）
  8. 返回结构化的 TargetLocation

##### 2.5 Edit Agent（编辑执行智能体）
- **职责**: 基于定位信息执行编辑操作
- **输入**: TargetLocation（来自 Retrieval Agent）
- **工具**:
  - `llm_generate_plan`: 生成编辑计划
  - `llm_generate_content`: 生成新内容
  - `check_semantic_conflict`: 检测语义冲突
  - `db_create_revision`: 创建新版本
  - `db_update_blocks`: 更新块内容
  - `db_insert_block`: 插入新块
  - `db_delete_block`: 删除块
  - `index_update_block`: 更新 Meilisearch 索引
  - `cache_invalidate`: 清除相关缓存
- **流程**:
  1. 接收 TargetLocation 和 Intent
  2. 生成编辑计划（操作类型、新内容）
  3. 检测语义冲突
  4. 生成预览 diff
  5. 如需确认，返回预览
  6. 执行数据库操作（创建新版本、更新块）
  7. 更新 Meilisearch 索引
  8. 清除缓存
  9. 返回执行结果

#### 3. 工具层（Tools）

##### 3.1 数据库工具（DB Tools）
```python
# 文档操作
- get_document(doc_id) -> Document
- get_revision(rev_id) -> Revision
- get_active_revision(doc_id) -> Revision
- create_revision(doc_id, parent_rev_id) -> Revision

# 块操作
- get_blocks(rev_id, filters) -> List[Block]
- get_block_by_id(block_id, rev_id) -> Block
- update_block(block_id, content) -> Block
- insert_block(rev_id, content, position) -> Block
- delete_block(block_id) -> bool

# 版本操作
- list_revisions(doc_id) -> List[Revision]
- rollback_revision(doc_id, target_rev_id) -> Revision
```

##### 3.2 检索工具（Search Tools）
```python
# 混合检索
- search_hybrid(query, doc_id, rev_id, top_k) -> List[Candidate]
- search_bm25(query, doc_id, rev_id, top_k) -> List[Candidate]
- search_vector(query, doc_id, rev_id, top_k) -> List[Candidate]

# 索引管理
- index_document(doc_id, rev_id) -> bool
- update_index(block_ids) -> bool
- delete_index(doc_id) -> bool
```

##### 3.3 LLM 工具（LLM Tools）
```python
# 意图理解
- parse_intent(user_message, context) -> Intent
- check_ambiguity(user_message, intent) -> AmbiguityCheck

# 内容生成
- generate_content(instruction, context) -> str
- generate_plan(intent, targets) -> EditPlan
- verify_target(intent, candidate) -> VerifyResult

# 语义分析
- check_semantic_conflict(original, new, context) -> ConflictCheck
- generate_clarification(ambiguity) -> Clarification
```

##### 3.4 索引工具（Index Tools）⭐ 新增
```python
# Meilisearch 索引操作
- index_document(doc_id, rev_id) -> IndexResult
- index_block(block_id, content, metadata) -> bool
- update_index(block_id, content) -> bool
- delete_from_index(block_id) -> bool
- search_index(query, filters) -> List[IndexResult]
- get_index_info(block_id) -> IndexInfo

# 索引管理
- rebuild_index(doc_id) -> bool
- clear_index(doc_id) -> bool
- get_index_stats() -> dict
```

##### 3.5 缓存工具（Cache Tools）
```python
- cache_get(key) -> Any
- cache_set(key, value, ttl) -> bool
- cache_delete(key) -> bool
- cache_clear_pattern(pattern) -> int
```

---

## 🔄 状态管理

### State Schema

```python
from typing import TypedDict, List, Optional, Literal
from langgraph.graph import StateGraph

class TargetLocation(TypedDict):
    """目标块的完整位置信息"""
    block_id: str
    block_version_id: str
    rev_id: str
    order_index: int
    content: str
    plain_text: str
    block_type: str
    heading_context: str
    db_location: dict
    meilisearch_index: dict
    context: dict
    confidence: float

class WorkflowState(TypedDict):
    # 基础信息
    doc_id: str
    session_id: str
    user_id: str
    active_rev_id: str
    active_version: int
    
    # 用户输入
    user_message: str
    user_selection: Optional[str]
    user_clarification: Optional[dict]
    
    # 意图信息
    intent: Optional[Intent]
    intent_confidence: float
    
    # 路由决策
    next_action: Literal["clarify", "retrieve", "edit", "end"]
    needs_clarification: bool
    clarification: Optional[dict]
    
    # 检索结果（Retrieval Agent 输出）⭐ 更新
    candidates: List[Candidate]
    target_locations: List[TargetLocation]  # 新增：完整的位置信息
    selected_target: Optional[TargetLocation]  # 新增：用户选择的目标
    
    # 编辑计划（Edit Agent 使用）
    edit_plan: Optional[EditPlan]
    preview_diff: Optional[PreviewDiff]
    
    # 执行结果
    new_rev_id: Optional[str]
    apply_result: Optional[ApplyResult]
    
    # 控制流
    retry_count: int
    max_retries: int
    warnings: List[dict]
    errors: List[dict]
    
    # 追踪信息
    trace_id: Optional[str]
    span_ids: dict
```

---

---

## � Retrieval Agent 详细设计

### 核心职责
Retrieval Agent 是连接意图理解和编辑执行的关键桥梁，负责：
1. 精准定位目标块
2. 收集完整的位置信息（DB + Index）
3. 提供上下文信息
4. 处理消歧场景

### 工作流程

```
用户意图 (Intent)
    ↓
┌─────────────────────────────────────┐
│  1. 选择检索策略                     │
│     - 关键词明确 → BM25              │
│     - 语义描述 → Vector              │
│     - 复杂查询 → Hybrid              │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  2. 多路检索                         │
│     - BM25 检索 (Meilisearch)       │
│     - 向量检索 (pgvector)           │
│     - 全文检索 (Meilisearch)        │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  3. 结果融合 (RRF)                  │
│     - 合并多路结果                   │
│     - 重排序                         │
│     - 去重                           │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  4. LLM 验证                        │
│     - 验证每个候选是否匹配意图       │
│     - 计算匹配置信度                 │
│     - 过滤低置信度结果               │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  5. 收集位置信息                     │
│     - 数据库位置 (table, pk)        │
│     - 索引位置 (index, doc_id)      │
│     - 文档位置 (order_index)        │
│     - 上下文 (前后块)                │
└─────────────────────────────────────┘
    ↓
    判断：候选数量
    ↓           ↓
  单个         多个
    ↓           ↓
  返回      返回消歧选项
TargetLocation  (让用户选择)
```

### 输出数据结构

```python
class TargetLocation(TypedDict):
    """完整的目标位置信息"""
    
    # 基础标识
    block_id: str                    # 块 ID (UUID)
    block_version_id: str            # 块版本 ID (UUID)
    rev_id: str                      # 文档版本 ID (UUID)
    
    # 内容信息
    content: str                     # Markdown 格式内容
    plain_text: str                  # 纯文本内容
    block_type: str                  # 块类型 (paragraph/heading/list/code/table)
    
    # 位置信息
    order_index: int                 # 在文档中的顺序位置
    heading_context: str             # 所属章节标题
    
    # 数据库位置
    db_location: {
        "table": "block_versions",   # 表名
        "primary_key": "uuid",       # 主键值
        "schema": "public"           # 模式名
    }
    
    # Meilisearch 索引位置
    meilisearch_index: {
        "index_name": "blocks",      # 索引名称
        "document_id": "doc_block",  # 文档 ID
        "indexed_at": "timestamp",   # 索引时间
        "index_version": "v1"        # 索引版本
    }
    
    # 上下文信息
    context: {
        "before": {                  # 前一个块
            "block_id": "uuid",
            "content": "...",
            "order_index": 4
        },
        "after": {                   # 后一个块
            "block_id": "uuid",
            "content": "...",
            "order_index": 6
        },
        "parent_heading": "第三章"   # 父级标题
    }
    
    # 元数据
    confidence: float                # 匹配置信度 (0-1)
    match_reason: str                # 匹配原因说明
    retrieval_scores: {              # 各检索方法的得分
        "bm25": 0.85,
        "vector": 0.92,
        "rrf": 0.88
    }
```

### 关键工具实现

#### 1. 混合检索工具
```python
class HybridSearchTool(BaseTool):
    name = "search_hybrid"
    description = "执行混合检索（BM25 + 向量 + RRF 融合）"
    
    def _run(
        self,
        query: str,
        doc_id: str,
        rev_id: str,
        top_k: int = 10
    ) -> List[Candidate]:
        # BM25 检索
        bm25_results = self.meilisearch.search(query, top_k)
        
        # 向量检索
        vector_results = self.pgvector.search(query, top_k)
        
        # RRF 融合
        fused_results = self.rrf_fusion(bm25_results, vector_results)
        
        return fused_results[:top_k]
```

#### 2. 位置信息收集工具
```python
class GetLocationInfoTool(BaseTool):
    name = "get_location_info"
    description = "获取块的完整位置信息（DB + Index + Context）"
    
    def _run(
        self,
        block_id: str,
        rev_id: str
    ) -> TargetLocation:
        # 从数据库获取块信息
        block = db.query(BlockVersion).filter(
            BlockVersion.block_id == block_id,
            BlockVersion.rev_id == rev_id
        ).first()
        
        # 获取 Meilisearch 索引信息
        index_info = meilisearch.get_document(
            f"{doc_id}_{block_id}"
        )
        
        # 获取上下文（前后块）
        context = self._get_context(block, rev_id)
        
        return TargetLocation(
            block_id=str(block.block_id),
            block_version_id=str(block.id),
            rev_id=str(block.rev_id),
            content=block.content_md,
            plain_text=block.plain_text,
            block_type=block.block_type,
            order_index=block.order_index,
            heading_context=block.heading_context,
            db_location={
                "table": "block_versions",
                "primary_key": str(block.id),
                "schema": "public"
            },
            meilisearch_index={
                "index_name": "blocks",
                "document_id": index_info["id"],
                "indexed_at": index_info["indexed_at"],
                "index_version": "v1"
            },
            context=context,
            confidence=0.95
        )
```

#### 3. LLM 验证工具
```python
class VerifyTargetTool(BaseTool):
    name = "llm_verify_target"
    description = "使用 LLM 验证候选块是否匹配用户意图"
    
    def _run(
        self,
        intent: Intent,
        candidate: Candidate
    ) -> VerifyResult:
        prompt = f"""
        用户意图：{intent.description}
        操作类型：{intent.operation}
        
        候选内容：
        {candidate.content}
        
        判断这个候选是否匹配用户意图。
        输出 JSON：
        {{
          "is_match": true/false,
          "confidence": 0.0-1.0,
          "reason": "匹配/不匹配的原因"
        }}
        """
        
        result = llm.chat_completion_json(prompt)
        return VerifyResult(**result)
```

### 消歧处理

当检索到多个高置信度候选时，Retrieval Agent 会：

1. **返回候选列表**：包含每个候选的位置信息和预览
2. **生成消歧问题**：帮助用户理解每个候选的上下文
3. **等待用户选择**：用户选择后，继续执行编辑流程

```python
# 消歧响应示例
{
  "status": "need_disambiguation",
  "candidates": [
    {
      "target_location": TargetLocation,
      "preview": "第三章 > 3.1 项目背景 > 本项目旨在...",
      "context_hint": "位于第三章开头"
    },
    {
      "target_location": TargetLocation,
      "preview": "第五章 > 5.2 实施计划 > 项目背景调研...",
      "context_hint": "位于第五章实施计划部分"
    }
  ],
  "question": "找到 2 个可能的位置，请选择要修改的段落："
}
```

### 性能优化

1. **缓存策略**
   - 缓存检索结果（5 分钟）
   - 缓存位置信息（10 分钟）
   - 缓存上下文信息（10 分钟）

2. **并行执行**
   - BM25 和向量检索并行执行
   - 位置信息收集并行执行

3. **智能降级**
   - 向量检索失败 → 降级到 BM25
   - Meilisearch 失败 → 降级到数据库查询
   - LLM 验证失败 → 使用规则验证

---

## 📝 实施计划

### Phase 1: 基础设施准备（1-2 天）

#### 1.1 安装依赖
```bash
pip install langgraph langchain-core langchain-openai
```

#### 1.2 创建工具层基础结构
- [ ] 创建 `app/tools/` 目录
- [ ] 实现 `app/tools/base.py` - 工具基类
- [ ] 实现 `app/tools/db_tools.py` - 数据库工具
- [ ] 实现 `app/tools/search_tools.py` - 检索工具
- [ ] 实现 `app/tools/llm_tools.py` - LLM 工具
- [ ] 实现 `app/tools/index_tools.py` - 索引工具 ⭐ 新增
- [ ] 实现 `app/tools/cache_tools.py` - 缓存工具

#### 1.3 创建智能体基础结构
- [ ] 创建 `app/agents/` 目录
- [ ] 实现 `app/agents/base.py` - 智能体基类
- [ ] 定义统一的智能体接口

### Phase 2: 工具层实现（2-3 天）

#### 2.1 数据库工具实现
```python
# app/tools/db_tools.py
from langchain.tools import BaseTool
from typing import Optional
from pydantic import BaseModel, Field

class GetDocumentInput(BaseModel):
    doc_id: str = Field(description="文档 ID")

class GetDocumentTool(BaseTool):
    name = "get_document"
    description = "获取文档信息"
    args_schema = GetDocumentInput
    
    def _run(self, doc_id: str) -> dict:
        # 实现逻辑
        pass
```

#### 2.2 检索工具实现
- [ ] 实现混合检索工具
- [ ] 实现 BM25 检索工具
- [ ] 实现向量检索工具
- [ ] 添加检索结果缓存

#### 2.3 索引工具实现 ⭐ 新增
- [ ] 实现 Meilisearch 索引工具
- [ ] 实现索引更新工具
- [ ] 实现索引查询工具
- [ ] 添加索引状态管理

#### 2.4 LLM 工具实现
- [ ] 实现意图解析工具
- [ ] 实现内容生成工具
- [ ] 实现语义分析工具
- [ ] 添加 LLM 调用缓存

### Phase 3: 智能体实现（3-4 天）

#### 3.1 Intent Agent
```python
# app/agents/intent_agent.py
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

def create_intent_agent(tools: list):
    llm = ChatOpenAI(
        base_url=settings.QWEN_API_BASE,
        api_key=settings.QWEN_API_KEY,
        model=settings.QWEN_MODEL
    )
    
    system_prompt = """你是一个意图理解专家。
    
    你的任务是：
    1. 理解用户的编辑请求
    2. 提取关键信息（操作类型、目标描述、新内容）
    3. 评估意图的明确性
    
    可用工具：
    - llm_parse_intent: 调用 LLM 解析意图
    - db_get_document: 获取文档信息
    - db_get_revision: 获取版本信息
    """
    
    return create_react_agent(
        llm,
        tools,
        state_modifier=system_prompt
    )
```

#### 3.2 Router Agent
- [ ] 实现路由决策逻辑
- [ ] 实现条件判断工具
- [ ] 添加决策日志

#### 3.3 Clarify Agent
- [ ] 实现澄清问题生成
- [ ] 实现跨段落引用解析
- [ ] 实现用户响应处理

#### 3.4 Retrieval Agent ⭐ 新增
```python
# app/agents/retrieval_agent.py
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

def create_retrieval_agent(tools: list):
    llm = ChatOpenAI(
        base_url=settings.QWEN_API_BASE,
        api_key=settings.QWEN_API_KEY,
        model=settings.QWEN_MODEL
    )
    
    system_prompt = """你是一个文档检索和定位专家。
    
    你的任务是：
    1. 根据用户意图选择最佳检索策略
    2. 执行多路检索（BM25 + 向量 + Meilisearch）
    3. 融合和排序检索结果
    4. 验证候选结果是否匹配意图
    5. 获取目标块的完整位置信息（数据库 + 索引）
    6. 获取上下文信息（前后块）
    7. 如有多个候选，返回让用户选择
    
    可用工具：
    - search_hybrid: 混合检索
    - search_bm25: BM25 检索
    - search_vector: 向量检索
    - search_meilisearch: Meilisearch 检索
    - db_get_blocks: 获取块详细信息
    - db_get_block_context: 获取块上下文
    - llm_verify_target: 验证目标匹配度
    - llm_rank_candidates: 重排序候选结果
    
    输出格式：
    {
      "target_locations": [TargetLocation],
      "needs_disambiguation": bool,
      "confidence": float
    }
    """
    
    return create_react_agent(
        llm,
        tools,
        state_modifier=system_prompt
    )
```

- [ ] 实现检索策略选择
- [ ] 实现多路检索执行
- [ ] 实现结果融合和排序
- [ ] 实现目标验证
- [ ] 实现位置信息收集
- [ ] 实现消歧处理

#### 3.5 Edit Agent
- [ ] 实现完整编辑流程
- [ ] 集成所有编辑相关工具
- [ ] 添加错误处理和重试

### Phase 4: LangGraph 工作流（2-3 天）

#### 4.1 定义状态图
```python
# app/services/langgraph_workflow.py
from langgraph.graph import StateGraph, END
from app.agents import (
    create_intent_agent,
    create_router_agent,
    create_clarify_agent,
    create_edit_agent
)

def create_workflow():
    # 创建状态图
    workflow = StateGraph(WorkflowState)
    
    # 添加节点
    workflow.add_node("intent", intent_node)
    workflow.add_node("router", router_node)
    workflow.add_node("clarify", clarify_node)
    workflow.add_node("retrieval", retrieval_node)  # ⭐ 新增
    workflow.add_node("edit", edit_node)
    
    # 添加边
    workflow.set_entry_point("intent")
    workflow.add_edge("intent", "router")
    
    # 条件路由
    workflow.add_conditional_edges(
        "router",
        route_decision,
        {
            "clarify": "clarify",
            "retrieve": "retrieval",  # ⭐ 更新
            "end": END
        }
    )
    
    workflow.add_edge("clarify", END)
    workflow.add_edge("retrieval", "edit")  # ⭐ 新增：检索后进入编辑
    workflow.add_edge("edit", END)
    
    return workflow.compile()
```

#### 4.2 实现节点函数
- [ ] 实现 intent_node
- [ ] 实现 router_node
- [ ] 实现 clarify_node
- [ ] 实现 retrieval_node ⭐ 新增
- [ ] 实现 edit_node

```python
# retrieval_node 示例实现
async def retrieval_node(state: WorkflowState) -> WorkflowState:
    """检索定位节点"""
    intent = state["intent"]
    doc_id = state["doc_id"]
    rev_id = state["active_rev_id"]
    
    # 创建 Retrieval Agent
    retrieval_agent = create_retrieval_agent(retrieval_tools)
    
    # 执行检索
    result = await retrieval_agent.ainvoke({
        "intent": intent,
        "doc_id": doc_id,
        "rev_id": rev_id,
        "user_message": state["user_message"]
    })
    
    # 更新状态
    state["target_locations"] = result["target_locations"]
    
    # 如需消歧
    if result.get("needs_disambiguation"):
        state["next_action"] = "end"
        state["needs_disambiguation"] = True
        return state
    
    # 选择最佳目标
    state["selected_target"] = result["target_locations"][0]
    state["next_action"] = "edit"
    
    return state
```

#### 4.3 实现路由函数
- [ ] 实现 route_decision
- [ ] 添加路由日志

### Phase 5: API 集成（1-2 天）

#### 5.1 更新 API 端点
```python
# app/api/v1/chat.py
from app.services.langgraph_workflow import create_workflow

@router.post("/edit")
async def chat_edit(
    request: ChatEditRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 创建工作流
    workflow = create_workflow()
    
    # 初始化状态
    initial_state = {
        "doc_id": request.doc_id,
        "session_id": request.session_id,
        "user_id": str(current_user.id),
        "user_message": request.message,
        "retry_count": 0,
        "max_retries": 2
    }
    
    # 执行工作流
    result = await workflow.ainvoke(initial_state)
    
    # 返回结果
    return format_response(result)
```

#### 5.2 添加流式输出支持
```python
@router.post("/edit/stream")
async def chat_edit_stream(
    request: ChatEditRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    workflow = create_workflow()
    
    async def event_generator():
        async for event in workflow.astream(initial_state):
            yield f"data: {json.dumps(event)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

### Phase 6: 测试与优化（2-3 天）

#### 6.1 单元测试
- [ ] 测试所有工具函数
- [ ] 测试所有智能体
- [ ] 测试状态转换

#### 6.2 集成测试
- [ ] 测试完整工作流
- [ ] 测试错误处理
- [ ] 测试边界情况

#### 6.3 性能优化
- [ ] 优化 LLM 调用次数
- [ ] 添加缓存策略
- [ ] 优化数据库查询

#### 6.4 可观测性
- [ ] 集成 Langfuse 追踪
- [ ] 添加性能指标
- [ ] 添加错误监控

### Phase 7: 文档与部署（1 天）

#### 7.1 更新文档
- [ ] 更新 README.md
- [ ] 更新架构文档
- [ ] 添加开发指南

#### 7.2 部署准备
- [ ] 更新 requirements.txt
- [ ] 更新 Docker 配置
- [ ] 更新环境变量

---

## 📈 预期收益

### 1. 技术收益

| 指标 | 当前 | 重构后 | 提升 |
|------|------|--------|------|
| 代码可维护性 | 中 | 高 | +40% |
| 功能扩展性 | 低 | 高 | +60% |
| 工具复用率 | 20% | 80% | +300% |
| 可观测性 | 中 | 高 | +50% |
| 智能化水平 | 低 | 高 | +70% |

### 2. 业务收益

- ✅ **更灵活的编辑能力**: 支持更复杂的编辑场景
- ✅ **更好的用户体验**: 流式输出，实时反馈
- ✅ **更强的自适应性**: 根据场景自动调整策略
- ✅ **更容易维护**: 模块化设计，职责清晰
- ✅ **更好的可扩展性**: 轻松添加新功能

### 3. 成本影响

| 项目 | 当前 | 重构后 | 变化 |
|------|------|--------|------|
| LLM 调用次数 | 2-3 次 | 4-6 次 | +100% |
| 平均延迟 | 2-3 秒 | 4-6 秒 | +100% |
| 单次成本 | ¥0.02 | ¥0.04-0.05 | +100% |

**成本增加原因**:
- 新增 Retrieval Agent 的 LLM 验证调用
- 新增候选结果的重排序调用
- 更完整的位置信息收集

**成本优化策略**:
- 使用缓存减少重复调用（预计节省 30%）
- 智能路由避免不必要的步骤（预计节省 20%）
- 批量处理降低单次成本（预计节省 15%）
- 使用更小的模型进行验证任务（预计节省 25%）

**优化后预期成本**: ¥0.03-0.04/请求（与当前持平或略高）

---

## ⚠️ 风险与挑战

### 1. 技术风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| LangGraph 学习曲线 | 中 | 高 | 提前学习，参考官方示例 |
| 性能下降 | 高 | 中 | 性能测试，优化关键路径 |
| 兼容性问题 | 中 | 低 | 保留旧接口，逐步迁移 |
| 调试困难 | 中 | 中 | 完善日志，使用 Langfuse |

### 2. 业务风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 功能回归 | 高 | 中 | 完整测试，灰度发布 |
| 用户体验下降 | 高 | 低 | A/B 测试，收集反馈 |
| 成本增加 | 中 | 高 | 成本监控，优化策略 |

### 3. 项目风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 工期延误 | 中 | 中 | 分阶段实施，及时调整 |
| 资源不足 | 中 | 低 | 合理分配，优先级排序 |
| 需求变更 | 低 | 低 | 敏捷开发，快速响应 |

---

## 🎯 成功标准

### 1. 功能完整性
- ✅ 所有现有功能正常工作
- ✅ 新增流式输出功能
- ✅ 新增智能路由功能
- ✅ 完整的错误处理

### 2. 性能指标
- ✅ P95 延迟 < 5 秒
- ✅ 成功率 > 95%
- ✅ 定位准确率 > 90%

### 3. 代码质量
- ✅ 测试覆盖率 > 80%
- ✅ 代码规范检查通过
- ✅ 文档完整

### 4. 可观测性
- ✅ 完整的 Langfuse 追踪
- ✅ 关键指标监控
- ✅ 错误告警

---

## 📚 参考资料

### LangGraph 官方文档
- [LangGraph 快速开始](https://langchain-ai.github.io/langgraph/)
- [StateGraph 使用指南](https://langchain-ai.github.io/langgraph/concepts/low_level/)
- [Agent 最佳实践](https://langchain-ai.github.io/langgraph/concepts/agentic_concepts/)

### LangChain 工具开发
- [自定义工具](https://python.langchain.com/docs/modules/tools/custom_tools)
- [工具调用](https://python.langchain.com/docs/modules/tools/)

### Langfuse 集成
- [LangGraph + Langfuse](https://langfuse.com/docs/integrations/langchain/tracing)
- [追踪最佳实践](https://langfuse.com/docs/tracing)

---

## 📞 联系方式

如有问题或建议，请联系：
- 项目负责人: [您的名字]
- 邮箱: minsibour@gmail.com
- GitHub Issues: https://github.com/minsib/document_mcp/issues

---

**最后更新**: 2026-01-26  
**文档状态**: ✅ 待审核
