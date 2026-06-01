"""Config / .env resolution + the secrets-never-leak contract."""

from agentforce_probe import config as config_mod


def test_env_override_wins(tmp_path, monkeypatch):
    p = tmp_path / "custom.env"
    p.write_text("AGENTPROBE_SF_CONSUMER_KEY=fromfile\n")
    monkeypatch.setenv("AGENTPROBE_ENV_FILE", str(p))
    # ensure no real env var shadows it
    monkeypatch.delenv("AGENTPROBE_SF_CONSUMER_KEY", raising=False)
    cfg = config_mod.Config()
    ck, cs = cfg.eca_credentials()
    assert ck == "fromfile"
    assert cs is None


def test_cwd_env_is_picked_up(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("AGENTPROBE_ANTHROPIC_API_KEY=k123\n")
    monkeypatch.delenv("AGENTPROBE_ENV_FILE", raising=False)
    monkeypatch.delenv("AGENTPROBE_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = config_mod.Config()
    assert cfg.judge_api_key("anthropic") == "k123"
    assert cfg.env_file_exists() is True


def test_env_var_takes_precedence_over_file(tmp_path, monkeypatch):
    p = tmp_path / "custom.env"
    p.write_text("AGENTPROBE_SF_CONSUMER_KEY=fromfile\n")
    monkeypatch.setenv("AGENTPROBE_ENV_FILE", str(p))
    monkeypatch.setenv("AGENTPROBE_SF_CONSUMER_KEY", "fromenv")
    cfg = config_mod.Config()
    ck, _ = cfg.eca_credentials()
    assert ck == "fromenv"


def test_missing_secret_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTPROBE_ENV_FILE", str(tmp_path / "nope.env"))
    monkeypatch.delenv("AGENTPROBE_SF_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("AGENTPROBE_SF_CONSUMER_SECRET", raising=False)
    cfg = config_mod.Config()
    assert cfg.eca_credentials() == (None, None)
    assert cfg.judge_api_key("openai") is None
    # unknown provider -> None, never raises
    assert cfg.judge_api_key("nonexistent") is None
