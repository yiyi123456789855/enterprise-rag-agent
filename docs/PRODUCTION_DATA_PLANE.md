# 生产数据与任务平面

## 架构

```text
FastAPI
  ├─ PostgreSQL：文档元数据、任务状态、切片、会话与反馈
  ├─ Qdrant：带租户/部门 Payload 的向量
  ├─ 共享上传暂存卷：只保存等待处理的原始文件
  └─ Valkey：Celery Broker、结果和任务锁
                         │
                         ▼
                  Celery ingestion-worker
                    解析 → 切片 → Embedding → PostgreSQL/Qdrant
```

API 以 1 MiB 分块写入暂存目录并在写入过程中执行大小限制，不把几十 MiB 文档放进进程内存或消息队列。Celery 消息只包含 `job_id`、`document_id`、文件名和共享路径。

## 可靠性语义

- 文档内容哈希和任务在同一个数据库事务中声明，并发重复上传复用同一个文档和任务。
- Worker 使用 late acknowledgement；进程异常退出后，未确认消息会重新投递。
- 每个任务使用带 TTL 的 Valkey 分布式锁，避免重复投递导致并发处理同一文档。
- 失败使用指数退避，默认最多重试 3 次。
- 默认软超时 840 秒、硬超时 900 秒，避免单个损坏文档永久占用 Worker。
- 成功、最终失败或分发失败后删除暂存正文；任务状态和错误保留在 PostgreSQL。
- `scripts/requeue_stale_ingestion.py` 可以恢复 API 发消息前崩溃或 Worker 强杀后遗留的任务。

## 故障恢复

重新投递超过一小时没有更新的任务：

```bash
docker compose --env-file .env.server -f docker-compose.server.yml exec rag-api \
  python scripts/requeue_stale_ingestion.py --older-than-seconds 3600
```

阈值不能小于 `CELERY_TIME_LIMIT`，避免把仍在正常处理的任务重复投递。

备份 PostgreSQL：

```bash
bash deploy/backup_postgres.sh
```

从 SQLite 迁移元数据时，目标 PostgreSQL 必须为空：

```bash
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite /path/to/rag.db \
  --database-url "$DATABASE_URL"
python scripts/reindex.py --batch-size 32
```

迁移的数据库写入在一个事务中完成；任何表失败都会整体回滚。迁移前仍应保留 SQLite 文件备份。

## 部署边界

当前 Compose 是单 Docker 主机方案，API 和 Worker 通过同一个命名卷读取暂存文件。如果扩展到多台主机或 Kubernetes，应把 `UploadStore` 替换为 S3/MinIO，并使用托管 PostgreSQL、托管 Valkey 与 Qdrant 集群。不要把 NFS 当作无限期原文仓库；原始文件应设置生命周期、加密和访问审计。

生产备份至少同时覆盖 PostgreSQL 与 Qdrant，并定期执行恢复演练。只生成备份而没有验证恢复，不应视为具备灾难恢复能力。
