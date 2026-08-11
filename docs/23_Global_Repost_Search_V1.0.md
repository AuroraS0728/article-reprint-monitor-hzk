# Global Repost Search V1.0

## 目标与边界

原创来源 `Source` 与动态发现的转载网站严格分离。正式来源代码为 `WEEKLYONSTOCK`；旧 `Platform`、`DetectionBatch` 和固定平台适配器继续兼容，但全网搜索不要求预建 Platform。

本轮没有开发 Chrome/Edge 浏览器插件，也不实现验证码绕过、自动登录、代理池或搜索引擎页面抓取。生产检索只允许使用合法 Search API。

## 判定规则

每篇文章至少执行带双引号的精确短语查询和原标题普通查询。标题经过 Unicode NFKC、HTML 实体还原、大小写、空白及常用标点归一化；可确认的网站尾缀会在比较时移除。普通标题相似度必须大于等于 `SEARCH_SIMILARITY_THRESHOLD`（默认 90）；短标题要求归一化后完全一致。

原创来源所有子域名及 canonical 原文 URL 必须排除。明确早于原创发布时间、超出容差的候选不能自动确认。

## 历史事实

`RepostRecord` 存在且 `is_valid=True` 表示曾经确认转载。后续搜索未返回、URL 404/410、域名失效或 `availability_status=REMOVED` 都只影响可用状态，不删除历史记录、不降低链接数和网站数。只有 Article 到达 `retention_until` 后，清理任务才可整体删除 Article、SearchRun 和 RepostRecord。

## Provider 与错误

统一接口为 `SearchProvider.search()`，返回 `SearchCandidate`。当前 provider 注册名为 `brave`，端点和认证方式已按 Brave 官方 Web Search API 文档核对。密钥只来自环境变量，不写入数据库、日志或前端。

未配置 Provider/Key 时创建 ERROR SearchRun，错误码 `SEARCH_PROVIDER_NOT_CONFIGURED`。429、超时和 5xx 记录 ERROR 并退避重试；Article 保持 ACTIVE，已有转载记录不受影响。

## 调度

新文章立即调度一次搜索，之后按 15 分钟、30 分钟、1 小时、2 小时、4 小时、8 小时执行；8 小时后以首次监测时间为锚点每 12 小时执行，即 20 小时、32 小时、44 小时……。Celery Beat 每 5 分钟扫描 `next_search_at`，仅下发当前到期文章；不为 7 天生命周期创建大量 ETA 任务。每篇文章使用 Redis 并发锁，监测到 `published_at + 7 days`；清理到 `published_at + 365 days`。
