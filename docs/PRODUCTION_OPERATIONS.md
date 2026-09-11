# 生产可观测性、限流与审计操作手册

本手册对应 `v0.6.5`。目标是让故障能定位、滥用能抑制、关键写操作能追责；它不替代 HTTPS 反向代理、WAF、集中日志平台或多可用区基础设施。

## 1. 请求链路与结构化日志

API 接受符合 `A-Za-z0-9._:-` 且不超过 128 字符的 `X-Request-ID`，否则生成 UUID；响应始终返回最终 Request ID。生产默认输出单行 JSON，字段包括时间、级别、Logger、Request ID、HTTP 方法、路由模板、状态码和耗时。

日志刻意不记录 Authorization、Cookie、原始请求体、问答内容和原始客户端 IP。路由指标使用 `/api/v1/jobs/{job_id}` 这类模板，不使用真实 ID，避免 Prometheus 标签基数失控。

推荐在反向代理生成 Request ID，并将应用标准输出收集到 Loki、OpenSearch、Splunk 或企业日志平台。查询一次失败请求时，以响应 `X-Request-ID` 串联代理和 API 日志。

## 2. Prometheus

`docker-compose.server.yml` 启动 Prometheus 并仅将 `9090` 绑定到服务器 `127.0.0.1`。`deploy/init_env.sh` 同时生成：

- `.env.server` 中的 `METRICS_BEARER_TOKEN`，供 API 校验；
- `data/secrets/metrics_token`，只读挂载给 Prometheus 采集器。

检查采集：

```bash
docker compose --env-file .env.server -f docker-compose.server.yml ps
curl -fsS http://127.0.0.1:9090/-/ready
```

主要指标：

- `rag_http_requests_total{method,route,status}`：请求量和错误率；
- `rag_http_request_duration_seconds`：路由延迟直方图；
- `rag_http_requests_in_progress{method}`：当前并发；
- `rag_rate_limit_rejections_total{policy}`：被限流请求数。
- `rag_dependency_up{dependency}`：数据库、任务队列、限流后端、向量索引和远程生成模型就绪状态。

`observability/alerts.yml` 预置 API Down、依赖不可用、5xx 比例、P95 延迟和限流突增规则。Prometheus 会评估规则，但不会自行通知；生产必须连接 Alertmanager 或现有告警平台，并按真实压测结果调整阈值。

Compose 固定 API 为一个 Uvicorn 进程，因此 Python 指标注册表是一致的。如果改为多个进程，需按 Prometheus Python Client 的 multiprocess 模式配置独立共享目录和聚合注册表，不能直接增加 `--workers`。

## 3. OpenTelemetry

默认关闭。已有 OTLP/HTTP Collector 时配置：

```dotenv
OTEL_ENABLED=true
OTEL_SERVICE_NAME=enterprise-rag-api
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces
```

重启 API 后会批量导出 FastAPI Server Span，并排除健康和指标采集路径。实现不采集请求/响应 Header 和 Body，避免把 Token、Cookie 或用户问题送到 Trace 后端。

当前 Compose 不捆绑 Collector，防止在未决定后端和数据保留策略时静默堆积遥测数据。可对接 OpenTelemetry Collector，再转发到 Tempo、Jaeger 或企业 APM。

## 4. Redis 令牌桶限流

生产强制 `RATE_LIMIT_BACKEND=redis`。每个 OIDC 用户按 `tenant_id + user_id` 隔离，键只保存 SHA-256 摘要；Redis Lua 脚本原子完成补充、扣减和过期。默认每 60 秒配额：

- Chat 60 次；
- 上传/删除 10 次；
- 查询类接口 300 次；
- 反馈 30 次。

超限返回 `429`、`Retry-After`；Redis 故障返回 `503`，生产不会静默绕过保护。成功响应返回 `X-RateLimit-Limit` 和 `X-RateLimit-Remaining`。

上述是应用用户级保护。公网入口还应在反向代理/WAF 限制连接数、未认证 IP、最大请求体和超时，防止攻击流量在完成 OIDC 校验前耗尽资源。

## 5. 防篡改审计链

上传新文档、删除文档和写入反馈会在同一数据库事务中追加审计事件。每个租户有独立递增序号；每条事件包含前序哈希，并用 `AUDIT_HMAC_KEY` 签名。审计失败会使对应业务事务回滚。

`auditor` 或 `knowledge-admin` 可以查询：

```text
GET /api/v1/audit-events?limit=100
GET /api/v1/audit-events/verify
```

运维人员也可以离线校验：

```bash
docker compose --env-file .env.server -f docker-compose.server.yml exec rag-api \
  python scripts/verify_audit_chain.py --tenant company-a
```

退出码 `0` 表示链完整，`1` 表示检测到断链或内容变化。不要随意轮换或丢失 `AUDIT_HMAC_KEY`，否则历史事件无法用同一密钥复算。需要轮换时，应先实现密钥版本字段并保留旧密钥。

这是一条“tamper-evident（可检测篡改）”链，不是数据库内的绝对不可变存储。高合规环境应定时把事件和最新链头导出到独立账户的对象锁/WORM 存储，并让 SIEM 对校验失败、序号异常和敏感管理动作告警。

## 6. 发布检查

```bash
python -m pytest tests -q
python evaluation/run_eval.py \
  --database /tmp/rag-evaluation.db \
  --dataset evaluation/golden_portfolio.jsonl \
  --tenant demo-company \
  --bootstrap examples/complex_enterprise_knowledge_base.md \
  --output /tmp/rag-evaluation-report.json \
  --thresholds evaluation/thresholds.json \
  --fail-on-regression
bash -n deploy/init_env.sh deploy/deploy.sh deploy/logs.sh
```

部署后至少验证：OIDC 401/403、限流 429、指标采集 Up、五条告警规则已加载、审计链校验为真、日志中不存在 Token/问题正文，并实际演练一次 PostgreSQL 恢复。

容器使用 `/health/ready` 做就绪检查，下游数据库、任务队列、限流 Redis 或向量索引不可用时返回 `503`。健康响应还会主动探测远程模型并通过 `generator_status=ready|fallback|extractive` 暴露状态；默认允许有引用的抽取式降级，设置 `LLM_REQUIRED=true` 后模型不可用也会返回 `503`。`/health/live` 只确认 API 进程仍能响应，适合编排系统的存活探针。
