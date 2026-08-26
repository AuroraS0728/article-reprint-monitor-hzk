from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime
from io import BytesIO
from typing import Any

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.worksheet import Worksheet

from apps.reposts.models import ContentRelation, RepostRecord

from .models import OwnedChannel
from .reading_metrics import fetch_reading_metrics

EXCEL_DATETIME_FORMAT = "yyyy-mm-dd hh:mm"
EXCEL_DATE_FORMAT = "yyyy-mm-dd"
INVALID_SHEET_CHARACTERS = re.compile(r"[:\\\\/?*\[\]]")


def safe_excel_text(value: object) -> str:
    """Prevent a database value from becoming an Excel formula on export."""

    text = "" if value is None else str(value)
    return f"'{text}" if text.lstrip().startswith(("=", "+", "-", "@")) else text


def _excel_datetime(value: date | datetime | None) -> date | datetime | None:
    if isinstance(value, datetime) and timezone.is_aware(value):
        return timezone.localtime(value).replace(tzinfo=None)
    return value


def _record_url(record: RepostRecord) -> str:
    return record.canonical_url or record.normalized_url or record.final_url or record.original_url


def _set_hyperlink(cell: Any, url: str) -> None:
    cell.value = safe_excel_text(url)
    cell.hyperlink = url
    cell.style = "Hyperlink"


def _format_sheet(sheet: Worksheet, widths: Iterable[int]) -> None:
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if isinstance(cell.value, datetime):
                cell.number_format = EXCEL_DATETIME_FORMAT
            elif isinstance(cell.value, date):
                cell.number_format = EXCEL_DATE_FORMAT


def _sheet_name(value: str, used_names: set[str]) -> str:
    base = INVALID_SHEET_CHARACTERS.sub("_", value).strip(" '") or "未命名渠道"
    base = base[:31]
    candidate = base
    suffix_number = 2
    while candidate.casefold() in {item.casefold() for item in used_names}:
        suffix = f"_{suffix_number}"
        candidate = f"{base[: 31 - len(suffix)]}{suffix}"
        suffix_number += 1
    used_names.add(candidate)
    return candidate


def build_owned_reading_workbook(*, export_as_of: datetime | None = None) -> tuple[bytes, datetime]:
    """Export owned publications separately from external repost monitoring.

    Reading values are fetched from the configured owned-channel metric provider
    when available. Unknown values remain ``—`` rather than being treated as 0.
    """

    export_as_of = export_as_of or timezone.now()
    channels = list(OwnedChannel.objects.filter(is_active=True).order_by("code", "id"))
    records = list(
        RepostRecord.objects.filter(
            is_valid=True,
            content_relation=ContentRelation.OWNED,
            created_at__lte=export_as_of,
            article__created_at__lte=export_as_of,
        )
        .select_related("article", "owned_channel")
        .order_by("article__published_at", "article__published_date", "id")
    )
    records_by_article_channel: dict[tuple[int, int], list[RepostRecord]] = defaultdict(list)
    records_by_channel: dict[int, list[RepostRecord]] = defaultdict(list)
    for record in records:
        if record.owned_channel_id is None:
            continue
        records_by_article_channel[(record.article_id, record.owned_channel_id)].append(record)
        records_by_channel[record.owned_channel_id].append(record)
    reading_metrics, provider_status = fetch_reading_metrics(records, as_of=export_as_of)

    article_ids = sorted({record.article_id for record in records})
    articles = {record.article_id: record.article for record in records}
    workbook = Workbook()
    data_sheet = workbook.active
    data_sheet.title = "数据"
    data_sheet.append(
        [
            "发布时间",
            "标题",
            "作者",
            "总阅读量",
            *[channel.name for channel in channels],
        ]
    )
    for article_id in article_ids:
        article = articles[article_id]
        article_counts = [
            metric.reading_count
            for channel in channels
            for record in records_by_article_channel.get((article_id, channel.id), [])
            if (metric := reading_metrics.get(record.id)) and metric.reading_count is not None
        ]
        data_sheet.append(
            [
                _excel_datetime(article.published_at) or article.published_date,
                safe_excel_text(article.title),
                safe_excel_text(article.author or article.author_department),
                sum(article_counts) if article_counts else "—",
                *[
                    (
                        sum(
                            metric.reading_count
                            for record in records_by_article_channel.get((article_id, channel.id), [])
                            if (metric := reading_metrics.get(record.id)) and metric.reading_count is not None
                        )
                        if any(
                            (metric := reading_metrics.get(record.id)) and metric.reading_count is not None
                            for record in records_by_article_channel.get((article_id, channel.id), [])
                        )
                        else "—" if records_by_article_channel.get((article_id, channel.id)) else ""
                    )
                    for channel in channels
                ],
            ]
        )
    _format_sheet(data_sheet, [19, 52, 18, 14, *([18] * len(channels))])

    used_names = {"数据", "总统计", "说明"}
    for channel in channels:
        sheet = workbook.create_sheet(_sheet_name(channel.name, used_names))
        sheet.append(["发布时间", "标题", "作者", "链接", "阅读量", "状态", "渠道说明"])
        for record in records_by_channel[channel.id]:
            article = record.article
            metric = reading_metrics.get(record.id)
            sheet.append(
                [
                    _excel_datetime(article.published_at) or article.published_date,
                    safe_excel_text(article.title),
                    safe_excel_text(article.author or article.author_department),
                    "",
                    metric.reading_count if metric and metric.reading_count is not None else "—",
                    metric.status if metric else "未查到",
                    safe_excel_text(channel.notes),
                ]
            )
            _set_hyperlink(sheet.cell(sheet.max_row, 4), _record_url(record))
        _format_sheet(sheet, [19, 52, 18, 52, 14, 20, 36])

    summary = workbook.create_sheet("总统计")
    summary.append(["自有渠道", "已识别分发文章数", "链接数", "可用阅读量数", "导出时点"])
    for channel in channels:
        channel_records = records_by_channel[channel.id]
        available_count = sum(
            1
            for record in channel_records
            if (metric := reading_metrics.get(record.id)) and metric.reading_count is not None
        )
        summary.append(
            [
                safe_excel_text(channel.name),
                len({record.article_id for record in channel_records}),
                len({(record.article_id, _record_url(record)) for record in channel_records}),
                available_count,
                _excel_datetime(export_as_of),
            ]
        )
    summary.append(
        [
            "合计",
            len(article_ids),
            len({(record.article_id, _record_url(record)) for record in records}),
            sum(
                1
                for record in records
                if (metric := reading_metrics.get(record.id)) and metric.reading_count is not None
            ),
            _excel_datetime(export_as_of),
        ]
    )
    _format_sheet(summary, [28, 22, 14, 18, 19])

    notes = workbook.create_sheet("说明")
    notes.append(["项目", "说明"])
    for row in [
        ("报表边界", "本文件只包含已确认的自有渠道分发，不包含外部转载；外部转载请下载“转载检测”报表。"),
        ("渠道列", "渠道和工作表由管理员配置及实际已识别的自有分发记录动态生成，不使用固定模拟列。"),
        ("阅读量", f"当前阅读量状态：{provider_status}。未知值显示“—”，不会将未知数据当作 0。"),
        ("链接", "链接使用真实 Excel 超链接对象；所有外部文本都进行了公式注入防护。"),
        ("导出时点", _excel_datetime(export_as_of)),
    ]:
        notes.append([safe_excel_text(row[0]), row[1] if isinstance(row[1], datetime) else safe_excel_text(row[1])])
    _format_sheet(notes, [18, 100])

    output = BytesIO()
    workbook.save(output)
    return output.getvalue(), export_as_of
