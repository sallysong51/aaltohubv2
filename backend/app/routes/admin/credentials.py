"""Admin credentials and connection diagnostics routes."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from app.models import UserResponse
from app.auth import get_current_admin_user
from app.database import db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/admin-credentials")
async def get_admin_credentials(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """List all admin credentials (phone/username pairs) - admin only"""
    try:
        rows = await db.fetch(
            "SELECT id, phone_number, username, added_by_user_id, created_at FROM admin_credentials ORDER BY created_at DESC"
        )
        credentials = []
        for row in rows:
            cred_dict = dict(row)
            # If added_by_user_id exists, fetch the user's username for display
            if cred_dict.get("added_by_user_id"):
                added_by = await db.fetchrow(
                    "SELECT username FROM users WHERE id = $1",
                    cred_dict["added_by_user_id"]
                )
                cred_dict["added_by_username"] = added_by.get("username") if added_by else None
            credentials.append(cred_dict)
        return {"data": credentials}
    except Exception as e:
        logger.error("get_admin_credentials error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch admin credentials")


@router.post("/admin-credentials")
async def add_admin_credential(
    phone_number: str | None = Query(None),
    username: str | None = Query(None),
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Add a new admin credential (phone or username) - admin only"""
    if not phone_number and not username:
        raise HTTPException(status_code=400, detail="Must provide phone_number or username")

    try:
        result = await db.fetchrow(
            """INSERT INTO admin_credentials (phone_number, username, added_by_user_id)
               VALUES ($1, $2, $3)
               RETURNING id, phone_number, username, created_at""",
            phone_number or None,
            username or None,
            current_user.id,
        )

        if not result:
            raise HTTPException(status_code=500, detail="Failed to add admin credential")

        logger.info("Admin credential added by %s: phone=%s, username=%s",
                   current_user.username, phone_number, username)

        return {"success": True, "credential": dict(result)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("add_admin_credential error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to add admin credential")


@router.delete("/admin-credentials/{credential_id}")
async def remove_admin_credential(
    credential_id: int,
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Remove an admin credential - admin only. Prevents removing the last credential."""
    try:
        # Safety check: prevent removing the last admin credential
        count = await db.fetchval("SELECT COUNT(*) FROM admin_credentials")
        if count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last admin credential")

        # Get credential info before deletion (for logging)
        cred = await db.fetchrow(
            "SELECT phone_number, username FROM admin_credentials WHERE id = $1",
            credential_id
        )

        if not cred:
            raise HTTPException(status_code=404, detail="Admin credential not found")

        # Delete the credential
        await db.execute(
            "DELETE FROM admin_credentials WHERE id = $1",
            credential_id
        )

        logger.info("Admin credential removed by %s: phone=%s, username=%s",
                   current_user.username, cred.get("phone_number"), cred.get("username"))

        return {"success": True, "message": "Admin credential removed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("remove_admin_credential error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to remove admin credential")


@router.get("/connection-diagnostics")
async def get_connection_diagnostics(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """
    Get comprehensive diagnostic information about telegram connections and group linking.

    Returns:
    - Migration status (connection_id column exists)
    - Current user's connections
    - Groups overview
    - Connection linking statistics
    - Unlinked groups details
    - Actionable recommendations
    """
    try:
        diagnostics = {}

        # 1. Check if connection_id column exists (migration 004 status)
        col_exists = await db.fetchrow(
            """SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'user_groups'
                AND column_name = 'connection_id'
            )"""
        )
        diagnostics["migration_status"] = {
            "connection_id_column_exists": col_exists['exists'] if col_exists else False,
            "migration_004_applied": col_exists['exists'] if col_exists else False,
        }

        # 2. Get current user's connections
        connections = await db.fetch(
            """SELECT id, telegram_user_id, username, first_name, last_name, phone_masked, connected_at
               FROM telegram_connections
               WHERE user_id = $1
               ORDER BY connected_at DESC""",
            current_user.id,
        )
        diagnostics["connections"] = {
            "count": len(connections),
            "list": [
                {
                    "id": str(c["id"]),
                    "telegram_user_id": c["telegram_user_id"],
                    "username": c.get("username"),
                    "first_name": c.get("first_name"),
                    "display_name": f"@{c['username']}" if c.get("username") else c.get("first_name") or c.get("phone_masked"),
                    "connected_at": str(c["connected_at"]) if c.get("connected_at") else None,
                }
                for c in connections
            ],
        }

        # 3. Groups overview
        total_groups = await db.fetchval("SELECT COUNT(*) FROM groups")
        public_groups = await db.fetchval("SELECT COUNT(*) FROM groups WHERE visibility = 'public'")
        private_groups = await db.fetchval("SELECT COUNT(*) FROM groups WHERE visibility = 'private'")

        diagnostics["groups_overview"] = {
            "total": total_groups or 0,
            "public": public_groups or 0,
            "private": private_groups or 0,
        }

        # 4. Connection linking stats
        total_user_groups = await db.fetchval("SELECT COUNT(*) FROM user_groups WHERE user_id = $1", current_user.id)
        linked_count = await db.fetchval(
            "SELECT COUNT(*) FROM user_groups WHERE user_id = $1 AND connection_id IS NOT NULL",
            current_user.id,
        )
        unlinked_count = await db.fetchval(
            "SELECT COUNT(*) FROM user_groups WHERE user_id = $1 AND connection_id IS NULL",
            current_user.id,
        )

        diagnostics["linking_stats"] = {
            "total_user_groups": total_user_groups or 0,
            "linked": linked_count or 0,
            "unlinked": unlinked_count or 0,
            "linked_percentage": round((linked_count / total_user_groups * 100) if total_user_groups else 0, 1),
            "unlinked_percentage": round((unlinked_count / total_user_groups * 100) if total_user_groups else 0, 1),
        }

        # 5. Breakdown by connection
        breakdown = await db.fetch(
            """SELECT
                   ug.connection_id,
                   tc.username,
                   tc.first_name,
                   COUNT(*) as group_count
               FROM user_groups ug
               LEFT JOIN telegram_connections tc ON ug.connection_id = tc.id
               WHERE ug.user_id = $1 AND ug.connection_id IS NOT NULL
               GROUP BY ug.connection_id, tc.username, tc.first_name""",
            current_user.id,
        )
        diagnostics["breakdown"] = [
            {
                "connection_id": str(b["connection_id"]),
                "username": b.get("username"),
                "display_name": f"@{b['username']}" if b.get("username") else b.get("first_name"),
                "group_count": b["group_count"],
            }
            for b in breakdown
        ]

        # 6. Unlinked groups details
        unlinked_groups = await db.fetch(
            """SELECT g.id, g.name, g.username, u.username as registered_by_username
               FROM user_groups ug
               JOIN groups g ON ug.group_id = g.id
               LEFT JOIN users u ON g.registered_by = u.id
               WHERE ug.user_id = $1 AND ug.connection_id IS NULL
               ORDER BY g.name
               LIMIT 50""",
            current_user.id,
        )
        diagnostics["unlinked_groups"] = [
            {
                "id": str(g["id"]),
                "name": g["name"],
                "username": g.get("username"),
                "registered_by_username": g.get("registered_by_username"),
            }
            for g in unlinked_groups
        ]

        # 7. Actionable recommendations
        recommendations = []

        if not diagnostics["migration_status"]["migration_004_applied"]:
            recommendations.append({
                "level": "error",
                "message": "마이그레이션 004가 적용되지 않았습니다. backend/scripts/ensure_migration_004.py를 실행하세요.",
            })

        conn_count = diagnostics["connections"]["count"]
        unlinked = diagnostics["linking_stats"]["unlinked"]

        if conn_count == 0:
            recommendations.append({
                "level": "warning",
                "message": "텔레그램 계정을 먼저 연결하세요.",
            })
        elif conn_count == 1 and unlinked > 0:
            recommendations.append({
                "level": "info",
                "message": f"자동 연결 버튼을 클릭하여 {unlinked}개 그룹을 자동으로 연결할 수 있습니다.",
            })
        elif conn_count > 1 and unlinked > 0:
            recommendations.append({
                "level": "warning",
                "message": f"여러 텔레그램 계정이 있습니다. 그룹 선택 페이지에서 각 계정별로 {unlinked}개 그룹을 다시 등록해주세요.",
            })
        elif unlinked == 0 and total_user_groups > 0:
            recommendations.append({
                "level": "success",
                "message": "모든 그룹이 텔레그램 계정에 연결되었습니다!",
            })

        diagnostics["recommendations"] = recommendations

        return diagnostics

    except Exception as e:
        logger.error("get_connection_diagnostics error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get diagnostics")
