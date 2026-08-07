# 第1轮：文档审查与项目骨架

请开始第1轮开发。

1. 阅读根目录 `AGENTS.md`、`README.md`。
2. 阅读 docs 中的 PRD、架构、数据库、API、采集、UI、Excel、测试、安全和部署文档。
3. 检查 prototype 和 samples。
4. 输出文档一致性审查报告，列出：
   - 已确认需求；
   - 冲突；
   - 尚无法确定的内容；
   - 建议默认值；
   - 风险；
   - 不得写死的数据清单。
5. 设计仓库目录、Django应用划分、Vue模块、数据库模块和开发阶段计划。
6. 初始化：
   - Django + DRF
   - Vue 3 + TypeScript + Vite
   - Celery + Redis
   - MySQL
   - Docker Compose
   - Nginx开发配置
   - pytest、Ruff、Black、mypy、pre-commit
   - ESLint与TypeScript检查
7. 创建 `.env.example` 和 `.gitignore`，不得写入真实密钥。
8. 创建可用的本机启动说明。
9. 创建基础健康检查接口和前端基础布局，但不得写死业务统计数据。
10. 运行基础测试和静态检查。

本轮交付：
- 审查报告；
- 实施计划；
- 项目骨架；
- Docker开发环境；
- README实际启动命令；
- 健康检查；
- 基础测试；
- 风险报告。

在我审核前，不要实现平台专用适配器。
