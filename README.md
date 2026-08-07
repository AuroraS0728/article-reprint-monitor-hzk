# 文章转载监测系统 V1.0

正式生产系统的开发骨架。已包含 Django/DRF、Vue、Celery/Redis/MySQL、Docker Compose、Nginx、三角色会话登录、原创文章录入与安全 Excel 导入、平台/域名配置、审计日志，以及第三轮的检测批次、状态矩阵、统计服务和日报/周报状态快照基础。

当前仍未包含任何正式平台适配器或真实外部采集。未验证的平台执行检测时会明确保存为“—/ADAPTER_NOT_VALIDATED”，绝不会伪装成 0 或 1。

## 本机启动

前置条件：Docker Desktop Compose v2、Git。复制环境变量后启动：

```powershell
Copy-Item .env.example .env
docker compose up --build
```

首次启动完成后，另开终端创建本机管理员：

```powershell
docker compose exec web python manage.py createsuperuser
```

访问：前端 `http://localhost:5173`；健康检查 `http://localhost:8000/api/v1/health/`；OpenAPI `http://localhost:8000/api/docs/`；Django 管理端 `http://localhost:8000/admin/`。

可选 Nginx 入口：`docker compose --profile nginx up nginx`，访问 `http://localhost:8080`。MySQL 和 Redis 没有宿主机端口映射。

## 本地质量检查

在 backend 容器中运行：

```powershell
docker compose exec web pytest
docker compose exec web ruff check .
docker compose exec web black --check .
docker compose exec web mypy apps config
docker compose exec web python manage.py check --deploy --settings=config.settings.production
docker compose exec frontend pnpm lint
docker compose exec frontend pnpm build
```

上线前还必须完成 `pip-audit`、`pnpm audit --audit-level=high`、密钥扫描、真实 MySQL Migration/恢复演练，以及文档规定的采集与安全测试。

## 安全与数据状态

- 模拟数据：未使用；测试账号仅由 pytest fixture 创建。
- 正式页面硬编码数据：无；文章、平台、批次、矩阵和统计均从 Django API 读取。测试适配器仅位于 `backend/tests/fixtures/`，生产代码不会导入它。
- 新增敏感配置：仅 `.env.example` 占位符，无真实密钥。
- 当前不得上线：统一安全外部请求客户端、平台真实验证、正式适配器、正式报表生成、端到端测试以及全部上线门禁尚未完成。

审查结论与开发计划见 `docs/01_文档一致性审查报告_V1.0.md`、`docs/02_威胁建模_V1.0.md`、`docs/03_实施计划_V1.0.md`。
