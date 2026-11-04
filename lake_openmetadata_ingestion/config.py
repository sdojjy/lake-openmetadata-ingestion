from __future__ import annotations

import logging
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any, missing: list[str] | None = None) -> Any:
    """Expand ${VAR} placeholders; record (never invent) the ones that are not set.

    A missing variable used to become the empty string silently, which turns e.g.
    ``lake://${LAKE_USER}:${LAKE_PASSWORD}@host`` into a DSN with an empty password. Keep the
    expansion behaviour (a missing optional var must not be fatal) but make it loud.
    """
    if isinstance(value, str):
        def _sub(m: re.Match[str]) -> str:
            name = m.group(1)
            if name not in os.environ:
                if missing is not None:
                    missing.append(name)
                return ""
            return os.environ[name]

        return _ENV_REF.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _expand_env(v, missing) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v, missing) for v in value]
    return value


def _warn_if_other_users_can_read(path: Path) -> None:
    """The config file holds the Lake DSN password (and the path of the OM token file): 0600 it."""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        logger.warning(
            "config file %s is accessible by other users (mode %o) but holds the Lake DSN "
            "credentials; chmod 600 it",
            path,
            mode,
        )


@dataclass
class LakeConfig:
    dsn: str


@dataclass
class OpenMetadataConfig:
    host: str
    jwt_token: str
    timeout_seconds: int = 30
    tls_ca_bundle: str | None = None
    require_tls: bool = False

    def __post_init__(self):
        # Environment interpolation produces strings; do not treat the string "false" as true.
        if isinstance(self.require_tls, str) and self.require_tls.lower() in ("true", "false"):
            self.require_tls = self.require_tls.lower() == "true"
        if not isinstance(self.require_tls, bool):
            raise ValueError("openmetadata.require_tls must be true or false")


@dataclass
class BotConfig:
    name: str = "LakeIngestionBot"
    # OneHour | 1 | 7 | 30 | 60 | 90 | Unlimited (days)
    token_expiry: str = "90"
    email_domain: str = "open-metadata.org"


@dataclass
class ServiceConfig:
    name: str
    display_name: str = "TiDB Cloud Lake"
    description: str = ""
    icon_url: str = ""


@dataclass
class MetadataConfig:
    catalogs: list[str] = field(default_factory=list)
    exclude_databases: list[str] = field(
        default_factory=lambda: ["system", "information_schema", "system_history"]
    )
    mark_deleted: bool = True


@dataclass
class StagesConfig:
    """TiDB Cloud Lake named stages are tenant-level; OM only has Table (tableType=Stage) under a schema.

    When enabled, stages are mounted as `<service>.<database>.<schema>.<stage>` and stage<->table
    lineage edges are synced (COPY INTO both directions, CTAS/DML reading `@stage`).
    """

    enabled: bool = False
    database: str = "default"
    schema: str = "stages"


@dataclass
class LineageConfig:
    state_file: str = ".state/lineage_watermark.json"
    include_kinds: list[str] = field(default_factory=lambda: ["CTAS", "DML", "CREATE_VIEW"])
    lookback_seconds: int = 120
    prune_view_upstreams: bool = True
    page_size: int = 5000


@dataclass
class Config:
    lake: LakeConfig
    openmetadata: OpenMetadataConfig
    service: ServiceConfig
    metadata: MetadataConfig
    lineage: LineageConfig
    bot: BotConfig
    stages: StagesConfig

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path = Path(path)
        missing: list[str] = []
        raw = _expand_env(yaml.safe_load(path.read_text()) or {}, missing)
        if missing:
            logger.warning(
                "config %s references unset environment variables (%s); they expand to empty "
                "strings, which makes the corresponding credential empty",
                path,
                ", ".join(sorted(set(missing))),
            )
        _warn_if_other_users_can_read(path)
        return cls(
            lake=LakeConfig(**raw["lake"]),
            openmetadata=OpenMetadataConfig(**raw["openmetadata"]),
            service=ServiceConfig(**raw["service"]),
            metadata=MetadataConfig(**raw.get("metadata", {})),
            lineage=LineageConfig(**raw.get("lineage", {})),
            bot=BotConfig(**raw.get("bot", {})),
            stages=StagesConfig(**raw.get("stages", {})),
        )
