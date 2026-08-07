# 第8轮：生产部署、备份和回滚

只有第7轮验收允许上线后执行。

1. 先整理生产部署前置条件，不得把真实密钥提交仓库。
2. 配置：
   - Ubuntu LTS；
   - Docker Compose；
   - Nginx；
   - HTTPS；
   - Django DEBUG=False；
   - ALLOWED_HOSTS；
   - CSRF_TRUSTED_ORIGINS；
   - Secure/HttpOnly Cookie；
   - HSTS在HTTPS验证后启用。
3. 公网只开放80、443；SSH仅固定管理来源。
4. MySQL、Redis、Celery和Django内部端口不得暴露公网。
5. 非root运行容器。
6. 设置生产环境变量和密钥轮换流程。
7. 完成数据库备份、文件备份、30天保留和恢复演练。
8. 保留上一版本镜像并完成回滚演练。
9. 配置日志轮转、磁盘监控、任务失败监控和DNS解析异常监控。
10. 上线后执行冒烟测试。
11. 输出：
   - 部署记录；
   - 版本；
   - 数据库迁移；
   - 安全检查；
   - 备份恢复结果；
   - 回滚步骤；
   - 已知问题。

任何高危问题未关闭时不得上线。
