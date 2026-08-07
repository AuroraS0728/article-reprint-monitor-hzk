import pytest

from apps.accounts.models import Role, User


@pytest.fixture
def user(db: object) -> User:
    return User.objects.create_user(username="operator", password="safe-test-password", role=Role.OPERATOR)


@pytest.fixture
def administrator(db: object) -> User:
    return User.objects.create_user(username="admin", password="safe-test-password", role=Role.ADMIN)


@pytest.fixture
def operator(db: object) -> User:
    return User.objects.create_user(username="operator-two", password="safe-test-password", role=Role.OPERATOR)


@pytest.fixture
def viewer(db: object) -> User:
    return User.objects.create_user(username="viewer", password="safe-test-password", role=Role.VIEWER)
