# 生产环境部署清单

**系统版本**: v1.0.0  
**完成度**: 90%  
**状态**: 生产就绪 ✅

---

## 必须完成的步骤

### 1. 环境配置 ✅

- [ ] 复制 `.env.example` 到 `.env`
- [ ] 配置数据库连接 `DATABASE_URL`
- [ ] 配置 Redis 连接 `REDIS_URL`
- [ ] 配置 Meilisearch `MEILI_HOST` 和 `MEILI_MASTER_KEY`
- [ ] 配置 Qwen API `QWEN_API_KEY`
- [ ] **生成并配置 SECRET_KEY**（必须！）

```bash
# 生成 SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# 在 .env 中设置
SECRET_KEY=your-generated-secret-key-here
```

### 2. 数据库初始化 ✅

- [ ] 创建数据库
```bash
createdb document_edit
```

- [ ] 安装 pgvector 扩展
```bash
psql document_edit -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

- [ ] 运行所有迁移
```bash
alembic upgrade head
```

- [ ] 验证迁移成功
```bash
psql document_edit -c "\dt"  # 查看所有表
```

### 3. 向量检索启用 ✅

- [ ] 运行向量支持脚本
```bash
python3 scripts/add_vector_support.py
```

- [ ] 验证向量列存在
```bash
psql document_edit -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='block_versions' AND column_name='embedding';"
```

- [ ] （可选）为现有文档生成 embeddings
```bash
python3 scripts/regenerate_embeddings.py
```

### 4. 用户认证配置 ✅

- [ ] 创建管理员用户
```bash
python3 scripts/create_admin_user.py
```

- [ ] 测试登录
```bash
curl -X POST http://localhost:8001/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}'
```

- [ ] 验证 Token 有效
```bash
curl -X GET http://localhost:8001/v1/auth/me \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 5. 服务启动 ✅

- [ ] 启动 PostgreSQL（端口 5435）
- [ ] 启动 Redis（端口 6382）
- [ ] 启动 Meilisearch（端口 7702）
- [ ] 启动 API 服务（端口 8001）

```bash
# 开发环境
uvicorn app.main:app --reload --port 8001

# 生产环境
gunicorn app.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8001 \
  --timeout 120
```

### 6. 健康检查验证 ✅

- [ ] 综合健康检查
```bash
curl http://localhost:8001/health/
```

- [ ] Liveness probe
```bash
curl http://localhost:8001/health/liveness
```

- [ ] Readiness probe
```bash
curl http://localhost:8001/health/readiness
```

- [ ] Prometheus 指标
```bash
curl http://localhost:8001/metrics
```

---

## 推荐完成的步骤

### 7. HTTPS 配置 🔒

- [ ] 配置 Nginx 反向代理
- [ ] 申请 SSL 证书（Let's Encrypt）
- [ ] 配置 HTTPS 重定向
- [ ] 测试 HTTPS 访问

### 8. 监控配置 📊

- [ ] 安装 Prometheus
- [ ] 配置 Prometheus 抓取
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'document-edit-system'
    static_configs:
      - targets: ['localhost:8001']
    metrics_path: '/metrics'
```

- [ ] 安装 Grafana
- [ ] 添加 Prometheus 数据源
- [ ] 创建监控仪表盘
- [ ] 配置告警规则

### 9. 日志管理 📝

- [ ] 配置日志级别（生产环境建议 INFO）
- [ ] 配置日志轮转
- [ ] （可选）集成日志聚合工具（ELK/Loki）

### 10. 备份策略 💾

- [ ] 配置数据库自动备份
```bash
# 每天备份
0 2 * * * pg_dump document_edit > /backup/document_edit_$(date +\%Y\%m\%d).sql
```

- [ ] 配置 Redis 持久化（RDB + AOF）
- [ ] 测试备份恢复流程

### 11. 安全加固 🔐

- [ ] 配置防火墙规则
```bash
# 只开放必要端口
ufw allow 8001/tcp  # API
ufw allow 443/tcp   # HTTPS
```

- [ ] 配置 CORS 白名单（修改 `app/main.py`）
- [ ] 启用 Rate Limiting
- [ ] 定期更新依赖包
```bash
pip list --outdated
```

### 12. 性能优化 ⚡

- [ ] 配置数据库连接池大小
- [ ] 配置 Redis 最大内存
- [ ] 启用 Meilisearch 索引预热
- [ ] 配置 CDN（如果需要）

---

## 可选完成的步骤

### 13. Kubernetes 部署 ☸️

- [ ] 创建 Deployment 配置
- [ ] 配置 Service 和 Ingress
- [ ] 配置 ConfigMap 和 Secret
- [ ] 配置 HPA（水平自动扩展）
- [ ] 配置 PVC（持久化存储）

### 14. CI/CD 配置 🚀

- [ ] 配置 GitHub Actions / GitLab CI
- [ ] 自动化测试
- [ ] 自动化部署
- [ ] 自动化回滚

### 15. 高级功能 🎯

- [ ] 配置 Langfuse 追踪
- [ ] 集成重排模型（Cohere）
- [ ] 配置内容安全检查
- [ ] 配置用户反馈系统

---

## 验证清单

### 功能验证

- [ ] 用户注册和登录正常
- [ ] 文档上传正常
- [ ] 对话式编辑正常
- [ ] 批量修改正常
- [ ] 版本回滚正常
- [ ] 向量检索正常
- [ ] API Key 认证正常

### 性能验证

- [ ] 单次编辑延迟 < 3s (P95)
- [ ] 批量修改延迟 < 5s (100 处)
- [ ] 检索准确率 > 90%
- [ ] 并发支持 100+ 请求/秒

### 安全验证

- [ ] 未认证请求被拒绝
- [ ] Token 过期后无法访问
- [ ] API Key 禁用后无法使用
- [ ] 并发修改冲突检测正常
- [ ] 审计日志记录完整

### 监控验证

- [ ] 健康检查端点正常
- [ ] Prometheus 指标正常收集
- [ ] 错误日志正常记录
- [ ] 告警规则正常触发

---

## 故障排查

### 问题 1: 数据库连接失败

**检查**:
```bash
psql $DATABASE_URL -c "SELECT 1;"
```

**解决**:
- 检查数据库是否启动
- 检查连接字符串是否正确
- 检查防火墙规则

### 问题 2: Redis 连接失败

**检查**:
```bash
redis-cli -u $REDIS_URL ping
```

**解决**:
- 检查 Redis 是否启动
- 检查连接字符串是否正确
- 检查 Redis 密码

### 问题 3: Meilisearch 连接失败

**检查**:
```bash
curl $MEILI_HOST/health
```

**解决**:
- 检查 Meilisearch 是否启动
- 检查 Master Key 是否正确
- 检查网络连接

### 问题 4: 向量检索不工作

**检查**:
```bash
psql document_edit -c "SELECT COUNT(*) FROM block_versions WHERE embedding IS NOT NULL;"
```

**解决**:
- 运行 `python3 scripts/add_vector_support.py`
- 运行 `python3 scripts/regenerate_embeddings.py`
- 检查 Qwen API Key 是否有效

### 问题 5: 认证失败

**检查**:
- SECRET_KEY 是否配置
- Token 是否过期
- 用户是否存在

**解决**:
```bash
# 重新创建管理员
python3 scripts/create_admin_user.py

# 检查用户
psql document_edit -c "SELECT * FROM users;"
```

---

## 监控指标

### 关键指标

- **请求成功率**: > 99%
- **P95 响应时间**: < 3s
- **错误率**: < 1%
- **数据库连接池使用率**: < 80%
- **Redis 内存使用率**: < 80%

### 告警阈值

- 错误率 > 1% - 警告
- P95 响应时间 > 5s - 警告
- 数据库连接池 > 90% - 严重
- 服务不可用 > 1 分钟 - 严重

---

## 联系方式

- 项目主页：https://github.com/minsib/document_mcp
- 问题反馈：https://github.com/minsib/document_mcp/issues
- 邮箱：minsibour@gmail.com

---

## 参考文档

- [README.md](README.md) - 项目概述
- [AUTH_GUIDE.md](AUTH_GUIDE.md) - 认证指南
- [MONITORING_GUIDE.md](MONITORING_GUIDE.md) - 监控指南
- [VECTOR_SEARCH_SETUP.md](VECTOR_SEARCH_SETUP.md) - 向量检索设置
- [BULK_EDIT_GUIDE.md](BULK_EDIT_GUIDE.md) - 批量修改指南
- [FINAL_SUMMARY.md](FINAL_SUMMARY.md) - 完整总结

---

**祝部署顺利！** 🎉
