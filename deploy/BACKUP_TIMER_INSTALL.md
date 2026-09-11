# Backup timer operational patch

This patch installs a daily online backup for the PostgreSQL metadata database
and the Qdrant `enterprise_knowledge` collection. It does not back up the
development-mode Keycloak H2 database.

From the project root on the Linux server:

```bash
chmod 750 deploy/backup_runtime.sh deploy/install_backup_timer.sh
bash deploy/install_backup_timer.sh
sudo systemctl start enterprise-rag-backup.service
sudo systemctl show enterprise-rag-backup.service -p Result -p ExecMainStatus
sudo journalctl -u enterprise-rag-backup.service -n 100 --no-pager
sudo systemctl enable --now enterprise-rag-backup.timer
systemctl list-timers enterprise-rag-backup.timer --no-pager
```

Successful backup directories are stored under `backups/automatic/backup-*`.
The script retains 14 days and only removes matching backup directories beneath
that validated path.
