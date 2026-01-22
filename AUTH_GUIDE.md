# 用户认证指南

## 功能概述

系统支持两种认证方式：
1. **JWT Token 认证**：适合 Web 应用和移动应用
2. **API Key 认证**：适合服务端集成和自动化脚本

## 快速开始

### 1. 运行数据库迁移

```bash
# 添加认证表
python3 scripts/add_vector_support.py  # 如果还没运行
python3 -m alembic upgrade head
```

### 2. 创建管理员用户

```bash
python3 scripts/create_admin_user.py
```

按提示输入：
- 用户名
- 邮箱
- 全名（可选）
- 密码

### 3. 测试认证

```bash
# 登录获取 token
curl -X POST http://localhost:8001/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}'
```

## 认证方式

### 方式 1: JWT Token 认证

#### 1.1 注册用户

```bash
curl -X POST http://localhost:8001/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com",
    "password": "password123",
    "full_name": "Test User"
  }'
```

#### 1.2 登录

```bash
curl -X POST http://localhost:8001/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "password": "password123"
  }'
```

响应：
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

#### 1.3 使用 Token 访问 API

```bash
curl -X POST http://localhost:8001/v1/docs/upload \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -F "title=测试文档" \
  -F "content=# 测试内容"
```

#### 1.4 刷新 Token

```bash
curl -X POST http://localhost:8001/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "YOUR_REFRESH_TOKEN"
  }'
```

### 方式 2: API Key 认证

#### 2.1 创建 API Key

首先使用 JWT Token 登录，然后创建 API Key：

```bash
curl -X POST http://localhost:8001/v1/auth/api-keys \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "key_name": "My API Key",
    "expires_days": 90
  }'
```

响应：
```json
{
  "key_id": "uuid",
  "key_name": "My API Key",
  "key_prefix": "sk-abc...",
  "api_key": "sk-abcdef1234567890...",
  "is_active": true,
  "expires_at": "2024-04-22T10:00:00Z",
  "created_at": "2024-01-22T10:00:00Z"
}
```

**重要**：`api_key` 只在创建时返回一次，请妥善保存！

#### 2.2 使用 API Key 访问 API

```bash
curl -X POST http://localhost:8001/v1/docs/upload \
  -H "X-API-Key: sk-abcdef1234567890..." \
  -F "title=测试文档" \
  -F "content=# 测试内容"
```

#### 2.3 列出 API Keys

```bash
curl -X GET http://localhost:8001/v1/auth/api-keys \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### 2.4 禁用/启用 API Key

```bash
curl -X PATCH http://localhost:8001/v1/auth/api-keys/{key_id}/toggle \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

#### 2.5 删除 API Key

```bash
curl -X DELETE http://localhost:8001/v1/auth/api-keys/{key_id} \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## API 端点

### 认证相关

| 端点 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/v1/auth/register` | POST | 注册新用户 | 否 |
| `/v1/auth/login` | POST | 用户登录 | 否 |
| `/v1/auth/refresh` | POST | 刷新 Token | 否 |
| `/v1/auth/me` | GET | 获取当前用户信息 | 是 |
| `/v1/auth/me` | PUT | 更新当前用户信息 | 是 |
| `/v1/auth/api-keys` | POST | 创建 API Key | 是 |
| `/v1/auth/api-keys` | GET | 列出 API Keys | 是 |
| `/v1/auth/api-keys/{key_id}` | DELETE | 删除 API Key | 是 |
| `/v1/auth/api-keys/{key_id}/toggle` | PATCH | 启用/禁用 API Key | 是 |

### 文档相关（需要认证）

| 端点 | 方法 | 说明 | 认证 |
|------|------|------|------|
| `/v1/docs/upload` | POST | 上传文档 | 是 |
| `/v1/docs/{id}/export` | GET | 导出文档 | 是 |
| `/v1/chat/edit` | POST | 对话式编辑 | 是 |
| `/v1/chat/confirm` | POST | 确认修改 | 是 |
| `/v1/chat/bulk-edit` | POST | 批量修改 | 是 |
| `/v1/chat/bulk-confirm` | POST | 确认批量修改 | 是 |
| `/v1/docs/{id}/revisions` | GET | 获取版本列表 | 是 |
| `/v1/docs/{id}/rollback` | POST | 回滚版本 | 是 |

## Python 客户端示例

### 使用 JWT Token

```python
import requests

class DocumentClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.access_token = None
        self.refresh_token = None
    
    def login(self, username: str, password: str):
        """登录"""
        response = requests.post(
            f"{self.base_url}/v1/auth/login",
            json={"username": username, "password": password}
        )
        response.raise_for_status()
        
        data = response.json()
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
    
    def _get_headers(self):
        """获取请求头"""
        if not self.access_token:
            raise Exception("未登录")
        return {"Authorization": f"Bearer {self.access_token}"}
    
    def upload_document(self, title: str, content: str):
        """上传文档"""
        response = requests.post(
            f"{self.base_url}/v1/docs/upload",
            headers=self._get_headers(),
            data={"title": title, "content": content}
        )
        response.raise_for_status()
        return response.json()

# 使用示例
client = DocumentClient("http://localhost:8001")
client.login("admin", "password")
result = client.upload_document("测试文档", "# 测试内容")
print(result)
```

### 使用 API Key

```python
import requests

class DocumentClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
    
    def _get_headers(self):
        """获取请求头"""
        return {"X-API-Key": self.api_key}
    
    def upload_document(self, title: str, content: str):
        """上传文档"""
        response = requests.post(
            f"{self.base_url}/v1/docs/upload",
            headers=self._get_headers(),
            data={"title": title, "content": content}
        )
        response.raise_for_status()
        return response.json()

# 使用示例
client = DocumentClient(
    "http://localhost:8001",
    "sk-abcdef1234567890..."
)
result = client.upload_document("测试文档", "# 测试内容")
print(result)
```

## 安全最佳实践

### 1. 密码安全

- ✅ 最小长度 6 个字符
- ✅ 使用 bcrypt 加密存储
- ✅ 不在日志中记录密码
- 🔴 建议：生产环境要求更强的密码策略

### 2. Token 安全

- ✅ Access Token 有效期 24 小时（可配置）
- ✅ Refresh Token 有效期 7 天
- ✅ 使用 HTTPS 传输
- 🔴 建议：生产环境使用更短的有效期

### 3. API Key 安全

- ✅ 使用 SHA-256 哈希存储
- ✅ 只在创建时返回完整 key
- ✅ 支持设置过期时间
- ✅ 支持禁用/删除
- 🔴 建议：定期轮换 API Key

### 4. SECRET_KEY 配置

**重要**：生产环境必须修改 SECRET_KEY！

```bash
# 生成随机 SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

在 `.env` 文件中设置：
```
SECRET_KEY=your-generated-secret-key-here
```

## 权限控制

### 用户角色

- **普通用户** (`is_superuser=False`)
  - 只能访问自己的文档
  - 可以创建、编辑、删除自己的文档
  - 可以管理自己的 API Keys

- **超级用户** (`is_superuser=True`)
  - 可以访问所有文档
  - 可以管理所有用户
  - 可以查看系统统计信息

### 文档权限

当前实现：
- 用户只能访问自己上传的文档
- 通过 `user_id` 字段关联

未来扩展：
- 文档共享
- 团队协作
- 细粒度权限控制

## 故障排除

### 问题 1: 401 Unauthorized

**原因**：Token 无效或已过期

**解决**：
1. 检查 Token 是否正确
2. 使用 refresh token 刷新
3. 重新登录

### 问题 2: 403 Forbidden

**原因**：权限不足

**解决**：
1. 检查用户是否被禁用
2. 检查是否需要超级用户权限
3. 检查文档所有权

### 问题 3: API Key 不工作

**原因**：
- API Key 已过期
- API Key 已被禁用
- API Key 格式错误

**解决**：
1. 检查 API Key 是否有效
2. 检查过期时间
3. 创建新的 API Key

### 问题 4: 无法创建用户

**原因**：
- 用户名已存在
- 邮箱已被注册
- 密码不符合要求

**解决**：
1. 使用不同的用户名
2. 使用不同的邮箱
3. 使用更强的密码

## 监控和审计

### 用户活动

- `last_login_at`: 最后登录时间
- `last_used_at`: API Key 最后使用时间

### 审计日志

所有文档操作都记录在 `edit_operations` 表中，包含：
- 操作用户 (`user_id`)
- 操作时间 (`created_at`)
- 操作类型 (`op_type`)
- 操作详情 (`rationale`, `patch_json`)

## 测试

### 测试认证功能

```bash
# 运行认证测试
pytest tests/test_auth.py -v
```

### 手动测试

```bash
# 1. 注册用户
curl -X POST http://localhost:8001/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "test", "email": "test@example.com", "password": "test123"}'

# 2. 登录
curl -X POST http://localhost:8001/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "test", "password": "test123"}'

# 3. 获取用户信息
curl -X GET http://localhost:8001/v1/auth/me \
  -H "Authorization: Bearer YOUR_TOKEN"

# 4. 创建 API Key
curl -X POST http://localhost:8001/v1/auth/api-keys \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"key_name": "Test Key", "expires_days": 30}'

# 5. 使用 API Key 上传文档
curl -X POST http://localhost:8001/v1/docs/upload \
  -H "X-API-Key: YOUR_API_KEY" \
  -F "title=Test" \
  -F "content=# Test"
```

## 配置选项

在 `.env` 文件中配置：

```bash
# 安全配置
SECRET_KEY=your-secret-key-here
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440  # 24 小时

# 密码策略（未来扩展）
MIN_PASSWORD_LENGTH=6
REQUIRE_UPPERCASE=false
REQUIRE_NUMBERS=false
REQUIRE_SPECIAL_CHARS=false
```

## 参考资料

- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [JWT.io](https://jwt.io/)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
