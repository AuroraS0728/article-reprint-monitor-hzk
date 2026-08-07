import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User


@pytest.mark.django_db
def test_health_is_public() -> None:
    response = APIClient().get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


@pytest.mark.django_db
def test_login_and_me(user: object) -> None:
    client = APIClient(enforce_csrf_checks=False)
    response = client.post(
        "/api/v1/auth/login",
        {"username": "operator", "password": "safe-test-password"},
        format="json",
    )
    assert response.status_code == 200
    assert client.get("/api/v1/auth/me").json()["data"]["username"] == "operator"


@pytest.mark.django_db
def test_invalid_login_is_rejected_without_registration() -> None:
    client = APIClient(enforce_csrf_checks=False)
    response = client.post("/api/v1/auth/login", {"username": "nobody", "password": "wrong-password"}, format="json")
    assert response.status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 403


@pytest.mark.django_db
def test_superuser_is_a_business_administrator() -> None:
    user = User.objects.create_superuser(username="root-admin", password="safe-admin-password")
    assert user.role == Role.ADMIN
    assert user.must_change_password is False
