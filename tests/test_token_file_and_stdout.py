"""The bot JWT is written to a 0600 file, never to stdout by default.

Helix 23c5940e: the token file was created with ``write_text()`` at the prevailing umask and only
then chmod'ed to 0600, and ``write_text`` follows symlinks.
Helix 72742ab9: ``init-bot`` printed the long-lived privileged JWT to stdout by default, which on the
documented cron/Airflow deployment means the job log.
"""

from __future__ import annotations

import argparse
import os
import stat

import pytest

from lake_openmetadata_ingestion import cli
from lake_openmetadata_ingestion.bot_bootstrap import BotResult
from lake_openmetadata_ingestion.config import (
    BotConfig,
    Config,
    LakeConfig,
    LineageConfig,
    MetadataConfig,
    OpenMetadataConfig,
    ServiceConfig,
    StagesConfig,
)
from lake_openmetadata_ingestion.secure_write import token_fingerprint, write_secret_file

TOKEN = "eyJhbGciOiJSUzI1NiJ9.b3QtYm90LWp3dC1zZWNyZXQ.c2lnbmF0dXJl"


def test_write_secret_file_is_atomic_and_owner_only(tmp_path):
    path = write_secret_file(tmp_path / "nested" / "bot_token", TOKEN)
    assert path.read_text() == TOKEN
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # no temporary leftovers next to the secret
    assert os.listdir(tmp_path / "nested") == ["bot_token"]


def test_write_secret_file_does_not_follow_a_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    link = tmp_path / "bot_token"
    link.symlink_to(outside)

    write_secret_file(link, TOKEN)

    assert outside.read_text() == "untouched", "secret was written through the symlink"
    assert not link.is_symlink()
    assert link.read_text() == TOKEN
    assert stat.S_IMODE(link.stat().st_mode) == 0o600


def test_token_fingerprint_does_not_reveal_the_token():
    fingerprint = token_fingerprint(TOKEN)
    assert fingerprint not in TOKEN
    assert TOKEN not in fingerprint
    assert fingerprint == token_fingerprint(TOKEN)


@pytest.fixture
def init_bot_cfg(monkeypatch):
    cfg = Config(
        lake=LakeConfig(dsn="lake://u:p@h:443/?warehouse=w"),
        openmetadata=OpenMetadataConfig(host="https://om.example.com/api", jwt_token="x"),
        service=ServiceConfig(name="lake_prod"),
        metadata=MetadataConfig(),
        lineage=LineageConfig(),
        bot=BotConfig(),
        stages=StagesConfig(),
    )
    monkeypatch.setenv("OM_ADMIN_TOKEN", "admin-token")
    monkeypatch.setattr(
        cli,
        "bootstrap_bot",
        lambda *a, **kw: BotResult(
            bot_name="b", bot_user_id="1", role="r", policy="p", token=TOKEN
        ),
    )
    return cfg


def test_init_bot_writes_token_to_file_and_never_prints_it(init_bot_cfg, tmp_path, capsys):
    target = tmp_path / "bot_token"
    args = argparse.Namespace(write_token=str(target), print_token=False)

    assert cli.cmd_init_bot(init_bot_cfg, args) == 0

    out, err = capsys.readouterr()
    assert TOKEN not in out
    assert TOKEN not in err
    assert target.read_text() == TOKEN
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert token_fingerprint(TOKEN) in out


def test_init_bot_defaults_to_the_state_file(init_bot_cfg, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(write_token=None, print_token=False)

    assert cli.cmd_init_bot(init_bot_cfg, args) == 0

    out, _ = capsys.readouterr()
    written = tmp_path / cli.DEFAULT_TOKEN_PATH
    assert written.read_text() == TOKEN
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert TOKEN not in out


def test_init_bot_prints_the_token_only_when_explicitly_asked(init_bot_cfg, capsys):
    args = argparse.Namespace(write_token=None, print_token=True)

    assert cli.cmd_init_bot(init_bot_cfg, args) == 0

    out, err = capsys.readouterr()
    assert TOKEN in out
    assert "may persist" in err  # the warning is on stderr, not mixed into stdout
