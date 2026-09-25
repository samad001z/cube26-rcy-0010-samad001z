"""Settings: the repo-root .env is read automatically; a missing setting is one line."""

import sys
from pathlib import Path

import pytest

from app import cli
from app.core.config import ENV_FILE, REPO_ROOT, Settings, SettingsError, get_settings

REQUIRED = ("DATABASE_URL", "MIGRATION_DATABASE_URL", "ATTACHMENT_KEY_SECRET")


@pytest.fixture
def no_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No required variable in the environment and no .env file."""
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", tmp_path / "absent.env")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_env_file_is_the_repo_root_env_whatever_the_working_directory():
    assert ENV_FILE == REPO_ROOT / ".env" and ENV_FILE.is_absolute()
    assert (REPO_ROOT / ".env.example").is_file()
    assert Settings.model_config["env_file"] == ENV_FILE


def test_values_are_read_from_the_env_file(no_env, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "DATABASE_URL=postgresql+psycopg://a@h/db\n"
        "MIGRATION_DATABASE_URL=postgresql+psycopg://o@h/db\n"
        "ATTACHMENT_KEY_SECRET=s3cret\n"
    )
    monkeypatch.setitem(Settings.model_config, "env_file", env)
    monkeypatch.chdir(tmp_path.parent)
    s = get_settings()
    assert s.database_url == "postgresql+psycopg://a@h/db"
    assert s.attachment_key_secret.get_secret_value() == "s3cret"


def test_missing_setting_is_a_one_line_hint(no_env):
    with pytest.raises(SettingsError) as info:
        get_settings()
    msg = str(info.value)
    assert "\n" not in msg
    assert "DATABASE_URL" in msg and "copy .env.example to .env" in msg


def test_cli_prints_the_hint_without_a_traceback(no_env, monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["alibi", "ingest", "--report", "r.csv", "--upstream", "u", "--org", "o"]
    )
    with pytest.raises(SystemExit) as info:
        cli.main()
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert err.strip().count("\n") == 0
    assert err.startswith("alibi: missing setting") and "copy .env.example to .env" in err
