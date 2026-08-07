# Article Reprint Monitor V1.0

## 1. What this repository is

这是“文章转载监测系统”V1.0 的开发仓库。

系统最终采用 B/S 架构：

- 用户通过浏览器访问 Vue 3 管理后台；
- Django/DRF 提供后端接口；
- Celery 与 Redis 执行每小时转载检测；
- MySQL 保存原创文章、平台、任务、转载记录和报表版本；
- 后端生成简洁 Excel 日报、周报；
- 周报通过 SMTP 自动发送。

## 2. Repository layout

```text
article-reprint-monitor/
├─ AGENTS.md
├─ README.md
├─ docs/                # PRD、架构、数据库、API、测试、安全等正式文档
├─ prototype/           # 页面原型
├─ samples/             # Excel样例、历史数据、已知原创/转载链接
├─ prompts/             # 分阶段交给Codex的任务指令
├─ backend/             # Django/DRF/Celery
├─ frontend/            # Vue 3 + TypeScript
├─ deploy/              # Docker Compose、Nginx、部署脚本
└─ tests/               # 跨模块测试与验收测试
```

## 3. Important files

- `AGENTS.md`：给 Codex 的长期项目规则。
- `README.md`：给人和 Codex 看的项目入口、结构和运行说明。
- `docs/02_产品需求文档_PRD_V1.0.docx`：业务需求主依据。
- `samples/文章转载监测系统_目标报表样例_V1.0_简洁版.xlsx`：Excel输出样式基准。
- `samples/known_original_and_reprints.txt`：已知原创文章和转载链接样本。
- `prompts/`：按顺序执行的开发任务。

## 4. Local development

项目骨架完成后，Codex必须把真实命令补充到这里，包括：

```bash
# 后端环境
# 前端环境
# MySQL / Redis
# Django migration
# Create admin
# Run backend
# Run Celery worker
# Run Celery beat
# Run frontend
# Run tests
```

在项目骨架尚未生成前，不得虚构可运行命令。

## 5. Environment variables

真实密钥只能放在本机或服务器的 `.env` 中，不得提交。

仓库应提供 `.env.example`，至少包含：

```env
DJANGO_SECRET_KEY=
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=
MYSQL_DATABASE=
MYSQL_USER=
MYSQL_PASSWORD=
MYSQL_HOST=mysql
MYSQL_PORT=3306
REDIS_URL=redis://redis:6379/0
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASSWORD=
DEFAULT_FROM_EMAIL=
TIME_ZONE=Asia/Shanghai
MOCK_MODE=false
```

## 6. Development order

按 `prompts/00_execution_order.md` 依次执行。

每轮完成后先检查：

- 实际修改文件；
- 迁移文件；
- 测试结果；
- 是否存在写死或模拟数据；
- 安全风险；
- 下一轮前置条件。

未经审核不要直接跳到生产部署。
