"""Shared group query helpers."""
import logging
from typing import Dict

from app.database import db
from app.models import GroupVisibility

logger = logging.getLogger(__name__)


def db_group_to_api(g: Dict) -> Dict:
    """Map DB groups row -> API response fields expected by the frontend.

    DB has: id, name, type, photo_url, member_count, visibility, registered_by, created_at
    API returns: id, telegram_id, title, group_type, visibility, etc.
    """
    return {
        "id": str(g["id"]),
        "telegram_id": g["id"],
        "title": g.get("name") or "Unknown",
        "username": g.get("username"),
        "member_count": g.get("member_count"),
        "group_type": g.get("type"),
        "visibility": g.get("visibility", "public"),
        "invite_link": g.get("invite_link"),
        "description": g.get("description"),
        "registered_by": g.get("registered_by"),
        "created_at": g.get("created_at"),
        "crawl_enabled": g.get("crawl_enabled", True),
    }


async def filter_accessible_group_ids(group_ids: list, current_user) -> list:
    """Return only group IDs the user is allowed to access (public or member of private)."""
    if not group_ids:
        return []
    int_ids = [int(gid) for gid in group_ids]
    rows = await db.fetch(
        "SELECT id, visibility FROM groups WHERE id = ANY($1::bigint[])", int_ids
    )
    if not rows:
        return []

    public_ids = []
    private_ids = []
    for g in rows:
        if g["visibility"] == GroupVisibility.PRIVATE.value:
            private_ids.append(g["id"])
        else:
            public_ids.append(g["id"])

    accessible = [str(gid) for gid in public_ids]

    if private_ids:
        membership_rows = await db.fetch(
            "SELECT group_id FROM user_groups WHERE user_id = $1 AND group_id = ANY($2::bigint[])",
            current_user.id, private_ids,
        )
        accessible.extend(str(m["group_id"]) for m in membership_rows)

    return accessible
