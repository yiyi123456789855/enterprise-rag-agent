# Enterprise RAG 生产化落地总结

更新时间：2026-09-11

仓库版本：`v0.6.5`

当前成熟度：单机生产试运行版

## 1. 最终结果

项目已从演示型本地 RAG，升级为一套可在单台 GPU 服务器上长期运行、可认证、可隔离、可观测、可备份并可验收的企业知识库系统。

当前已经闭环：

- 使用 BGE-M3、BGE Reranker、Qdrant 和本地 Qwen/vLLM 完成真实检索与生成。
- 使用 OIDC/JWT 建立可信身份，并在检索前执行租户和部门 ACL。
- 将业务元数据从 SQLite 迁移到 PostgreSQL，将同步入库升级为 Valkey + Celery。
- 提供引用校验、证据不足拒答、敏感信息拒答和提示注入防护。
- 提供结构化日志、Prometheus 指标、Grafana 看板和告警状态日志。
- 建立 PostgreSQL/Qdrant、Keycloak 和异地加密包的备份与恢复流程。
- 通过 31/31 项服务器端验收，并形成并发 2 与并发 4 的容量基线。

“可生产试运行”不等于“已经高可用”。当前适合受控的公司内部试点；多机容灾、集中告警和正式密钥托管仍属于下一阶段。

## 2. 端到端业务流程

### 文档入库

1. 用户携带 OIDC Access Token 上传 PDF、DOCX、TXT 或 Markdown。
2. API 从已验证的 Token 提取租户、用户、部门和角色，忽略浏览器自行填写的身份字段。
3. 上传文件以有界流方式写入暂存区，计算 SHA-256，并通过数据库约束去重。
4. Celery Worker 从 Valkey 获取任务，解析文档、按标题和页码切块。
5. 文档、任务和 Chunk 元数据写入 PostgreSQL。
6. BGE-M3 生成向量，写入 Qdrant；向量载荷包含租户和部门 ACL。
7. 成功后文档进入 `ready`；失败任务保留原因，可重试和审计。

### 问答检索

1. API 验证 JWT 签名、签发者、受众和有效期。
2. 安全策略先拦截敏感信息、凭据窃取和提示注入请求。
3. 多轮会话根据上一轮问题改写指代不完整的 Query。
4. Qdrant Dense 检索和 BM25 检索仅在当前租户与授权部门内召回。
5. RRF 融合候选后，由 BGE CrossEncoder 二阶段重排。
6. 证据相关性、问题词覆盖率和关键实体覆盖率共同决定回答或拒答。
7. Qwen 生成答案；引用不合法时回退到抽取式回答，仍无可靠证据时拒答。
8. 返回答案、引用、候选分数、各阶段耗时和会话 ID。

## 3. 生产部署形态

经过验证的单机部署使用以下边界：

| 组件 | 运行方式 | 监听范围 | 作用 |
|---|---|---|---|
| FastAPI | systemd | `127.0.0.1:8010` | Web UI 与业务 API |
| Celery Worker | systemd | 无对外端口 | 文档解析、切块和向量化 |
| Qwen/vLLM | systemd | `127.0.0.1:8001` | OpenAI 兼容生成接口 |
| PostgreSQL | Docker Compose | Docker 内网 | 业务与 Keycloak 持久数据 |
| Valkey | Docker Compose | Docker 内网 | 入库任务和限流状态 |
| Qdrant | Docker Compose | `127.0.0.1:6333` | 向量索引 |
| Keycloak | Docker | `127.0.0.1:8081` | OIDC 身份提供方 |
| Prometheus | Docker | `127.0.0.1:9090` | 指标采集与规则计算 |
| Grafana | Docker | `127.0.0.1:3000` | 运行监控看板 |

所有管理端口只监听回环地址。无域名场景使用 SSH 隧道访问，不应直接暴露到 `0.0.0.0`：

```bash
ssh -N \
  -L 8010:127.0.0.1:8010 \
  -L 8081:127.0.0.1:8081 \
  -L 3000:127.0.0.1:3000 \
  your-user@your-server
```

## 4. 身份、授权与隔离验证

Keycloak 已配置：

- `tenant_id` 固定或按组织映射。
- `departments` 来自 Group Membership Mapper。
- `roles` 来自 Realm Role Mapper。
- API Audience 映射到 `enterprise-rag-api`。
- 管理、文档编辑和审计角色分别授权。

实际验证覆盖：

- 无 Token 请求返回 401。
- 无效或过期 Token 被拒绝。
- 研发部可以检索研发私有文档。
- 市场部看不到研发私有文档。
- 另一个租户看不到当前租户文档。
- 删除文档后，对应向量不可继续检索。

Keycloak 已从开发用 H2 迁移到 PostgreSQL，并完成生产模式启动、原用户密码登录、Token Claims 和 Audience 验证。旧 H2 实例仅作为限时回滚资产保留，不作为当前数据源。

## 5. 数据迁移和可靠性

业务数据已从 SQLite 迁移到 PostgreSQL，迁移范围包括：

| 表 | 迁移时样本行数 |
|---|---:|
| documents | 1 |
| ingestion_jobs | 2 |
| chunks | 58 |
| conversations | 334 |
| feedback | 9 |
| audit_events | 13 |

迁移后重新构建 Qdrant 索引，并在 PostgreSQL + Celery + Redis + Qdrant 组合上重新运行完整验收。

可靠性措施包括：

- PostgreSQL 有界连接池和事务边界。
- Celery late-ack、任务超时、指数退避、分布式锁和陈旧任务重投。
- 文档 SHA-256 幂等去重。
- 上传、删除、反馈写入 HMAC 哈希审计链。
- LLM 超时、重试、熔断和抽取式降级。
- 健康接口分别报告数据库、队列、限流、向量索引和生成器状态。

## 6. 验收结果

最终服务器验收：

```text
passed = 31
failed = 0
total = 31
average = 362.40 ms
p50 = 372.10 ms
p95 = 753.73 ms
```

验收覆盖 18 条黄金问题和生产控制项，包括：

- 制度问答、数字型规则、复杂条件和引用。
- 无答案问题、未来预测、敏感信息和提示注入拒答。
- 多轮追问和指代消解。
- 反馈指标写入。
- 私有文档上传、去重、ACL、跨租户隔离和删除一致性。

## 7. 容量与资源基线

测试环境：RTX 4090 24GB、Qwen2.5-3B-Instruct、`max-num-seqs=2`、`gpu-memory-utilization=0.35`。

| 场景 | 请求 | 成功率 | 吞吐 | 平均延迟 | P95 | 最大延迟 |
|---|---:|---:|---:|---:|---:|---:|
| 持续并发 2 | 20 | 100% | 2.955 req/s | 675.01 ms | 1175.39 ms | 1230.12 ms |
| 突发并发 4 | 20 | 100% | 3.446 req/s | 1118.58 ms | 1782.46 ms | 2057.20 ms |

突发并发 4 时观测到 GPU 100%、显存峰值 14208 MiB、温度峰值 84°C、功耗峰值 338W。建议单机持续并发按 2 规划，短时突发可到 4；扩大流量前重新压测。

系统内存诊断显示 62 GiB 中约 44 GiB 可用、Swap 几乎未使用，因此没有主机内存压力。当前不实施“把 Worker 模型移到 CPU”的优化，避免用入库延迟换取暂时不需要的显存空间。

## 8. 可观测性和告警

已落地：

- `/internal/metrics` 使用独立 Bearer Token 保护；无 Token 返回 401。
- Prometheus 成功采集 API，数据库、队列、限流、向量索引和生成器依赖值均为 1。
- Grafana 看板展示 API 状态、请求速率、5xx、P95、依赖状态、并发和限流拒绝。
- 已验证看板已作为 `observability/grafana-dashboard.json` 纳入仓库。
- 告警规则覆盖 API Down、5xx 升高、依赖不可用、P95 升高和限流突增。
- 告警状态轮询器把 firing/resolved 转换为结构化 systemd journal 日志。
- 人工注入的告警自检已验证 firing 和 resolved 两个事件均被记录。

当前告警只记录到服务器日志，尚未连接企业 IM、邮件、PagerDuty 或集中 SIEM。

## 9. 备份与恢复

已验证的备份层次：

1. PostgreSQL 自定义格式 Dump + Qdrant Collection Snapshot，每日执行，包含 SHA-256。
2. Keycloak PostgreSQL 数据库独立备份，每日执行。
3. 使用专用 OpenPGP 公钥生成异地加密包；服务器仅保存公钥，私钥离线保管。
4. 加密包复制到服务器外后再次校验 SHA-256，并执行解密、解包和内部校验演练。

恢复演练已验证 PostgreSQL 隔离恢复后的 documents、jobs、chunks、conversations、feedback 和 audit_events 行数；Keycloak 也完成独立 PostgreSQL 启动与原用户登录验证。

禁止提交或上传：`.env*` 实际配置、Access Token、Qdrant/Valkey/PostgreSQL 密码、指标 Token、OpenPGP 私钥、备份包、数据库、模型缓存和运行日志。

## 10. 仓库与服务器资产边界

本仓库包含通用代码、配置示例、数据平面、OIDC、监控规则、备份脚本、告警日志脚本、测试和文档。

以下资产是在目标服务器上按实际路径和服务名生成的部署实例，不应原样提交：

- `/etc/systemd/system/enterprise-rag-*.service` 与 `.timer`。
- 真实 `.env.server`、`.env.qwen` 和运行密钥。
- Keycloak 数据迁移/回滚容器及数据库 Dump。
- Prometheus/Grafana 持久数据。
- 自动备份、异地加密包、恢复临时库和发布证据目录。

仓库内的 systemd 文件是模板，安装脚本会替换用户、用户组和项目绝对路径。

## 11. 尚未完成的生产能力

按优先级排列：

1. 进行 7 天公司内部试点，记录真实问题命中率、拒答率、P95 和用户反馈。
2. 将告警接入企业通知渠道，并验证通知抑制、恢复通知和责任人轮值。
3. 将 `.env` 中的长期密钥迁移到 Vault、云 Secret Manager 或等价系统。
4. 将上传暂存区迁移到 S3/MinIO，解除 API 与 Worker 必须共享本机磁盘的限制。
5. 为 PostgreSQL、Valkey、Qdrant、Keycloak 和 API 设计多节点高可用及故障切换。
6. 增加 OCR、表格结构化解析、更大的人审黄金集和数据漂移评估。
7. 在有域名时增加 HTTPS 反向代理、正式证书、WAF 和统一登录入口。

完成第 1 项后，可从“单机生产试运行”升级为“受控内部生产”；完成第 2 至第 5 项后，才适合宣称具备完整企业生产韧性。
