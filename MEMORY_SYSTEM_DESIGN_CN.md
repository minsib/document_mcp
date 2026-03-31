# 记忆系统设计文档

## 目标

本文定义文档编辑系统的记忆系统 V1 方案。

目标如下：

- 将记忆稳定绑定到真实认证用户
- 复用已经落库的会话和消息作为记忆源数据
- 将长期稳定偏好与时效性上下文分开存储
- 让写入逻辑可控、可审计、可回溯
- 让读取成本足够低，可以在每次编辑工作流开始时加载

这个设计**不依赖完整迁移到 `deepagents`**，可以直接落在当前的 `LangGraph + workflow + services` 架构上。

## 当前基础

当前项目已经具备以下前提条件：

- 已有认证用户 `users`
- 文档归属关系 `documents.user_id`
- 已有 `chat_sessions`
- 已有 `chat_messages`
- 文档块已接入 `pgvector`
- 主工作流入口可以在规划编辑前加载额外上下文

最近已经完成的改造还包括：

- `/v1/chat/edit` 和 `/v1/chat/confirm` 已绑定真实用户
- 每一轮 user/assistant 对话已落库
- workflow trace 已记录 `agents_used`、`skills_used`、`events`
- 主链路已经按 `agent + skill` 风格解耦，但没有切换到底层 runtime

## 设计原则

1. 记忆是系统状态，不是原始聊天记录本身。
2. 提取可以用 LLM，但存储策略应尽量规则化。
3. 稳定偏好应存结构化表，不应直接存成向量块。
4. 时效性记忆应按“相关性 + 新鲜度”检索，而不是全量拼进 prompt。
5. 用户必须能查看、删除、关闭自己的记忆。

## 记忆类型

### 1. 长期稳定偏好

适合长期保留，并且可以直接拼进提示词的用户偏好。

示例：

- 回答语言：`zh`、`en`
- 回答风格：`concise`、`detailed`、`structured`
- 编辑风格：`conservative`、`rewrite_aggressive`
- 默认确认偏好：`preview_first`、`auto_apply_low_risk`
- 格式偏好：`bullet_first`、`table_ok`、`no_emoji`

### 2. 情节型记忆

中短期有效，描述用户最近在做什么、关注什么。

示例：

- 用户最近正在编辑某个项目的发版说明
- 用户最近在改搜索系统的技术方案文档
- 用户最近一段时间主要在做法律风格措辞优化

### 3. 工作上下文记忆

短期有效，通常和当前文档、当前编辑阶段、当前工作流有关，并应自动过期。

示例：

- 用户当前正在重写项目背景部分
- 用户最近更偏好 `replace` 而不是 `delete`
- 用户最近 30 分钟一直在编辑同一篇文档

## 存储模型

### 表：`user_preferences`

用于存长期稳定偏好，结构化读取，适合直接注入 prompt。

建议表结构：

```sql
CREATE TABLE user_preferences (
    preference_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    preference_key TEXT NOT NULL,
    preference_value JSONB NOT NULL,
    source TEXT NOT NULL DEFAULT 'memory_extractor',
    confidence NUMERIC(4,3) NOT NULL DEFAULT 0.800,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, preference_key)
);

CREATE INDEX idx_user_preferences_user_key
ON user_preferences (user_id, preference_key);
```

说明：

- `preference_value` 用 `JSONB`，这样既能存字符串，也能存结构化对象
- 同一个 `preference_key` 默认采用覆盖更新

### 表：`user_memory_items`

用于存可检索的情节型记忆和工作上下文记忆。

建议表结构：

```sql
CREATE TABLE user_memory_items (
    memory_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    doc_id UUID NULL,
    session_id UUID NULL,
    memory_layer TEXT NOT NULL DEFAULT 'episodic',
    memory_type TEXT NOT NULL,
    memory_subtype TEXT NULL,
    scope TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT NULL,
    retrieval_text TEXT NULL,
    source_message_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    extraction_reason JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_type TEXT NOT NULL DEFAULT 'turn_trace',
    confidence NUMERIC(4,3) NOT NULL,
    importance NUMERIC(4,3) NOT NULL DEFAULT 0.500,
    memory_strength DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    stability DOUBLE PRECISION NOT NULL DEFAULT 7.0,
    review_count INTEGER NOT NULL DEFAULT 0,
    recall_count INTEGER NOT NULL DEFAULT 0,
    retention_score DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    last_recalled_at TIMESTAMPTZ NULL,
    last_reinforced_at TIMESTAMPTZ NULL,
    min_keep_until TIMESTAMPTZ NULL,
    max_keep_until TIMESTAMPTZ NULL,
    archived_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

如果要直接在 PostgreSQL 里做向量检索：

```sql
ALTER TABLE user_memory_items
ADD COLUMN embedding vector(1024);

CREATE INDEX idx_user_memory_items_user_type_time
ON user_memory_items (user_id, memory_type, created_at DESC);
```

建议枚举值：

- `memory_layer`：`working`、`episodic`、`persona`、`relation`
- `memory_type`：`edit_pattern`、`failure_case`、`project_context`
- `memory_subtype`：`confirmed_edit`、`failed_edit`、`retry_trace`
- `scope`：`short_term`、`medium_term`、`long_term`

### 可选表：`memory_extraction_runs`

用于审计和调试，不是 V1 必需。

```sql
CREATE TABLE memory_extraction_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    session_id UUID NOT NULL,
    source_message_ids JSONB NOT NULL,
    extractor_version TEXT NOT NULL,
    candidates JSONB NOT NULL,
    decisions JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

如果想先快速上线，V1 可以先不做这张表。

## 源数据

记忆提取应从已经落库的会话消息中读取，而不是从 HTTP 原始请求里直接取。

主要来源：

- `chat_sessions`
- `chat_messages`

目前 `chat_messages.meta` 里已经有这些结构化信息：

- `doc_id`
- `request_type`
- `status`
- `operation_type`
- `confirm_token`
- `preview_hash`
- `new_rev_id`
- `trace.agents_used`
- `trace.skills_used`
- `trace.events`

这些信息已经足够支撑第一版记忆提取，不需要再新增一条并行埋点链路。

## 提取流程

### 第一步：候选记忆提取

在一轮 user/assistant 对话完成并落库之后触发。

建议触发点：

- `/v1/chat/edit` 响应落库之后
- `/v1/chat/confirm` 响应落库之后

输入：

- 最新 user message
- 最新 assistant message
- 当前 session 最近 5 到 20 条消息
- 文档上下文
- workflow trace

输出格式建议：

```json
[
  {
    "memory_class": "preference",
    "key": "response_style",
    "value": "concise",
    "confidence": 0.92,
    "reason": "用户多次表达希望回答更简洁直接。"
  },
  {
    "memory_class": "episodic",
    "title": "近期在修改搜索上线发布说明",
    "content": "用户最近正在修订搜索项目上线相关的 release notes。",
    "scope": "medium_term",
    "confidence": 0.81,
    "reason": "最近多个 session 都在讨论发布说明和上线措辞。"
  }
]
```

实现建议：

- 使用一个 LLM 驱动的 `MemoryExtractor`
- 输出必须走严格 schema 校验
- 校验失败的结果直接丢弃，不写库

### 第二步：策略判断

这一层尽量规则化，只在必要时借助 LLM。

需要判断：

- 存还是不存
- 存到 `user_preferences` 还是 `user_memory_items`
- 覆盖、合并还是追加
- 热度初始化和衰减参数
- 最低保留期和最大保留期
- 最低置信度门槛

### 第三步：持久化

这一步应由普通服务层完成，不应该让提取器直接写库。

- 偏好写入 `user_preferences`
- 情节型/上下文记忆写入 `user_memory_items`
- 必要时执行 merge/upsert

## 提取规则

### 什么时候存成长期稳定偏好

满足以下特征时，存入 `user_preferences`：

- 明确是用户偏好表达
- 在多个 session 中重复出现
- 预计一周以上仍然有价值
- 能直接影响回答生成或编辑策略

示例：

- “以后都用中文回复”
- “回答简洁一点”
- “默认先给结论再展开”
- “修改时尽量保守，不要大改”

默认处理策略：

- 同一个 `preference_key` 采用 `overwrite`

### 什么时候存成情节型或工作上下文记忆

满足以下特征时，存入 `user_memory_items`：

- 与当前项目或近期任务相关
- 对未来几次检索有帮助
- 不足以提升为长期稳定偏好
- 带有文档或时间上下文

示例：

- 用户最近在准备某次产品发布文档
- 用户最近主要在润色 PRD
- 用户最近一直在对同一篇文档做多轮编辑

默认处理策略：

- 如果是全新内容，用 `append`
- 如果和已有内容高度相似，用 `merge/update`

### 什么时候丢弃

以下情况直接不存：

- 纯礼貌性对话
- 只对当前这一轮有效的一次性指令
- 置信度太低
- 涉及敏感信息但没有明确产品价值
- 只是 assistant 的输出推测，缺乏用户信号

示例：

- “谢谢”
- “先这样吧”
- 一次性拼写修正，且没有体现长期模式

## 置信度、热度衰减与保留规则

建议阈值：

- 稳定偏好写入阈值：`>= 0.85`
- 情节型记忆写入阈值：`>= 0.75`
- 工作上下文写入阈值：`>= 0.65`
- 低于阈值直接丢弃

短中期记忆不建议只靠固定 TTL 删除，建议采用：

- 遗忘曲线衰减
- 定时任务扫描
- 最低生存期
- 最大保留期兜底
- 先归档再物理删除

建议初始化：

- 新写入短期记忆：`memory_strength = 0.85`，`stability = 7`
- 新写入中期记忆：`memory_strength = 0.92`，`stability = 21`
- 高价值上下文：可按 `importance` 和 `confidence` 给更高初值

建议强化更新：

- 仅被检索命中：增加 `recall_count`
- 被实际拼进 prompt：增加 `review_count`，并上调 `memory_strength`
- 被后续用户行为再次印证：提升 `stability`
- 同一主题被连续多轮使用：可额外提升 `stability`

建议遗忘公式：

```text
retention_score = memory_strength * exp(-days_elapsed / stability)
```

建议定时任务周期：

- 每小时或每天执行一次

建议归档规则：

- `short_term`：超过 7 天未被召回且 `retention_score < 0.25`，归档
- `medium_term`：超过 30 天未被召回且 `retention_score < 0.20`，归档
- 如果仍在 `min_keep_until` 保护期内，不归档
- 如果超过 `max_keep_until`，即使保留分较高，也进入人工可配置的归档/降级流程

建议删除策略：

- 默认先写 `archived_at`
- 归档后再由单独清理任务做物理删除

长期稳定偏好仍然不走遗忘曲线删除，只支持：

- 覆盖更新
- 显式删除

## 覆盖、追加、合并策略

### 覆盖

以下字段适合覆盖：

- `response_style`
- `response_language`
- `editing_style`
- `confirmation_preference`

原因：

- 这类字段应该只有“当前生效值”

### 追加

以下内容适合追加：

- 项目背景
- 最近活动
- 任务轨迹
- 情节型事实

原因：

- 历史本身有价值
- 用户可能同时并行处理多个上下文

### 合并

以下情况适合合并：

- 新候选和已有记忆语义高度接近
- 同一用户、同一项目、同一文档或同一会话簇
- 新内容只是补充细节或刷新时效性

合并后的更新内容：

- 更新 `summary`
- 合并 `source_message_ids`
- 刷新 `confidence`
- 刷新 `importance`
- 刷新 `memory_strength`
- 刷新 `stability`
- 刷新 `retention_score`
- 刷新 `last_reinforced_at`
- 刷新保留边界
- 更新时间戳

## 运行时读取方式

### 在工作流开始前加载

在 `EditWorkflow.execute(...)` 开始时做：

1. 读取该用户的长期稳定偏好
2. 检索与当前请求相关的记忆项
3. 组装紧凑的 memory context
4. 放入 workflow state

建议 state 扩展：

```python
state["user_preferences"] = {...}
state["retrieved_memories"] = [...]
state["memory_context"] = {
    "stable_preferences": "...",
    "recent_context": "...",
}
```

### Prompt 使用方式

不要把原始 memory row 直接无脑拼进 prompt。

推荐结构：

```text
稳定用户偏好：
- 使用中文回复
- 回答尽量简洁、结构化
- 优先保守修改，再考虑激进改写

近期相关上下文：
- 用户最近正在修改搜索项目上线说明
- 用户最近一直在编辑同一篇文档，并偏好先预览再确认
```

### 检索排序策略

对 `user_memory_items` 的排序建议考虑：

- 与当前用户消息的向量相似度
- 是否同一 `doc_id`
- 是否同一近期 `session_id`
- 热度
- 最近使用时间
- 重要度

建议 top-K：

- 3 到 8 条

## API 设计

### 1. 查询用户偏好

`GET /v1/users/me/preferences`

返回示例：

```json
{
  "items": [
    {
      "preference_key": "response_style",
      "preference_value": "concise",
      "confidence": 0.94,
      "last_seen_at": "2026-03-27T10:00:00Z"
    }
  ]
}
```

### 2. 更新用户偏好

`PUT /v1/users/me/preferences/{preference_key}`

请求示例：

```json
{
  "preference_value": "concise",
  "source": "user_explicit"
}
```

这个接口适合显式设置偏好，也适合未来做前端开关。

### 3. 查询用户记忆项

`GET /v1/users/me/memory`

建议支持 query 参数：

- `memory_type`
- `scope`
- `doc_id`
- `active_only=true`

### 4. 删除记忆项

`DELETE /v1/users/me/memory/{memory_id}`

### 5. 删除偏好

`DELETE /v1/users/me/preferences/{preference_key}`

### 6. 查看某个会话历史

`GET /v1/chat/sessions/{session_id}`

用途：

- 调试 session replay
- 支撑未来“系统记住了什么”的可视化界面

### 7. 手动触发重提取

`POST /v1/users/me/memory/extract`

用途：

- 管理员或调试用
- 根据 session 范围重新构建记忆

V1 可以先不做。

## 建议的服务层拆分

### `MemoryExtractor`

职责：

- 读取最近会话消息
- 调用 LLM，输出候选记忆
- 保证输出符合严格 schema

建议方法：

- `extract_from_session_turn(session_id, message_ids)`
- `extract_candidates(messages, document_context)`

### `MemoryPolicyService`

职责：

- 给候选项打分
- 决定存储目标
- 决定 overwrite / merge / append
- 分配初始热度、衰减率和保留边界

建议方法：

- `evaluate(candidate)`
- `decide(candidate, existing_memories, existing_preferences)`

### `MemoryStoreService`

职责：

- 写偏好
- 写记忆项
- 合并相似记忆
- 定时衰减热度
- 归档冷记忆
- 删除归档后的旧记忆

建议方法：

- `upsert_preference(...)`
- `insert_memory_item(...)`
- `merge_memory_item(...)`
- `delete_memory_item(...)`
- `decay_memory_heat(...)`
- `archive_cold_memories(...)`
- `prune_archived_memories(...)`

### `MemoryRetriever`

职责：

- 读取长期偏好
- 检索相关的中短期记忆
- 组装 memory context

建议方法：

- `get_user_preferences(user_id)`
- `search_memories(user_id, query, doc_id=None, top_k=5)`
- `build_memory_context(user_id, query, doc_id=None)`

## 提取 Prompt 规则建议

提取器应遵守以下规则：

1. 只提取和用户相关的记忆，不提取泛化任务摘要。
2. 显式用户偏好优先于隐式推断偏好。
3. 不要把一次性上下文误判成长期偏好。
4. 不要存密钥、密码、隐私细节等不必要敏感信息。
5. 不确定时降低置信度，不要强行输出强结论。
6. 长期偏好的值尽量归一化成稳定枚举。

建议的长期偏好 key：

- `response_language`
- `response_style`
- `response_structure`
- `editing_style`
- `confirmation_preference`
- `risk_tolerance`

## 实施计划

### 第一阶段

- 保持当前真实用户 + session/message 落库
- 增加 `GET /v1/chat/sessions/{session_id}`
- 增加 `user_preferences`
- 增加手动偏好接口

### 第二阶段

- 增加 `user_memory_items`
- 实现 `MemoryExtractor`
- 在 turn 落库后异步提取候选记忆

### 第三阶段

- 在 `EditWorkflow` 开始时注入偏好和记忆
- 增加用户侧记忆查看/删除接口
- 如有需要，再补前端展示

## 为什么适合这个项目

这套方案适合当前文档编辑系统，原因是：

- 用户身份现在已经稳定
- 会话和消息已经落库
- 主工作流本身比较确定，结构化偏好很容易发挥作用
- 项目已经在用 PostgreSQL 和 `pgvector`
- 记忆能力能提升编辑质量，但不需要先把整套系统迁到更重的 agent runtime

## V1 明确不做的事

- 不做完全自治、没有规则约束的记忆 agent
- 不把全部原始聊天记录都当作记忆
- 不在验证价值前就引入独立外部知识库
- 不迁移整个项目到 `deepagents`

## 建议的下一步实现切片

1. 先加 `GET /v1/chat/sessions/{session_id}`，方便直接查看落库消息
2. 先实现 `user_preferences`
3. 把长期偏好注入 `EditWorkflow`
4. 再实现 `user_memory_items`
5. 最后补提取器、策略层和持久化
