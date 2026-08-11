from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.accounts.models import User
from apps.sources.models import Source
from apps.sources.token_services import create_source_token


class Command(BaseCommand):
    help = "为指定原创来源创建只显示一次的 Bearer Token。"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--source", required=True)
        parser.add_argument("--user", required=True)
        parser.add_argument("--name", required=True)

    def handle(self, *args: object, **options: object) -> None:
        source_code = str(options["source"])
        username = str(options["user"])
        name = str(options["name"]).strip()
        if not name:
            raise CommandError("Token 名称不能为空。")
        try:
            source = Source.objects.get(code=source_code)
        except Source.DoesNotExist as error:
            raise CommandError(f"Source 不存在：{source_code}") from error
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as error:
            raise CommandError(f"User 不存在：{username}") from error
        created = create_source_token(source=source, name=name, created_by=user)
        self.stdout.write(self.style.SUCCESS(f"Token：{created.plaintext}"))
        self.stdout.write("请立即保存，该 Token 不会再次显示。")
