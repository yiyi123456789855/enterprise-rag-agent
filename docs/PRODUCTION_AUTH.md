# 生产认证与授权接入

## 目标

生产请求只信任身份提供商签发的 Access Token。`tenant_id`、`user_id`、`departments` 和 `roles` 由服务端校验 JWT 后生成，客户端提交的同名业务字段不会改变权限范围。

## 1. 在身份提供商中注册 API

创建受保护 API/Resource Server，并记录：

- Issuer：Token 中 `iss` 的精确值，包括可能存在的结尾 `/`；
- Audience：Token 中供本服务使用的 `aud`；
- JWKS URL：公开签名公钥集合地址；
- 签名算法：推荐 `RS256`，不要使用 `none` 或 HMAC 共享密钥算法。

服务只允许 `RS*`、`PS*`、`ES*` 和 `EdDSA` 等非对称算法。生产 Issuer 和 JWKS URL 必须使用 HTTPS。

## 2. 配置 Claim 和角色

让 Access Token 至少包含：

```json
{
  "sub": "employee-123",
  "iss": "https://id.company.com/realms/main",
  "aud": "enterprise-rag-api",
  "exp": 1780000000,
  "tenant_id": "company-a",
  "departments": ["研发部"],
  "roles": ["document-editor"]
}
```

角色定义：

| 角色 | 权限 |
|---|---|
| 普通已认证用户 | 问答、查看自己的会话、提交自己的反馈 |
| `document-editor` | 上传公开文档或自己部门范围内的文档 |
| `knowledge-admin` | 上传任意部门文档、删除文档、查看租户指标 |
| `auditor` | 查看当前租户指标 |

若现有 Claim 名不同，可通过 `OIDC_TENANT_CLAIM`、`OIDC_DEPARTMENTS_CLAIM` 和 `OIDC_ROLES_CLAIM` 映射。当前版本要求这些 Claim 位于 JWT 顶层。

## 3. 配置服务

复制服务器环境示例，然后替换示例身份地址：

```bash
cp .env.server.example .env.server
chmod 600 .env.server
```

关键配置：

```dotenv
APP_ENV=production
AUTH_MODE=oidc
OIDC_ISSUER=https://id.company.com/realms/main
OIDC_AUDIENCE=enterprise-rag-api
OIDC_JWKS_URL=https://id.company.com/realms/main/protocol/openid-connect/certs
OIDC_ALGORITHMS=RS256
OIDC_TENANT_CLAIM=tenant_id
OIDC_DEPARTMENTS_CLAIM=departments
OIDC_ROLES_CLAIM=roles
```

配置缺失、仍为 `example.com`、使用 HTTP、使用对称/未知算法，或生产环境选择 legacy 模式时，应用会拒绝启动。

## 4. 接口验证

普通问答：

```bash
curl -sS http://127.0.0.1:8000/api/v1/chat \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"question":"差旅住宿标准是多少？","top_k":5}'
```

即使请求中伪造另一个 `tenant_id` 或 `departments`，服务也会使用 Token 中的范围。使用无效 Token、错误 `aud`、错误 `iss` 或过期 Token 应返回 401；缺少角色应返回 403；跨租户和跨部门资源统一返回 404，减少资源枚举信息。

## 5. 运行生产权限验收

准备三个短期 Token：本租户研发管理员、本租户市场用户、另一租户研发用户，然后执行：

```bash
export ACCESS_TOKEN='...'
export SALES_ACCESS_TOKEN='...'
export OTHER_TENANT_ACCESS_TOKEN='...'

python evaluation/run_server_acceptance.py \
  --base-url http://127.0.0.1:8000 \
  --tenant company-a \
  --output evaluation/server_acceptance_report.json
```

## 6. 前端上线边界

仓库内置页面允许手工粘贴短期 Token，适合验收，不是完整企业登录页面。正式前端应使用 Authorization Code + PKCE 或 BFF：不内置 Client Secret、不把 Token 写入 localStorage、不记录 Authorization Header，并配合 HTTPS、CSP、短有效期 Token 与身份提供商的撤销策略。
