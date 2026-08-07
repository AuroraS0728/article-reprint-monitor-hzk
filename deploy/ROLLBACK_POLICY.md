# V1.0 backup, retention, and rollback policy

The application schedules a private MySQL logical backup at 01:30 Asia/Shanghai and retention cleanup at 02:00 Asia/Shanghai. A failed `mysqldump` is recorded as a failed backup; it is never reported as a successful backup.

- Database backup files: 30 days in private storage only.
- Generated Excel files: 30 days. The report metadata and source snapshot remain for one year, so an administrator can regenerate a new report version after file cleanup.
- Task-failure and email-delivery logs: 30 days.
- Original articles, repost records, and status statistics: one year. Deletion skips records still protected by referenced data and records that outcome in the maintenance run; it does not force-delete relational history.

Production releases must tag the currently running image before rollout (for example `repost-monitor:prod-YYYYMMDD`). The deployment host must retain the immediately preceding tagged production image until the replacement has passed health checks and rollback approval. Image cleanup must not delete that rollback tag.

Only administrators can request a backup or cleanup through the API. Both requests create audit entries. Credentials are supplied from deployment environment variables and are never included in command logs, database records, frontend responses, or Git.
