# Codex执行顺序

1. `01_review_and_scaffold.md`
2. `02_auth_article_platform.md`
3. `03_detection_scheduler_matrix.md`
4. `04_platform_adapters.md`
5. `05_reports_excel_email.md`
6. `06_manual_ops_logs.md`
7. `07_full_test_acceptance.md`
8. `08_production_deploy.md`

执行规则：

- 每次只发送一轮指令。
- 上一轮未启动成功或测试未通过，不进入下一轮。
- 每轮结束后要求Codex提交真实测试输出、未完成项和安全风险。
- 平台适配轮必须在本机取得真实验证证据，不能用模拟结果代替。
- 生产部署轮必须最后执行。
