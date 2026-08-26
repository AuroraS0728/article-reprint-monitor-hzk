from typing import ClassVar

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class Role(models.TextChoices):
    ADMIN = "ADMIN", "管理员"
    OPERATOR = "OPERATOR", "操作人员"
    VIEWER = "VIEWER", "查看人员"


class RepostUserManager(UserManager["User"]):
    def create_superuser(
        self,
        username: str,
        email: str | None = None,
        password: str | None = None,
        **extra_fields: object
    ) -> "User":
        extra_fields.setdefault("role", Role.ADMIN)
        extra_fields.setdefault("must_change_password", False)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)
    must_change_password = models.BooleanField(default=True)
    objects: ClassVar[RepostUserManager] = RepostUserManager()

    class Meta:
        db_table = "accounts_user"
