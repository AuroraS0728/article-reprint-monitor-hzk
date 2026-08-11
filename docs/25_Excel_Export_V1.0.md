# Excel Export V1.0

## API

`GET /api/v1/repost-monitor/export.xlsx`

需要已登录用户，只读读取当前数据库，不触发搜索、不等待 SearchRun、不修改业务数据。支持 `start_date`、`end_date`、`article_id`、`author`、`monitoring_status`、`site_domain` 和 `has_repost=true|false`。无筛选时导出尚在保留期内的全部数据。

导出开始时固定一个 `export_as_of`，所有 Sheet 只读取该时点以前已创建的有效 RepostRecord。默认文件名 `文章转载监测_YYYYMMDD_HHmm.xlsx`；有完整日期范围时为 `文章转载监测_YYYYMMDD-YYYYMMDD.xlsx`。

## Workbook

Sheet 顺序：

1. 数据
2. 实际发现过转载的网站动态 Sheet
3. 总统计
4. 统计汇总

数据 Sheet 一篇 Article 一行，包含发布时间、作者、标题、原文 URL、监测状态/截止时间、历史转载网站数/链接数和动态网站列。同网站多 URL 时单元格显示第一条 `URL √（共N条）`，网站 Sheet 保留所有 URL。

总统计使用 `√` 表示曾经转载。统计汇总只给出文章数、历史转载网站数、链接数及“在已转载文章中的覆盖比例”，不虚构全网网站分母或全网转载率。

## 历史与安全

`REMOVED`、404、410 或当前不可访问的记录仍输出 URL、Hyperlink 和 `√`，网站 Sheet 仅在“当前链接状态”显示已删除/不可访问。Excel 值以 `= + - @` 等字符开头时转为安全文本；超链接使用 openpyxl Hyperlink 对象，不使用 `HYPERLINK()` 公式。Sheet 名清理非法字符、限制 31 字符并自动处理重名。
