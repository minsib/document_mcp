# 监控指南

## 功能概述

系统提供完整的监控和可观测性功能：
1. **健康检查**：检查系统和组件健康状态
2. **Prometheus 指标**：收集业务和性能指标
3. **请求日志**：记录所有 API 请求
4. **错误追踪**：自动记录和统计错误

## 健康检查

### 综合健康检查

**端点**: `GET /health/`

检查所有关键组件的健康状态。

**响应示例**:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-22T10:00:00Z",
  "version": "1.0.0",
  "checks": {
    "database": {
      "status": "up",
      "message": "Database is healthy",
      "response_time_ms": 5.23
    },
    "redis": {
      "status": "up",
      "message": "Redis is healthy",
      "response_time_ms": 2.15
    },
    "meilisearch": {
      "status": "up",
      "message": "Meilisearch is healthy",
      "response_time_ms": 8.45
    }
  }
}
```

**状态说明**:
- `healthy`: 所有组件正常
- `degraded`: 部分非关键组件异常
- `unhealthy`: 关键组件异常

### 存活检查

**端点**: `GET /health/liveness`

用于 Kubernetes liveness probe，检查应用是否还在运行。

**响应**:
```json
{
  "status": "alive"
}
```

### 就绪检查

**端点**: `GET /health/readiness`

用于 Kubernetes readiness probe，检查应用是否准备好接收流量。

**响应**:
```json
{
  "status": "ready"
}
```

或

```json
{
  "status": "not_ready",
  "reason": "Database connection failed"
}
```

## Prometheus 指标

### 访问指标

**端点**: `GET /metrics`

返回 Prometheus 格式的指标数据。

### 业务指标

#### 文档操作

- `documents_uploaded_total{user_id}`: 上传的文档总数
- `documents_exported_total{user_id}`: 导出的文档总数

#### 编辑操作

- `edits_requested_total{operation_type}`: 编辑请求总数
- `edits_applied_total{operation_type}`: 成功应用的编辑总数
- `edits_failed_total{operation_type, error_type}`: 失败的编辑总数

#### 批量修改

- `bulk_edits_requested_total`: 批量修改请求总数
- `bulk_edits_applied_total`: 成功应用的批量修改总数
- `bulk_changes_count`: 批量修改的变更数量分布

#### 检索操作

- `searches_performed_total{search_type}`: 执行的搜索总数
  - `search_type`: `bm25`, `vector`, `hybrid`
- `search_results_count`: 搜索结果数量分布

#### 认证操作

- `auth_login_attempts_total{status}`: 登录尝试总数
  - `status`: `success`, `failed`
- `auth_api_key_usage_total{status}`: API Key 使用总数
  - `status`: `success`, `failed`, `expired`

### 性能指标

#### 请求延迟

- `request_duration_seconds{method, endpoint, status_code}`: 请求处理时长

#### LLM 调用

- `llm_call_duration_seconds{model, operation}`: LLM API 调用时长
- `llm_calls_total{model, operation, status}`: LLM API 调用总数
- `llm_tokens_used_total{model, token_type}`: 使用的 token 总数

#### 数据库操作

- `db_query_duration_seconds{operation}`: 数据库查询时长
- `db_connections_active`: 活跃的数据库连接数

#### 缓存操作

- `cache_hits_total{cache_type}`: 缓存命中总数
- `cache_misses_total{cache_type}`: 缓存未命中总数

#### 搜索引擎

- `meilisearch_query_duration_seconds`: Meilisearch 查询时长
- `vector_search_duration_seconds`: 向量搜索时长

### 系统指标

- `app_info`: 应用信息（版本、环境等）
- `active_users`: 活跃用户数
- `total_documents`: 文档总数
- `total_blocks`: 块总数

### 错误指标

- `errors_total{error_type, endpoint}`: 错误总数

## 日志

### 日志格式

```
2024-01-22 10:00:00,123 - app.main - INFO - Request: POST /v1/docs/upload
2024-01-22 10:00:01,456 - app.main - INFO - Response: POST /v1/docs/upload - 200 (1.333s)
```

### 日志级别

- `DEBUG`: 调试信息
- `INFO`: 一般信息（请求、响应）
- `WARNING`: 警告信息
- `ERROR`: 错误信息（包含堆栈跟踪）
- `CRITICAL`: 严重错误

### 配置日志级别

在 `.env` 文件中设置：
```bash
LOG_LEVEL=INFO
```

## Prometheus 集成

### 1. 安装 Prometheus

```bash
# Docker
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus
```

### 2. 配置 Prometheus

创建 `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'document-edit-system'
    static_configs:
      - targets: ['host.docker.internal:8001']
    metrics_path: '/metrics'
```

### 3. 访问 Prometheus

打开浏览器访问: http://localhost:9090

### 4. 常用查询

#### 请求速率

```promql
rate(request_duration_seconds_count[5m])
```

#### 平均响应时间

```promql
rate(request_duration_seconds_sum[5m]) / rate(request_duration_seconds_count[5m])
```

#### P95 响应时间

```promql
histogram_quantile(0.95, rate(request_duration_seconds_bucket[5m]))
```

#### 错误率

```promql
rate(errors_total[5m])
```

#### LLM 调用成功率

```promql
rate(llm_calls_total{status="success"}[5m]) / rate(llm_calls_total[5m])
```

## Grafana 集成

### 1. 安装 Grafana

```bash
docker run -d \
  --name grafana \
  -p 3000:3000 \
  grafana/grafana
```

### 2. 添加 Prometheus 数据源

1. 访问 http://localhost:3000 (默认用户名/密码: admin/admin)
2. 添加数据源 → Prometheus
3. URL: http://prometheus:9090
4. 保存并测试

### 3. 导入仪表盘

创建仪表盘，添加以下面板：

#### 请求速率

```promql
sum(rate(request_duration_seconds_count[5m])) by (endpoint)
```

#### 响应时间

```promql
histogram_quantile(0.95, sum(rate(request_duration_seconds_bucket[5m])) by (le, endpoint))
```

#### 错误率

```promql
sum(rate(errors_total[5m])) by (error_type)
```

#### 活跃用户

```promql
active_users
```

#### 文档统计

```promql
total_documents
total_blocks
```

## 告警规则

### 1. 创建告警规则

创建 `alerts.yml`:

```yaml
groups:
  - name: document_edit_system
    interval: 30s
    rules:
      # 高错误率
      - alert: HighErrorRate
        expr: rate(errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value }} errors/sec"
      
      # 慢响应
      - alert: SlowResponse
        expr: histogram_quantile(0.95, rate(request_duration_seconds_bucket[5m])) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Slow response time detected"
          description: "P95 response time is {{ $value }}s"
      
      # 数据库连接池耗尽
      - alert: DatabaseConnectionPoolExhausted
        expr: db_connections_active > 18
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Database connection pool nearly exhausted"
          description: "Active connections: {{ $value }}/20"
      
      # 组件不健康
      - alert: ComponentUnhealthy
        expr: up{job="document-edit-system"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Service is down"
          description: "The service has been down for more than 1 minute"
```

### 2. 配置 Alertmanager

创建 `alertmanager.yml`:

```yaml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'email'

receivers:
  - name: 'email'
    email_configs:
      - to: 'admin@example.com'
        from: 'alertmanager@example.com'
        smarthost: 'smtp.example.com:587'
        auth_username: 'alertmanager@example.com'
        auth_password: 'password'
```

## Kubernetes 部署

### 1. 健康检查配置

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: document-edit-system
spec:
  containers:
  - name: app
    image: document-edit-system:latest
    ports:
    - containerPort: 8001
    livenessProbe:
      httpGet:
        path: /health/liveness
        port: 8001
      initialDelaySeconds: 30
      periodSeconds: 10
      timeoutSeconds: 5
      failureThreshold: 3
    readinessProbe:
      httpGet:
        path: /health/readiness
        port: 8001
      initialDelaySeconds: 10
      periodSeconds: 5
      timeoutSeconds: 3
      failureThreshold: 3
```

### 2. ServiceMonitor 配置

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: document-edit-system
spec:
  selector:
    matchLabels:
      app: document-edit-system
  endpoints:
  - port: http
    path: /metrics
    interval: 30s
```

## 监控最佳实践

### 1. 设置合理的告警阈值

- 错误率 > 1% 触发警告
- P95 响应时间 > 5s 触发警告
- 数据库连接池使用率 > 90% 触发告警

### 2. 定期检查指标

- 每天检查错误日志
- 每周检查性能趋势
- 每月检查资源使用情况

### 3. 建立监控仪表盘

创建包含以下内容的仪表盘：
- 请求速率和响应时间
- 错误率和错误类型分布
- 资源使用情况（CPU、内存、数据库连接）
- 业务指标（文档数、用户数、编辑数）

### 4. 日志管理

- 使用日志聚合工具（如 ELK、Loki）
- 设置日志保留策略
- 定期清理旧日志

## 故障排查

### 问题 1: 指标端点返回 404

**原因**: Prometheus 客户端未正确安装

**解决**:
```bash
pip install prometheus-client
```

### 问题 2: 健康检查失败

**原因**: 数据库或 Redis 连接失败

**解决**:
1. 检查数据库连接配置
2. 检查 Redis 连接配置
3. 查看详细错误信息

### 问题 3: 指标数据不更新

**原因**: Prometheus 抓取失败

**解决**:
1. 检查 Prometheus 配置
2. 检查网络连接
3. 查看 Prometheus 日志

## 参考资料

- [Prometheus 文档](https://prometheus.io/docs/)
- [Grafana 文档](https://grafana.com/docs/)
- [FastAPI 监控](https://fastapi.tiangolo.com/advanced/middleware/)
