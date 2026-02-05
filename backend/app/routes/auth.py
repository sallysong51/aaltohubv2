"""
Authentication routes
"""
from fastapi import APIRouter, Depends, HTTPException
from app.models import (
    SendCodeRequest, SendCodeResponse,
    VerifyCodeRequest, Verify2FARequest,
    AuthResponse, RefreshTokenRequest,
    UserCreate, UserResponse, UserRole
)
from app.auth import create_access_token, create_refresh_token, get_current_user, verify_refresh_token
from app.database import get_db
from app.telegram_client import telegram_manager
from app.config import settings


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/send-code", response_model=SendCodeResponse)
async def send_code(request: SendCodeRequest):
    """Send authentication code to Telegram"""
    try:
        result = await telegram_manager.send_code(request.phone_or_username)
        return SendCodeResponse(
            success=result["success"],
            message="Code sent successfully",
            phone_code_hash=result["phone_code_hash"],
            requires_2fa=result["requires_2fa"]
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/verify-code", response_model=AuthResponse)
async def verify_code(request: VerifyCodeRequest, db=Depends(get_db)):
    """Verify authentication code and sign in"""
    try:
        result = await telegram_manager.verify_code(
            request.phone_or_username,
            request.code,
            request.phone_code_hash
        )
        
        # Check if 2FA is required
        if result.get("requires_2fa"):
            raise HTTPException(
                status_code=403,
                detail="Two-factor authentication required"
            )
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail="Verification failed")
        
        # Get user info
        user_info = result["user_info"]
        session_string = result["session_string"]
        
        # Determine role
        is_admin = settings.is_admin(
            phone=user_info.get("phone_number"),
            username=user_info.get("username")
        )
        role = UserRole.ADMIN if is_admin else UserRole.USER
        
        # Check if user exists
        existing_user = db.table("users").select("*").eq("telegram_id", user_info["telegram_id"]).execute()
        
        if existing_user.data and len(existing_user.data) > 0:
            # Update existing user
            user_data = existing_user.data[0]
            user_id = user_data["id"]
            
            db.table("users").update({
                "phone_number": user_info.get("phone_number"),
                "username": user_info.get("username"),
                "first_name": user_info.get("first_name"),
                "last_name": user_info.get("last_name"),
                "role": role.value
            }).eq("id", user_id).execute()
        else:
            # Create new user
            new_user = db.table("users").insert({
                "telegram_id": user_info["telegram_id"],
                "phone_number": user_info.get("phone_number"),
                "username": user_info.get("username"),
                "first_name": user_info.get("first_name"),
                "last_name": user_info.get("last_name"),
                "role": role.value
            }).execute()
            
            user_id = new_user.data[0]["id"]
        
        # Save Telethon session
        await telegram_manager.save_session(user_id, session_string)
        
        # Get updated user data
        user_response = db.table("users").select("*").eq("id", user_id).execute()
        user = UserResponse(**user_response.data[0])
        
        # Create JWT tokens
        access_token = create_access_token({"sub": user_id})
        refresh_token = create_refresh_token({"sub": user_id})
        
        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=user
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify-2fa", response_model=AuthResponse)
async def verify_2fa(request: Verify2FARequest, db=Depends(get_db)):
    """Verify 2FA password and complete sign in"""
    try:
        result = await telegram_manager.verify_2fa(
            request.phone_or_username,
            request.password
        )
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail="2FA verification failed")
        
        # Get user info
        user_info = result["user_info"]
        session_string = result["session_string"]
        
        # Determine role
        is_admin = settings.is_admin(
            phone=user_info.get("phone_number"),
            username=user_info.get("username")
        )
        role = UserRole.ADMIN if is_admin else UserRole.USER
        
        # Check if user exists
        existing_user = db.table("users").select("*").eq("telegram_id", user_info["telegram_id"]).execute()
        
        if existing_user.data and len(existing_user.data) > 0:
            # Update existing user
            user_data = existing_user.data[0]
            user_id = user_data["id"]
            
            db.table("users").update({
                "phone_number": user_info.get("phone_number"),
                "username": user_info.get("username"),
                "first_name": user_info.get("first_name"),
                "last_name": user_info.get("last_name"),
                "role": role.value
            }).eq("id", user_id).execute()
        else:
            # Create new user
            new_user = db.table("users").insert({
                "telegram_id": user_info["telegram_id"],
                "phone_number": user_info.get("phone_number"),
                "username": user_info.get("username"),
                "first_name": user_info.get("first_name"),
                "last_name": user_info.get("last_name"),
                "role": role.value
            }).execute()
            
            user_id = new_user.data[0]["id"]
        
        # Save Telethon session
        await telegram_manager.save_session(user_id, session_string)
        
        # Get updated user data
        user_response = db.table("users").select("*").eq("id", user_id).execute()
        user = UserResponse(**user_response.data[0])
        
        # Create JWT tokens
        access_token = create_access_token({"sub": user_id})
        refresh_token = create_refresh_token({"sub": user_id})
        
        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=user
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh", response_model=AuthResponse)
async def refresh_token(request: RefreshTokenRequest, db=Depends(get_db)):
    """Refresh access token using refresh token"""
    try:
        payload = verify_refresh_token(request.refresh_token)
        user_id = payload.get("sub")
        
        # Get user data
        user_response = db.table("users").select("*").eq("id", user_id).execute()
        if not user_response.data or len(user_response.data) == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = UserResponse(**user_response.data[0])
        
        # Create new tokens
        access_token = create_access_token({"sub": user_id})
        new_refresh_token = create_refresh_token({"sub": user_id})
        
        return AuthResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            user=user
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: UserResponse = Depends(get_current_user)):
    """Get current user info"""
    return current_user


@router.post("/logout")
async def logout(current_user: UserResponse = Depends(get_current_user)):
    """Logout (client-side token deletion only)"""
    # In a real implementation, you might want to blacklist the token
    # For now, just return success and let client delete the token
    return {"success": True, "message": "Logged out successfully"}
