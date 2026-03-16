# 文档对话式内容修改系统

> 基于 AI 的智能文档编辑系统，支持自然语言对话式修改文档内容

## 项目简介

这是一个创新的文档编辑系统，允许用户通过自然语言对话的方式修改文档内容。系统使用 Qwen3-235B 大语言模型，结合混合检索技术，实现精准的内容定位和智能修改。

### 核心特性

- 🤖 **对话式编辑**：用自然语言描述修改需求，AI 自动定位并修改
- 🎯 **精准定位**：混合检索（BM25 + 向量检索 + RRF 融合）确保定位准确
- 🧠 **语义理解**：向量检索支持语义搜索，理解查询意图
- 📝 **版本管理**：完整的版本历史，支持任意版本回滚
- 🔍 **预览确认**：修改前预览 diff，确认后执行
- 🔄 **批量修改**：支持全文统一替换和批量编辑
- 🔒 **并发安全**：乐观锁机制，防止并发冲突
- 🔐 **用户认证**：JWT Token + API Key 双重认证
- 📊 **完整审计**：所有操作可追溯，支持审计查询
- 📈 **监控告警**：健康检查 + Prometheus 指标
- ⚡ **智能降级**：多级降级策略确保系统稳定性
- 👥 **协同编辑**：基于 Redis + WebSocket 的实时多人协作

## 技术架构

### 技术栈

- **后端框架**：FastAPI + Python 3.11+
- **数据库**：PostgreSQL 15+ (with pgvector)
- **搜索引擎**：Meilisearch
- **缓存**：Redis
- **LLM**：Qwen3-235B (通过 API)
- **工作流**：LangChain + LangGraph
- **可观测性**：Langfuse
- **监控**：Prometheus + Grafana

### 系统架构

```
┌─────────────┐
│   用户      │
└──────┬──────┘
       │
       ↓
┌─────────────────────────────────────┐
│  API Server (FastAPI)               │
│  ├─ LangGraph 工作流引擎            │
│  ├─ 意图解析 (Qwen3-235B)          │
│  ├─ 混合检索 (BM25 + Vector)       │
│  └─ 编辑执行引擎                    │
└──────┬──────────────────────────────┘
       │
       ├──────────────┬──────────────┬──────────────┐
       ↓              ↓              ↓              ↓
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ Postgres │   │  Redis   │   │Meilisearch│   │Qwen3 API │
│ +pgvector│   │ (Cache)  │   │  (BM25)   │   │ (235B)   │
└──────────┘   └──────────┘   └──────────┘   └──────────┘
```

## 快速开始

### 环境要求

**后端**:
- Python 3.11+
- PostgreSQL 15+ (with pgvector extension)
- Redis 7+
- Meilisearch 1.5+
- **Qwen API Key**（必需）



### 获取 Qwen API Key

1. 访问阿里云百炼平台：https://dashscope.console.aliyun.com/
2. 注册/登录账号
3. 进入 API-KEY 管理页面：https://dashscope.console.aliyun.com/apiKey
4. 创建新的 API Key
5. 复制 API Key 到 `.env` 文件中

### 安装步骤

1. **克隆项目**

```bash
git clone https://github.com/minsib/document_mcp.git
cd document_mcp
```

2. **创建虚拟环境**

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows
```

3. **安装依赖**

```bash
pip install -r requirements.txt
```

4. **配置环境变量**

创建 `.env` 文件：

```bash
# 数据库配置
DATABASE_URL=postgresql://user:password@localhost:5432/document_edit

# Redis 配置
REDIS_URL=redis://localhost:6379/0

# Meilisearch 配置
MEILI_HOST=http://localhost:7700
MEILI_MASTER_KEY=your_master_key

# Qwen3 API 配置
QWEN_API_KEY=your_qwen_api_key
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-max-latest  # 或 qwen3-235b

# 安全配置（生产环境必须修改）
SECRET_KEY=your-secret-key-here  # 使用 python -c "import secrets; print(secrets.token_urlsafe(32))" 生成
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440  # 24 小时

# Langfuse 配置（可选）
LANGFUSE_PUBLIC_KEY=your_public_key
LANGFUSE_SECRET_KEY=your_secret_key
LANGFUSE_HOST=https://cloud.langfuse.com

# 应用配置
APP_ENV=development
LOG_LEVEL=INFO
```

5. **初始化数据库**

```bash
# 创建数据库
createdb document_edit

# 安装 pgvector 扩展
psql document_edit -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 运行迁移
alembic upgrade head

# 创建管理员用户
python3 scripts/create_admin_user.py
```

6. **启动服务**

```bash
# 启动 Meilisearch（使用自定义端口）
meilisearch --master-key=your_master_key --http-addr 127.0.0.1:7702

# 启动 Redis（使用自定义端口）
redis-server --port 6382

# 启动后端 API 服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

7. **访问应用**

- API 文档：http://localhost:8001/docs
- 健康检查：http://localhost:8001/health

## 使用示例

### 使用 API（推荐）

#### 0. 用户认证

```bash
# 注册用户
curl -X POST "http://localhost:8000/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com",
    "password": "password123"
  }'

# 登录获取 Token
curl -X POST "http://localhost:8000/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "password": "password123"
  }'

# 响应包含 access_token 和 refresh_token
```

详细说明：[AUTH_GUIDE.md](AUTH_GUIDE.md)

### 1. 上传文档

```bash
curl -X POST "http://localhost:8000/v1/docs/upload" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@document.md" \
  -F "title=项目需求文档"
```

响应：
```json
{
  "doc_id": "550e8400-e29b-41d4-a716-446655440000",
  "rev_id": "660e8400-e29b-41d4-a716-446655440001",
  "block_count": 45,
  "title": "项目需求文档"
}
```

### 2. 对话式编辑

```bash
curl -X POST "http://localhost:8000/v1/chat/edit" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "doc_id": "550e8400-e29b-41d4-a716-446655440000",
    "session_id": "session_123",
    "message": "把项目背景那段改得更简洁一些"
  }'
```

响应（需要确认）：
```json
{
  "status": "need_confirm",
  "preview": {
    "diffs": [
      {
        "block_id": "block_001",
        "op_type": "replace",
        "before_snippet": "本项目旨在开发一个创新的...",
        "after_snippet": "本项目开发创新的...",
        "heading_context": "1. 项目背景",
        "char_diff": -50
      }
    ],
    "total_changes": 1,
    "estimated_impact": "low"
  },
  "confirm_token": "token_abc123",
  "preview_hash": "hash_xyz789",
  "message": "请确认以下修改"
}
```

### 3. 确认修改

```bash
curl -X POST "http://localhost:8000/v1/chat/confirm" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "session_123",
    "doc_id": "550e8400-e29b-41d4-a716-446655440000",
    "confirm_token": "token_abc123",
    "preview_hash": "hash_xyz789",
    "action": "apply"
  }'
```

响应：
```json
{
  "status": "applied",
  "new_rev_id": "770e8400-e29b-41d4-a716-446655440002",
  "message": "已成功修改 1 处内容"
}
```

### 4. 导出文档

```bash
curl -X GET "http://localhost:8000/v1/docs/550e8400-e29b-41d4-a716-446655440000/export?format=md" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -o output.md
```

### 5. 版本回滚

```bash
curl -X POST "http://localhost:8000/v1/docs/550e8400-e29b-41d4-a716-446655440000/rollback" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "target_rev_id": "660e8400-e29b-41d4-a716-446655440001",
    "target_rev_no": 1
  }'
```

### 6. 协同编辑（WebSocket）

系统支持基于 Redis + WebSocket 的实时多人协同编辑：

```javascript
// 建立 WebSocket 连接
const token = 'YOUR_ACCESS_TOKEN';
const docId = 'your-document-id';
const ws = new WebSocket(`ws://localhost:8001/ws/collab/${docId}?token=${token}`);

// 接收消息
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log('Received:', message);
  
  switch (message.type) {
    case 'edit':
      // 其他用户的编辑操作
      applyEdit(message.data);
      break;
    case 'cursor':
      // 其他用户的光标位置
      showCursor(message.user_id, message.position);
      break;
    case 'user_joined':
      // 用户加入通知
      console.log(`${message.username} 加入了文档`);
      break;
    case 'user_left':
      // 用户离开通知
      console.log(`${message.username} 离开了文档`);
      break;
    case 'error':
      // 编辑冲突等错误
      console.error(`编辑冲突: ${message.message}`);
      break;
  }
};

// 发送编辑操作
ws.send(JSON.stringify({
  type: 'edit',
  data: {
    block_id: 'block_123',
    operation: 'replace',
    content: '新内容'
  }
}));

// 发送光标位置
ws.send(JSON.stringify({
  type: 'cursor',
  position: {
    block_id: 'block_123',
    offset: 42
  }
}));
```

**协同编辑特性**：
- ✅ **实时同步**：编辑操作实时广播给所有在线用户
- ✅ **编辑锁机制**：块级编辑锁防止编辑冲突
- ✅ **用户状态管理**：实时显示在线用户列表
- ✅ **光标同步**：实时同步用户光标位置
- ✅ **离线同步**：支持离线用户重新连接后同步最新编辑
- ✅ **数据持久化**：编辑历史存储在 Redis 中

**⚠️ 当前限制**：
- 单实例部署（不支持多容器/多机器扩展）
- 消息同步模式（非文档状态同步）
- 适合小规模团队使用（< 10 人）
- 详细技术限制请参考 [COLLABORATION_TECHNICAL_DEBT.md](COLLABORATION_TECHNICAL_DEBT.md)



## 核心功能详解

### 1. 智能定位

系统使用混合检索策略确保定位准确：

- **BM25 检索**：擅长关键词匹配（如"第 3 章"、"交付时间"）
- **向量检索**：擅长语义理解（如"关于钱的内容" → "付款条款"）
- **RRF 融合算法**：使用 Reciprocal Rank Fusion 算法融合多路检索结果，提升准确率

#### RRF 算法原理

RRF (Reciprocal Rank Fusion) 是一种简单而有效的多路检索结果融合算法：

```
RRF(d) = Σ 1 / (k + rank(d))
```

其中：
- `d` 是文档（块）
- `k` 是常数（默认 60）
- `rank(d)` 是文档在各个检索结果列表中的排名

**优势**：
- 不需要归一化不同检索器的分数
- 对排名靠前的结果给予更高权重
- 能够有效融合 BM25 和向量检索的优势
- 简单高效，无需训练

### 2. 编辑操作类型

- **replace**：替换指定段落内容
- **insert_after**：在指定段落后插入新内容
- **insert_before**：在指定段落前插入新内容
- **delete**：删除指定段落
- **multi_replace**：批量替换（全文统一修改）

### 3. 安全机制

- **evidence_quote 校验**：确保定位的段落与 AI 理解的一致
- **preview_hash 校验**：确保用户确认的预览与实际执行的修改一致
- **乐观锁**：防止并发修改冲突
- **三重校验**：preview_hash + plan_hash + version 确保修改安全

### 4. 版本管理

- 每次修改生成新 revision
- 完整的版本历史链
- 支持任意版本回滚
- 审计日志记录所有操作

## 项目结构

```
document_mcp/
├── app/                        # 后端应用
│   ├── main.py                 # FastAPI 应用入口
│   ├── config.py               # 配置管理
│   ├── models/                 # 数据模型
│   │   ├── database.py         # SQLAlchemy 模型
│   │   └── schemas.py          # Pydantic 模型
│   ├── api/                    # API 路由
│   │   └── collaboration.py    # 协同编辑 WebSocket API ✅
│   ├── auth/                   # 认证模块（JWT + API Key）
│   ├── services/               # 业务逻辑层
│   │   ├── splitter.py         # 文档智能分块
│   │   ├── retriever.py        # 混合检索（BM25 + 向量 + RRF）
│   │   ├── langgraph_workflow.py  # LangGraph 工作流引擎 ✅
│   │   ├── collaboration.py    # 协同编辑管理器 ✅
│   │   ├── cache.py            # 多级缓存管理
│   │   └── search_indexer.py   # Meilisearch 索引
│   ├── agents/                 # 智能体层 ✅
│   │   ├── intent_agent.py     # 意图理解智能体
│   │   ├── router_agent.py     # 路由决策智能体
│   │   ├── clarify_agent.py    # 澄清确认智能体
│   │   ├── retrieval_agent.py  # 检索定位智能体
│   │   └── edit_agent.py       # 编辑执行智能体
│   ├── tools/                  # 工具层 ✅
│   │   ├── db_tools.py         # 数据库操作工具
│   │   ├── search_tools.py     # 检索工具
│   │   ├── llm_tools.py        # LLM 调用工具
│   │   └── index_tools.py      # 索引管理工具
│   ├── nodes/                  # 工作流节点（批量编辑等）
│   ├── monitoring/             # 监控模块（Prometheus）
│   └── utils/                  # 工具函数
├── alembic/                    # 数据库迁移
│   └── versions/               # 迁移脚本
├── scripts/                    # 运维脚本
│   ├── test_monitoring.py      # 监控测试脚本
│   └── generate_monitoring_traffic.sh  # 流量生成
├── ops/                        # 运维配置
│   ├── prometheus/             # Prometheus 配置
│   └── grafana/                # Grafana 配置
├── .env.example                # 环境变量示例
├── requirements.txt            # Python 依赖
├── docker-compose.yml          # Docker Compose 编排
└── README.md                   # 本文件
```

## 开发指南

### 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_workflow.py

# 生成覆盖率报告
pytest --cov=app --cov-report=html
```

### 代码规范

项目使用以下工具确保代码质量：

```bash
# 格式化代码
black app/

# 类型检查
mypy app/

# Lint 检查
ruff check app/
```

### 数据库迁移

```bash
# 创建新迁移
alembic revision --autogenerate -m "描述"

# 应用迁移
alembic upgrade head

# 回滚迁移
alembic downgrade -1
```

## 部署

### Docker 部署

```bash
# 构建镜像
docker build -t document-edit:latest .

# 使用 Docker Compose 启动
docker-compose up -d
```

### 启用向量检索（推荐）

向量检索可以显著提升语义搜索准确率。启用步骤：

```bash
# 1. 添加 pgvector 支持
python scripts/add_vector_support.py

# 2. 为现有文档生成 embeddings
python scripts/regenerate_embeddings.py

# 3. 验证安装
psql -h localhost -p 5435 -U postgres -d document_edit -c "SELECT COUNT(*) FROM block_versions WHERE embedding IS NOT NULL;"
```



### 生产环境配置

```bash
# 使用 Gunicorn + Uvicorn
gunicorn app.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
```

## 性能指标

- **定位准确率**：> 90%（混合检索 + RRF 融合）
- **单次编辑延迟**：< 3 秒（P95）
- **批量修改**：< 5 秒（100 处）
- **并发支持**：100+ 并发编辑请求
- **协同编辑延迟**：< 100ms（WebSocket 消息传输，单实例）
- **多用户协作**：支持 < 10 用户同时编辑（MVP 限制）
- **可用性**：99.9% SLA

## 监控与健康检查

系统提供完整的监控和可观测性功能：

```bash
# 健康检查
curl http://localhost:8000/health/

# Prometheus 指标
curl http://localhost:8000/metrics

# Kubernetes liveness probe
curl http://localhost:8000/health/liveness

# Kubernetes readiness probe
curl http://localhost:8000/health/readiness
```


## 监控与告警

系统提供完整的 Prometheus 指标收集：

- **业务指标**：文档上传、编辑操作、批量修改、检索、认证
- **性能指标**：请求延迟、LLM 调用、数据库、缓存、搜索
- **系统指标**：应用信息、活跃用户、文档统计
- **错误指标**：错误总数和分类

配置 Grafana 仪表盘查看：
- 编辑请求成功率
- 定位准确率
- API 延迟分布（P50/P95/P99）
- 数据库查询性能
- LLM 调用统计和成本

## 常见问题

### Q: 如何提高定位准确率？

A: 
1. **启用向量检索**（推荐）：运行 `python scripts/add_vector_support.py`
2. 提供更具体的上下文（如章节名称）
3. 使用混合检索（BM25 + 向量 + RRF）

### Q: 向量检索的成本如何？

A:
- 存储：每个块约 6KB embedding 数据
- API：Qwen embedding API 约 ¥0.0001/1K tokens
- 1000 个块约需 ¥0.02 + 6MB 存储

### Q: 如何处理大文档（> 10MB）？

A: 
1. 系统会自动按段落切分
2. 使用增量索引策略
3. 启用 Block Version 引用模式（模式 B）

### Q: 支持哪些文档格式？

A: 
- MVP 阶段：Markdown (.md)、纯文本 (.txt)
- 后续支持：Word (.docx)、PDF

### Q: 如何保证并发安全？

A: 
- 使用乐观锁（CAS）机制
- confirm_token 包含版本号
- 冲突时自动重试或提示用户

### Q: 如何配置用户认证？

A:
1. 生成 SECRET_KEY：`python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. 在 `.env` 文件中设置 SECRET_KEY
3. 运行 `python3 scripts/create_admin_user.py` 创建管理员
4. 支持 JWT Token 和 API Key 两种认证方式



### Q: 协同编辑如何防止冲突？

A:
1. **块级编辑锁**：每个文档块独立加锁，不同用户可同时编辑不同块
2. **自动超时**：编辑锁 30 秒后自动过期，防止死锁
3. **冲突提示**：当锁被其他用户持有时，显示冲突提示和锁持有者
4. **实时同步**：编辑操作实时广播，所有用户看到最新状态

### Q: 协同编辑支持多少用户？

A:
- **当前版本**：每个文档建议 < 10 个用户（MVP 实现）
- **架构限制**：单实例部署，不支持水平扩展
- **性能表现**：WebSocket 消息延迟 < 100ms
- **扩展计划**：未来版本将支持分布式部署和更大规模协作

**重要提醒**：当前协同编辑是 MVP 实现，存在一些架构限制。详细分析请参考 [COLLABORATION_TECHNICAL_DEBT.md](COLLABORATION_TECHNICAL_DEBT.md)

## 路线图

### Phase 1: MVP（已完成）
- ✅ 核心编辑流程
- ✅ BM25 检索
- ✅ 版本管理
- ✅ 预览确认

### Phase 2: 体验优化（已完成）
- ✅ 混合检索（BM25 + 向量）
- ✅ RRF 融合算法
- ✅ 批量修改
- ✅ 用户认证系统
- ✅ 基础监控
- ✅ 意图澄清机制

### Phase 3: 架构升级（已完成）✅
- ✅ LangGraph 工作流重构
- ✅ 智能体架构（Intent/Router/Retrieval/Edit/Clarify）
- ✅ 工具层封装（DB/Search/LLM/Index）
- ⏳ 流式输出支持
- ⏳ 完整的 Langfuse 追踪

### Phase 4: 前端重构（计划中）
- 📋 适配新架构的前端界面
- 📋 实时工作流可视化
- 📋 智能体执行状态展示
- 📋 流式响应支持

### Phase 4: 协同编辑（已完成）✅
- ✅ 协同编辑（Redis + WebSocket 实时同步）
- ✅ 多用户实时协作
- ✅ 编辑锁机制防冲突
- ✅ 用户状态管理
- ✅ 光标位置同步

### Phase 5: 高级功能（未来）
- 📋 AI 主动建议
- 📋 深度学习重排模型（Cohere Rerank 或自训练）
- 📋 多语言支持
- 📋 操作转换（OT）算法

## 贡献指南

欢迎贡献代码！请遵循以下步骤：

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 联系方式

- 项目主页：https://github.com/minsib/document_mcp
- 问题反馈：https://github.com/minsib/document_mcp/issues
- 邮箱：minsibour@gmail.com

## 致谢

- [Qwen](https://github.com/QwenLM/Qwen) - 强大的大语言模型
- [LangChain](https://github.com/langchain-ai/langchain) - LLM 应用框架
- [Meilisearch](https://github.com/meilisearch/meilisearch) - 快速搜索引擎
- [pgvector](https://github.com/pgvector/pgvector) - PostgreSQL 向量扩展

---

**注意**：本项目仍在积极开发中，API 可能会有变动。生产环境使用前请充分测试。
