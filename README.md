# Document MCP

> 基于 FastAPI + LangGraph + Vue 的文档对话式编辑系统。

## 当前实现

这个仓库当前已经落地的是一套可运行的端到端系统，不再只是技术方案草稿。

- 后端：FastAPI + PostgreSQL + Redis + Meilisearch
- 工作流：LangGraph 驱动的意图解析、检索、规划、预览、确认、执行链路
- 前端：Vue 3 + Vite + Pinia，提供登录注册、文档管理、版本管理、Markdown 预览和对话编辑界面
- 认证：JWT 登录态，文档导出、版本查看、回滚等接口带用户归属校验
- 检索：BM25 + 向量检索 + RRF 融合
- 会话与记忆：会话消息落库，支持长期偏好、情景记忆、工作记忆
- 监控：Prometheus + Grafana + Alertmanager，已覆盖工作流、检索、LLM 调用等链路指标

## 现在支持什么

- 上传 `Markdown / TXT / DOCX`
- `PDF` 上传会被明确拒绝，当前未接入 PDF 解析
- 文档列表、正文导出、整篇 Markdown 保存为新版本
- 历史版本浏览与回滚
- 对话式编辑：预览、消歧、确认应用
- 批量编辑预览与确认应用
- 用户会话持久化
- 多层记忆检索与维护
- WebSocket 协同编辑基础能力
- Docker Compose 一键启动前后端和观测栈

## 前端交互

当前前端不是占位页面，已经接入主流程：

- 登录 / 注册后进入工作台
- 左侧为 VS Code 风格导航和文档 / 版本侧栏
- 中间默认展示 Markdown 转译后的预览
- 双击正文区域进入富文本编辑
- 支持日间 / 夜间主题切换
- 页面固定为视口高度，三栏内部独立滚动
- 右侧对话面板可直接发起编辑请求

## 技术栈

### 后端

- Python 3.11
- FastAPI
- SQLAlchemy
- PostgreSQL 15 + pgvector
- Redis 7
- Meilisearch 1.5
- LangGraph
- Qwen API

### 前端

- Vue 3
- Vite
- Pinia
- Vue Router
- Markdown-it
- Quill

### 可观测性

- Prometheus
- Grafana
- Alertmanager
- Langfuse（可选，配置后启用）

## 系统结构

```text
document_mcp/
├── app/                     # FastAPI 后端
│   ├── auth/                # 认证
│   ├── models/              # SQLAlchemy / Pydantic 模型
│   ├── nodes/               # 工作流节点
│   ├── services/            # LangGraph、检索、记忆、索引等服务
│   ├── monitoring/          # Prometheus 指标与健康检查
│   └── api/                 # 协同编辑等 API
├── frontend/                # Vue 前端
├── ops/                     # Prometheus / Grafana 配置
├── tests/                   # 结构化 pytest 测试
├── docker-compose.yml
└── README.md
```

## 快速启动

### 推荐：Docker Compose

先准备 `.env`，至少提供：

```bash
QWEN_API_KEY=your_qwen_api_key
MEILI_MASTER_KEY=changeme
SECRET_KEY=replace_me
```

然后直接启动：

```bash
docker compose up -d --build
```

默认端口：

- 前端：http://localhost:5173
- API 文档：http://localhost:8001/docs
- 健康检查：http://localhost:8001/health
- Metrics：http://localhost:8001/metrics
- Prometheus：http://localhost:9090
- Grafana：http://localhost:3000
- Alertmanager：http://localhost:9093

Grafana 默认账号：

- 用户名：`admin`
- 密码：`admin`

### 本地开发

1. 创建并激活虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate
```

2. 安装后端依赖

```bash
pip install -r requirements.txt
```

3. 启动基础服务

```bash
docker compose up -d postgres redis meilisearch
```

4. 启动后端

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

5. 启动前端

```bash
cd frontend
npm install
npm run dev
```

## 关键环境变量

```bash
DATABASE_URL=postgresql://docuser:docpass@localhost:5435/document_edit
REDIS_URL=redis://localhost:6382/0
MEILI_HOST=http://localhost:7702
MEILI_MASTER_KEY=changeme

QWEN_API_KEY=your_qwen_api_key
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-max-latest

SECRET_KEY=replace_me
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
```

前端开发时默认访问：

```bash
VITE_API_BASE_URL=http://localhost:8001
```

## API 示例

### 注册

```bash
curl -X POST "http://localhost:8001/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "demo",
    "email": "demo@example.com",
    "password": "password123"
  }'
```

### 登录

```bash
curl -X POST "http://localhost:8001/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "demo",
    "password": "password123"
  }'
```

### 上传文档

```bash
curl -X POST "http://localhost:8001/v1/docs/upload" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "title=项目需求文档" \
  -F "file=@document.docx"
```

### 发起对话式编辑

```bash
curl -X POST "http://localhost:8001/v1/chat/edit" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "doc_id": "YOUR_DOC_ID",
    "session_id": "optional-session-id",
    "message": "把技术架构那段改得更专业一些"
  }'
```

### 确认应用修改

```bash
curl -X POST "http://localhost:8001/v1/chat/confirm" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "YOUR_SESSION_ID",
    "doc_id": "YOUR_DOC_ID",
    "confirm_token": "YOUR_CONFIRM_TOKEN",
    "preview_hash": "YOUR_PREVIEW_HASH",
    "action": "apply"
  }'
```

## 可观测性

当前 Prometheus 指标已经覆盖这些链路：

- 文档上传 / 导出
- 编辑请求成功率与耗时
- 批量编辑次数与修改量
- 检索耗时、候选数、top score、消歧/重试结果
- 检索证据校验结果
- LLM 调用耗时、状态、token 用量
- LangGraph 工作流总耗时、节点耗时、路由次数、活跃运行数

指标定义在 [app/monitoring/metrics.py](app/monitoring/metrics.py)。

## 测试

仓库已经删除旧的散落测试脚本，统一改成 `tests/` 目录下的结构化 pytest 套件。

运行方式：

```bash
pytest -q
```

如果 API 不在默认地址：

```bash
TEST_API_BASE_URL=http://127.0.0.1:8001 pytest -q
```

当前测试覆盖：

- 注册 / 登录 / 当前用户
- Markdown 上传、DOCX 上传、PDF 拒绝
- 文档导出
- 编辑器整篇保存生成新版本
- 对话式编辑主链路
- 批量编辑预览与确认

详细说明见 [tests/README.md](tests/README.md)。

## 当前限制

- `PDF` 解析尚未接入
- 富文本编辑仍基于 Quill，属于 Markdown 预览上的编辑补充，不是完整所见即所得排版系统
- 协同编辑是单实例基础实现，更适合小规模场景
- 观测面已经打通，但具体召回质量评估仍以 Prometheus 指标为主，没有独立评测服务

## 相关文档

- [AUTH_GUIDE.md](AUTH_GUIDE.md)
- [BULK_EDIT_GUIDE.md](BULK_EDIT_GUIDE.md)
- [PROJECT_STATUS.md](PROJECT_STATUS.md)
- [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)
- [FINAL_SUMMARY.md](FINAL_SUMMARY.md)

## 开发命令

```bash
# 后端测试
pytest -q

# 前端构建
cd frontend && npm run build

# 启动完整栈
docker compose up -d --build

# 查看容器状态
docker compose ps
```

## 仓库地址

- GitHub: https://github.com/minsib/document_mcp
- Issues: https://github.com/minsib/document_mcp/issues
