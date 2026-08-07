from apps.articles.services import normalize_title


def test_title_normalization_only_removes_explicitly_configured_suffixes() -> None:
    source_title = "郑州银行60亿元二级资本债落地 筑牢中长期稳健经营发展根基"
    observed = f"{source_title}*新浪财经*新浪网"

    assert normalize_title(observed) == observed
    assert normalize_title(observed, confirmed_suffixes=["新浪财经*新浪网"]) == source_title
