# 文章转载监测系统 V1.0

正式生产系统的增量实现。已包含 Django/DRF、Vue、Celery/Redis/MySQL、Docker Compose、Nginx、三角色会话登录、原创文章录入与安全 Excel 导入、平台/域名配置、审计日志、固定平台检测兼容能力，以及基于 Source API 的全网转载检索。

新链路支持固定原创来源、只保存哈希的 Source Token、90% 确定性标题相似度、动态网站发现、canonical URL 去重、7 天自适应监测、1 年数据保留和动态多 Sheet Excel 导出。转载记录表示“曾经转载”的历史事实；页面后来 404、410 或不可访问不会删除记录或减少统计。

浏览器插件不在本轮范围内，尚未开发。旧固定平台能力继续保留；未验证的平台仍明确保存为“—/ADAPTER_NOT_VALIDATED”。

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

创建来源接入 Token（完整 Token 只显示一次）：

```powershell
docker compose exec web python manage.py create_source_ingest_token --source WEEKLYONSTOCK --user operator --name weekly-browser
```

Search Provider 通过环境变量配置。当前实现 `SEARCH_PROVIDER=brave`，并从 `BRAVE_SEARCH_API_KEY` 读取密钥；密钥为空时 SearchRun 明确记录 `SEARCH_PROVIDER_NOT_CONFIGURED`，不会产生模拟搜索结果。

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
- 当前不得上线：真实 Search API 尚需有效账户/Key 及服务条款确认，第 7 轮遗留的镜像漏洞与正式上线门禁也必须关闭。

审查结论与开发计划见 `docs/01_文档一致性审查报告_V1.0.md`、`docs/02_威胁建模_V1.0.md`、`docs/03_实施计划_V1.0.md`。
全网搜索、Source API 和动态 Excel 契约见 `docs/23_Global_Repost_Search_V1.0.md`、`docs/24_Source_Ingest_API_V1.0.md`、`docs/25_Excel_Export_V1.0.md`。
