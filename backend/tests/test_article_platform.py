from datetime import date
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.articles.models import Article
from apps.audit.models import OperationLog


@pytest.fixture
def administrator(db: object) -> User:
    return User.objects.create_user(username="admin", password="safe-test-password", role=Role.ADMIN)


@pytest.fixture
def operator(db: object) -> User:
    return User.objects.create_user(username="operator-two", password="safe-test-password", role=Role.OPERATOR)


@pytest.fixture
def viewer(db: object) -> User:
    return User.objects.create_user(username="viewer", password="safe-test-password", role=Role.VIEWER)


def client_for(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_article_permissions_duplicates_and_audit(operator: User, viewer: User) -> None:
    payload = {"title": "测试文章", "published_date": "2026-08-06"}
    assert client_for(viewer).post("/api/v1/articles", payload, format="json").status_code == 403
    created = client_for(operator).post("/api/v1/articles", payload, format="json")
    assert created.status_code == 201
    assert Article.objects.count() == 1
    assert client_for(operator).post("/api/v1/articles", payload, format="json").status_code == 400
    assert client_for(viewer).get("/api/v1/articles").status_code == 200
    assert OperationLog.objects.filter(action_type="ARTICLE_CREATE").exists()


@pytest.mark.django_db
def test_article_read_requires_login_and_supports_date_filter_and_archive(operator: User) -> None:
    client = client_for(operator)
    first = client.post("/api/v1/articles", {"title": "第一篇", "published_date": "2026-08-01"}, format="json")
    second = client.post("/api/v1/articles", {"title": "第二篇", "published_date": "2026-08-15"}, format="json")
    assert APIClient().get("/api/v1/articles").status_code == 403
    response = client.get("/api/v1/articles?published_date_from=2026-08-10&published_date_to=2026-08-20")
    assert [item["id"] for item in response.json()] == [second.json()["id"]]
    assert client.delete(f"/api/v1/articles/{first.json()['id']}").status_code == 204
    assert Article.objects.get(pk=first.json()["id"]).status == "ARCHIVED"
    restored = client.post(
        "/api/v1/articles/bulk-status",
        {"article_ids": [first.json()["id"]], "status": "ACTIVE"},
        format="json",
    )
    assert restored.status_code == 200
    assert Article.objects.get(pk=first.json()["id"]).status == "ACTIVE"


def make_xlsx(*, title: object = "导入文章") -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["原创文章标题", "原创发布日期", "备注"])
    sheet.append([title, date(2026, 8, 6), "导入测试"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.mark.django_db
def test_excel_import_rejects_formula_and_imports_valid_article(operator: User) -> None:
    client = client_for(operator)
    formula_file = SimpleUploadedFile(
        "article.xlsx",
        make_xlsx(title="=1+1"),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    preview = client.post("/api/v1/article-imports", {"file": formula_file}, format="multipart")
    assert preview.status_code == 201
    assert preview.json()["data"]["failed_rows"] == 1
    valid_file = SimpleUploadedFile(
        "article.xlsx", make_xlsx(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    preview = client.post("/api/v1/article-imports", {"file": valid_file}, format="multipart")
    assert preview.status_code == 201
    confirmed = client.post(f"/api/v1/article-imports/{preview.json()['data']['id']}/confirm", {}, format="json")
    assert confirmed.status_code == 200
    assert Article.objects.filter(title="导入文章").exists()


@pytest.mark.django_db
def test_excel_import_rejects_formula_in_optional_field_and_keeps_private_file(operator: User) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["原创文章标题", "原创发布日期", "备注"])
    sheet.append(["安全导入", date(2026, 8, 6), "=1+1"])
    buffer = BytesIO()
    workbook.save(buffer)
    uploaded = SimpleUploadedFile(
        "unsafe.xlsx",
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response = client_for(operator).post("/api/v1/article-imports", {"file": uploaded}, format="multipart")
    assert response.status_code == 201
    assert response.json()["data"]["failed_rows"] == 1
    from apps.articles.models import ArticleImportJob

    job = ArticleImportJob.objects.get(pk=response.json()["data"]["id"])
    assert job.uploaded_file.name.startswith("article-imports/")
    assert job.uploaded_file.name.endswith(".xlsx")
    assert job.uploaded_file.storage.exists(job.uploaded_file.name)


@pytest.mark.django_db
def test_excel_import_rejects_untrusted_mime_type(operator: User) -> None:
    client = client_for(operator)
    uploaded = SimpleUploadedFile("article.xlsx", make_xlsx(), content_type="text/plain")
    assert client.post("/api/v1/article-imports", {"file": uploaded}, format="multipart").status_code == 400


@pytest.mark.django_db
def test_platform_and_audit_permissions(administrator: User, operator: User, viewer: User) -> None:
    payload = {"code": "TEST_PLATFORM", "name": "测试平台", "domain_names": ["example.com"]}
    assert client_for(operator).post("/api/v1/platforms", payload, format="json").status_code == 403
    assert APIClient().get("/api/v1/platforms").status_code == 403
    created = client_for(administrator).post("/api/v1/platforms", payload, format="json")
    assert created.status_code == 201
    platform_id = created.json()["id"]
    assert client_for(viewer).get("/api/v1/platforms").status_code == 200
    assert (
        client_for(administrator).post(f"/api/v1/platforms/{platform_id}/enable", {}, format="json").status_code == 422
    )
    assert client_for(administrator).get("/api/v1/operation-logs").status_code == 200
    assert client_for(viewer).get("/api/v1/operation-logs").status_code == 403


@pytest.mark.django_db
def test_only_administrator_can_create_users(administrator: User, operator: User) -> None:
    payload = {"username": "new-viewer", "password": "safe-new-password", "role": Role.VIEWER}
    assert client_for(operator).post("/api/v1/users", payload, format="json").status_code == 403
    response = client_for(administrator).post("/api/v1/users", payload, format="json")
    assert response.status_code == 201
    assert User.objects.filter(username="new-viewer", role=Role.VIEWER).exists()
