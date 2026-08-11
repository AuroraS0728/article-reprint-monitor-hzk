from __future__ import annotations

from datetime import date

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_0004_backfills_existing_duplicate_groups_before_adding_unique_constraint() -> None:
    old_targets = [("articles", "0003_source_global_monitoring"), ("sources", "0002_searchrun")]
    executor = MigrationExecutor(connection)
    executor.migrate(old_targets)
    old_apps = executor.loader.project_state(old_targets).apps
    User = old_apps.get_model("accounts", "User")
    Article = old_apps.get_model("articles", "Article")
    user = User.objects.create(username="migration-admin", password="not-used", role="ADMIN")
    for index in range(3):
        Article.objects.create(
            title=f"历史重复 {index}",
            normalized_title="历史重复",
            published_date=date(2026, 8, 11),
            created_by_id=user.id,
        )

    new_targets = [("articles", "0004_article_duplicate_protection"), ("sources", "0003_articleingestconflict")]
    try:
        executor = MigrationExecutor(connection)
        executor.migrate(new_targets)
        new_apps = executor.loader.project_state(new_targets).apps
        MigratedArticle = new_apps.get_model("articles", "Article")
        rows = list(MigratedArticle.objects.filter(normalized_title="历史重复").order_by("id"))
        assert [row.duplicate_slot for row in rows] == [0, 1, 2]
        assert rows[0].duplicate_reason == ""
        assert [row.duplicate_reason for row in rows[1:]] == [
            "LEGACY_MIGRATION_EXISTING_DUPLICATE",
            "LEGACY_MIGRATION_EXISTING_DUPLICATE",
        ]
        assert all(row.duplicate_approved_by_id is None for row in rows[1:])
        assert all(row.duplicate_approved_at is None for row in rows[1:])
        MigratedArticle.objects.create(
            title="历史重复 3",
            normalized_title="历史重复",
            published_date=date(2026, 8, 11),
            duplicate_slot=3,
            created_by_id=user.id,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                MigratedArticle.objects.create(
                    title="非法重复 slot0",
                    normalized_title="历史重复",
                    published_date=date(2026, 8, 11),
                    duplicate_slot=0,
                    created_by_id=user.id,
                )
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
