"""
Telegram groups routes
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
from app.models import (
    TelegramGroupInfo, TelegramGroupResponse,
    RegisterGroupsRequest, RegisterGroupsResponse,
    MessagesListResponse, MessageResponse,
    UserResponse, GroupVisibility
)
from app.auth import get_current_user, get_current_admin_user
from app.database import get_db
from app.telegram_client import telegram_manager


router = APIRouter(prefix="/groups", tags=["Groups"])


@router.get("/my-telegram-groups", response_model=List[TelegramGroupInfo])
async def get_my_groups(
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get all Telegram groups user is member of"""
    try:
        # Get groups from Telegram
        groups = await telegram_manager.get_user_groups(current_user.id)
        
        # Get registered groups from database
        registered_response = db.table("groups").select("telegram_id").execute()
        registered_ids = {g["telegram_id"] for g in registered_response.data} if registered_response.data else set()
        
        # Mark registered groups
        result = []
        for group in groups:
            group_info = TelegramGroupInfo(
                **group,
                is_registered=group["telegram_id"] in registered_ids
            )
            result.append(group_info)
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/register", response_model=RegisterGroupsResponse)
async def register_groups(
    request: RegisterGroupsRequest,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Register selected groups"""
    try:
        registered_groups = []
        failed_invites = []
        
        for group_data in request.groups:
            # Insert group into database
            group_insert = {
                "telegram_id": group_data["telegram_id"],
                "title": group_data["title"],
                "username": group_data.get("username"),
                "member_count": group_data.get("member_count"),
                "group_type": group_data.get("group_type"),
                "visibility": group_data.get("visibility", GroupVisibility.PUBLIC.value),
                "registered_by": current_user.id
            }
            
            # Check if group already exists
            existing = db.table("groups").select("*").eq("telegram_id", group_data["telegram_id"]).execute()
            
            if existing.data and len(existing.data) > 0:
                # Group already registered, skip
                continue
            
            # Insert new group
            new_group = db.table("groups").insert(group_insert).execute()
            group_id = new_group.data[0]["id"]
            
            # Add to user's follows
            db.table("user_group_follows").insert({
                "user_id": current_user.id,
                "group_id": group_id
            }).execute()
            
            # If public, invite admin
            if group_data.get("visibility", GroupVisibility.PUBLIC.value) == GroupVisibility.PUBLIC.value:
                invite_result = await telegram_manager.invite_admin_to_group(group_data["telegram_id"])
                
                if invite_result["success"]:
                    # Update admin_invited status
                    db.table("groups").update({
                        "admin_invited": True
                    }).eq("id", group_id).execute()
                else:
                    # Store error
                    db.table("groups").update({
                        "admin_invited": False,
                        "admin_invite_error": invite_result["error"]
                    }).eq("id", group_id).execute()
                    
                    failed_invites.append({
                        "group_id": group_id,
                        "title": group_data["title"],
                        "error": invite_result["error"]
                    })
            
            # Get updated group data
            updated_group = db.table("groups").select("*").eq("id", group_id).execute()
            registered_groups.append(TelegramGroupResponse(**updated_group.data[0]))
        
        return RegisterGroupsResponse(
            success=True,
            registered_groups=registered_groups,
            failed_invites=failed_invites
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/registered", response_model=List[TelegramGroupResponse])
async def get_registered_groups(
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get user's registered groups"""
    try:
        # Get groups user follows
        follows = db.table("user_group_follows").select("group_id").eq("user_id", current_user.id).execute()
        
        if not follows.data or len(follows.data) == 0:
            return []
        
        group_ids = [f["group_id"] for f in follows.data]
        
        # Get group details
        groups = db.table("groups").select("*").in_("id", group_ids).execute()
        
        return [TelegramGroupResponse(**g) for g in groups.data] if groups.data else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{group_id}/messages", response_model=MessagesListResponse)
async def get_group_messages(
    group_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get messages from a specific group"""
    try:
        # Check if user has access to this group
        # For now, allow all authenticated users (public groups)
        # TODO: Add private group access check
        
        # Calculate offset
        offset = (page - 1) * page_size
        
        # Get total count
        count_response = db.table("messages").select("id", count="exact").eq("group_id", group_id).execute()
        total = count_response.count if hasattr(count_response, 'count') else 0
        
        # Get messages
        messages_response = db.table("messages").select("*").eq("group_id", group_id).order("sent_at", desc=True).range(offset, offset + page_size - 1).execute()
        
        messages = [MessageResponse(**m) for m in messages_response.data] if messages_response.data else []
        
        return MessagesListResponse(
            messages=messages,
            total=total,
            page=page,
            page_size=page_size,
            has_more=offset + page_size < total
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{group_id}/invite-admin")
async def retry_invite_admin(
    group_id: str,
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Retry inviting admin to a group (admin only)"""
    try:
        # Get group
        group_response = db.table("groups").select("*").eq("id", group_id).execute()
        
        if not group_response.data or len(group_response.data) == 0:
            raise HTTPException(status_code=404, detail="Group not found")
        
        group = group_response.data[0]
        
        # Invite admin
        invite_result = await telegram_manager.invite_admin_to_group(group["telegram_id"])
        
        if invite_result["success"]:
            # Update status
            db.table("groups").update({
                "admin_invited": True,
                "admin_invite_error": None
            }).eq("id", group_id).execute()
            
            return {"success": True, "message": "Admin invited successfully"}
        else:
            # Update error
            db.table("groups").update({
                "admin_invited": False,
                "admin_invite_error": invite_result["error"]
            }).eq("id", group_id).execute()
            
            return {"success": False, "error": invite_result["error"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{group_id}")
async def get_group(
    group_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get a single group by ID"""
    try:
        # Check if user has access to this group
        group_response = db.table("groups").select("*").eq("id", group_id).execute()
        
        if not group_response.data or len(group_response.data) == 0:
            raise HTTPException(status_code=404, detail="Group not found")
        
        group = group_response.data[0]
        
        # Check access for private groups
        if group["visibility"] == "private":
            # Check if user is owner or has been invited
            if group["registered_by"] != current_user.id:
                follow = db.table("user_group_follows").select("*").eq("user_id", current_user.id).eq("group_id", group_id).execute()
                if not follow.data:
                    raise HTTPException(status_code=403, detail="Access denied")
        
        return TelegramGroupResponse(**group)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{group_id}/invite-links")
async def get_invite_links(
    group_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get all invite links for a group"""
    try:
        # Check if user owns this group
        group = db.table("groups").select("*").eq("id", group_id).eq("registered_by", current_user.id).single().execute()
        
        if not group.data:
            raise HTTPException(status_code=404, detail="Group not found or you don't have permission")
        
        # Get invite links
        invites = db.table("private_group_invites").select("*").eq("group_id", group_id).order("created_at", desc=True).execute()
        
        return invites.data if invites.data else []
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/groups/{group_id}/invite-link")
async def create_invite_link(
    group_id: str,
    expires_at: str = None,
    max_uses: int = None,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Create an invite link for a private group"""
    import secrets
    from datetime import datetime
    
    try:
        # Check if user owns this group
        group = db.table("groups").select("*").eq("id", group_id).eq("registered_by", current_user.id).single().execute()
        
        if not group.data:
            raise HTTPException(status_code=404, detail="Group not found or you don't have permission")
        
        if group.data["visibility"] != "private":
            raise HTTPException(status_code=400, detail="Can only create invite links for private groups")
        
        # Generate unique token
        token = secrets.token_urlsafe(32)
        
        # Create invite
        invite_data = {
            "group_id": group_id,
            "token": token,
            "created_by": current_user.id,
            "expires_at": expires_at,
            "max_uses": max_uses,
            "created_at": datetime.utcnow().isoformat()
        }
        
        result = db.table("private_group_invites").insert(invite_data).execute()
        
        return {
            "success": True,
            "invite_link": f"/invite/{token}",
            "token": token,
            "expires_at": expires_at,
            "max_uses": max_uses
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/invite/{token}/accept")
async def accept_invite(
    token: str,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Accept an invite link and gain access to private group"""
    from datetime import datetime
    
    try:
        # Get invite
        invite = db.table("private_group_invites").select("*").eq("token", token).single().execute()
        
        if not invite.data:
            raise HTTPException(status_code=404, detail="Invite not found")
        
        invite_data = invite.data
        
        # Check if revoked
        if invite_data.get("is_revoked"):
            raise HTTPException(status_code=400, detail="Invite link has been revoked")
        
        # Check if expired
        if invite_data.get("expires_at"):
            expires_at = datetime.fromisoformat(invite_data["expires_at"])
            if datetime.utcnow() > expires_at:
                raise HTTPException(status_code=400, detail="Invite link has expired")
        
        # Check max uses
        if invite_data.get("max_uses"):
            if invite_data.get("used_count", 0) >= invite_data["max_uses"]:
                raise HTTPException(status_code=400, detail="Invite link has reached maximum uses")
        
        # Add user to group followers
        follow_data = {
            "user_id": current_user.id,
            "group_id": invite_data["group_id"],
            "created_at": datetime.utcnow().isoformat()
        }
        
        # Check if already following
        existing = db.table("user_group_follows").select("*").eq("user_id", current_user.id).eq("group_id", invite_data["group_id"]).execute()
        
        if not existing.data:
            db.table("user_group_follows").insert(follow_data).execute()
        
        # Increment used_count
        db.table("private_group_invites").update({
            "used_count": invite_data.get("used_count", 0) + 1
        }).eq("id", invite_data["id"]).execute()
        
        return {"success": True, "group_id": invite_data["group_id"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/groups/{group_id}/invite-link/{invite_id}/revoke")
async def revoke_invite_link(
    group_id: str,
    invite_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Revoke an invite link"""
    from datetime import datetime
    
    try:
        # Check if user owns this group
        group = db.table("groups").select("*").eq("id", group_id).eq("registered_by", current_user.id).single().execute()
        
        if not group.data:
            raise HTTPException(status_code=404, detail="Group not found or you don't have permission")
        
        # Revoke invite
        result = db.table("private_group_invites").update({
            "is_revoked": True,
            "revoked_at": datetime.utcnow().isoformat()
        }).eq("id", invite_id).eq("group_id", group_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Invite not found")
        
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/groups/{group_id}/visibility")
async def update_group_visibility(
    group_id: str,
    visibility: str,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Update group visibility (public/private)"""
    from datetime import datetime
    
    try:
        # Check if user owns this group
        group = db.table("groups").select("*").eq("id", group_id).eq("registered_by", current_user.id).single().execute()
        
        if not group.data:
            raise HTTPException(status_code=404, detail="Group not found or you don't have permission")
        
        # Update visibility
        result = db.table("groups").update({
            "visibility": visibility,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", group_id).execute()
        
        # If changing to public, try to invite admin
        if visibility == "public":
            try:
                await telegram_manager.invite_admin_to_group(group.data["telegram_id"])
                db.table("groups").update({
                    "admin_invited": True,
                    "admin_invite_error": None
                }).eq("id", group_id).execute()
            except Exception as e:
                db.table("groups").update({
                    "admin_invited": False,
                    "admin_invite_error": str(e)
                }).eq("id", group_id).execute()
        
        return {"success": True, "visibility": visibility}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/groups/{group_id}")
async def delete_group(
    group_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Delete a group (private groups: owner only, public groups: admin only)"""
    try:
        # Get group
        group = db.table("groups").select("*").eq("id", group_id).single().execute()
        
        if not group.data:
            raise HTTPException(status_code=404, detail="Group not found")
        
        # Check permissions
        if group.data["visibility"] == "private":
            # Private group: only owner can delete
            if group.data["registered_by"] != current_user.id:
                raise HTTPException(status_code=403, detail="Only the group owner can delete private groups")
        else:
            # Public group: only admin can delete
            if current_user.role != "admin":
                raise HTTPException(status_code=403, detail="Only admins can delete public groups")
        
        # Delete group (cascade will handle related records)
        db.table("groups").delete().eq("id", group_id).execute()
        
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
