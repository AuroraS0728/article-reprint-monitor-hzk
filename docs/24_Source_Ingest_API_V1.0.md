# Source Ingest API V1.0

本文件冻结后续浏览器插件使用的最小契约。插件唯一职责是通知后台“发现一篇原创文章”，不登录 Django、不创建检测批次、不指定 Platform、不调用 Search Provider，也不计算相似度。

## Endpoint

- Method: `POST`
- Path: `/api/v1/source-ingest/articles`
- Authentication: `Authorization: Bearer <SOURCE_TOKEN>`
- Content-Type: `application/json`
- Session/CSRF: 不使用 SessionAuthentication，不要求 CSRF Cookie

Source 由 Token 决定，请求体不能指定。

## Request

```json
{
  "title": "这一主线再掀涨停潮！低位方向正在成为新主角？",
  "author": "木木",
  "published_at": "2026-08-10T20:34:00+08:00",
  "original_url": "https://www.weeklyonstock.com/xxxx"
}
```

四个字段均必填。URL 必须属于 Token Source 的域名或子域名，并通过 HTTP(S)、凭据、localhost 和裸 IP 校验。

## Success responses

首次创建返回 HTTP 201；同一 canonical URL 的幂等提交或标题更新返回 HTTP 200。

```json
{
  "success": true,
  "data": {
    "created": true,
    "updated": false,
    "article_id": 123,
    "monitoring": true,
    "monitor_until": "2026-08-17T20:34:00+08:00",
    "retention_until": "2027-08-10T20:34:00+08:00"
  }
}
```

重复且无变化时不会延长监测期、不会创建第二篇 Article、不会重复调度。相同 URL 标题更新仍是同一 Article，并在原监测窗口内立即安排一次搜索。首次提交已超过 7 天的文章会录入为 COMPLETED。

## Error responses

- 401/403: Token 缺失、错误、停用、过期或 Source 停用。
- 400: 必填字段/时间/URL 无效，或 URL 不属于 Token Source。

错误体统一为 `success=false` 和 `error.code/error.message`。日志和审计禁止记录完整 Token、Authorization header 或 token hash。

## Token command

```text
python manage.py create_source_ingest_token --source WEEKLYONSTOCK --user operator --name weekly-browser
```

数据库只保存 token prefix 和 SHA-256；完整 Token 仅在创建时显示一次。
