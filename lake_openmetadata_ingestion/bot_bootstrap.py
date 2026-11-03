"""One-shot creation of the OM bot this tool provisions (instance-wide scope, see _RULES caveat).

Creates: policy -> role -> bot user (with the role) -> bot -> JWT. Idempotent (all PUTs); rerunning
regenerates the token, which invalidates the previous one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .om_client import OpenMetadataClient

logger = logging.getLogger(__name__)

# EditAll covers EditLineage/EditDescription/...; Delete is needed for mark_deleted soft deletes.
#
# CAVEAT (Helix 0c69e7bc): an OM policy rule matches by resource *type*; these rules carry no
# ``condition``, so the allow matches every service/database/schema/table in the whole OM instance,
# not just the one named by ``service.name``. Scoping the grant to that service would need a rule
# condition, and condition/SpEL semantics differ between OM versions and are not exercised by this
# repo's tests, so shipping one could make every write of an existing deployment fail closed. The
# honest fix here is to stop calling the grant "least-privilege" and to document the scope.
_RULES = [
    {
        "name": "lake-sync-allow-metadata",
        "description": "Create/update/soft-delete TiDB Cloud Lake services, databases, schemas, tables and their lineage.",
        "resources": ["databaseService", "database", "databaseSchema", "table"],
        "operations": ["Create", "ViewAll", "EditAll", "Delete"],
        "effect": "allow",
    },
    {
        "name": "lake-sync-deny-displayname",
        "description": "Bots must not rename entities.",
        "resources": ["All"],
        "operations": ["EditDisplayName"],
        "effect": "deny",
    },
]


@dataclass
class BotResult:
    bot_name: str
    bot_user_id: str
    role: str
    policy: str
    token: str


def bootstrap_bot(om_admin: OpenMetadataClient, name: str, token_expiry: str, email_domain: str) -> BotResult:
    policy = om_admin.upsert_policy(
        f"{name}Policy",
        "Lake ingestion sync policy: Create/ViewAll/EditAll/Delete on database services, databases, "
        "schemas and tables in this OpenMetadata instance. The rules are not scoped to one service "
        "(OM policy rules match by resource type); see README for deployment guidance.",
        _RULES,
    )
    role = om_admin.upsert_role(f"{name}Role", "Role for lake-openmetadata-ingestion bot.", [policy["name"]])
    user = om_admin.upsert_bot_user(name, f"{name}@{email_domain}", [role["id"]], token_expiry)
    om_admin.upsert_bot(name, user["name"], "Bot used by lake-openmetadata-ingestion to push TiDB Cloud Lake metadata and lineage.")
    token = om_admin.generate_bot_token(user["id"], token_expiry)
    return BotResult(bot_name=name, bot_user_id=user["id"], role=role["name"], policy=policy["name"], token=token)
