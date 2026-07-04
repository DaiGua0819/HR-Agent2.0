"""Settings loading tests for env-backed integration secrets."""

from __future__ import annotations

import app.settings as settings_module


def test_load_settings_exports_dotenv_values_for_feishu(monkeypatch, tmp_path) -> None:
    """FeishuConfig properties should see values provided only by .env."""

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "FEISHU_APP_ID=cli_test",
                "FEISHU_APP_SECRET=secret_test",
                "FEISHU_REDIRECT_URI=http://example.test/callback",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    monkeypatch.delenv("FEISHU_REDIRECT_URI", raising=False)
    monkeypatch.setattr(settings_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings_module, "CONFIG_DIR", tmp_path / "config")
    settings_module.load_settings.cache_clear()

    loaded = settings_module.load_settings()

    settings_module.load_settings.cache_clear()
    assert loaded.feishu.app_id == "cli_test"
    assert loaded.feishu.app_secret == "secret_test"
    assert loaded.feishu.redirect_uri == "http://example.test/callback"


def test_env_example_documents_interview_center_feishu_keys() -> None:
    env_example = settings_module.PROJECT_ROOT / ".env.example"
    content = env_example.read_text(encoding="utf-8")

    for key in (
        "FEISHU_APP_ID=",
        "FEISHU_APP_SECRET=",
        "FEISHU_REDIRECT_URI=",
        "FEISHU_BITABLE_APP_TOKEN=",
        "FEISHU_CANDIDATE_TABLE_ID=",
        "FEISHU_INTERVIEW_TABLE_ID=",
        "FEISHU_AI_PRODUCT_MANAGER_TABLE_ID=",
    ):
        assert key in content
