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

# 启动 API 服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

7. **访问 API 文档**

打开浏览器访问：http://localhost:8000/docs

## 使用示例

### 0. 用户认证

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

## 核心功能详解

### 1. 智能定位

系统使用三层检索策略确保定位准确：

- **BM25 检索**：擅长关键词匹配（如"第 3 章"、"交付时间"）
- **向量检索**：擅长语义理解（如"关于钱的内容" → "付款条款"）
- **重排模型**：进一步优化排序，提升准确率

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
├── app/
│   ├── main.py                 # FastAPI 应用入口
│   ├── config.py               # 配置管理
│   ├── models/                 # 数据模型
│   │   ├── database.py         # SQLAlchemy 模型
│   │   └── schemas.py          # Pydantic 模型
│   ├── api/                    # API 路由
│   │   ├── docs.py             # 文档管理 API
│   │   ├── chat.py             # 对话编辑 API
│   │   └── revisions.py        # 版本管理 API
│   ├── services/               # 业务逻辑
│   │   ├── splitter.py         # 文档分块
│   │   ├── retriever.py        # 混合检索
│   │   ├── workflow.py         # LangGraph 工作流
│   │   └── cache.py            # 缓存管理
│   ├── nodes/                  # LangGraph 节点
│   │   ├── intent_parser.py    # 意图解析
│   │   ├── retriever.py        # 检索节点
│   │   ├── verifier.py         # 验证节点
│   │   ├── planner.py          # 计划生成
│   │   ├── preview.py          # 预览生成
│   │   └── apply.py            # 执行节点
│   ├── utils/                  # 工具函数
│   │   ├── markdown.py         # Markdown 处理
│   │   ├── hash.py             # 哈希计算
│   │   └── validation.py       # 校验工具
│   └── db/                     # 数据库操作
│       ├── connection.py       # 连接管理
│       └── dao.py              # 数据访问层
├── alembic/                    # 数据库迁移
│   ├── versions/
│   └── env.py
├── tests/                      # 测试
│   ├── test_api.py
│   ├── test_workflow.py
│   └── test_retriever.py
├── docs/                       # 文档
│   ├── design.md               # 设计文档
│   └── api.md                  # API 文档
├── .env.example                # 环境变量示例
├── requirements.txt            # Python 依赖
├── alembic.ini                 # Alembic 配置
├── Dockerfile                  # Docker 镜像
├── docker-compose.yml          # Docker Compose
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

详细说明请参考 [VECTOR_SEARCH_SETUP.md](VECTOR_SEARCH_SETUP.md)

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

详细说明：[MONITORING_GUIDE.md](MONITORING_GUIDE.md)

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

详见 [AUTH_GUIDE.md](AUTH_GUIDE.md)

## 路线图

### Phase 1: MVP（已完成）
- ✅ 核心编辑流程
- ✅ BM25 检索
- ✅ 版本管理
- ✅ 预览确认

### Phase 2: 体验优化（已完成）
- ✅ 混合检索（BM25 + 向量）
- ✅ 批量修改
- ✅ 用户认证系统
- ✅ 基础监控
- 🚧 多轮对话上下文
- 🚧 用户反馈学习

### Phase 3: 性能优化（部分完成）
- ✅ 多级缓存
- ✅ 增量索引
- ⏳ Block Version 引用模式
- ⏳ 分布式部署

### Phase 4: 高级功能（未来）
- 📋 协同编辑
- 📋 AI 主动建议
- 📋 自定义重排模型
- 📋 多语言支持

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
