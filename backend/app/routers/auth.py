"""
Auth Router — Login, 2FA, Refresh Token, Logout
Uses Supabase Auth under the hood.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client as SupabaseClient

from app.dependencies import (
    get_current_user,
    get_supabase,
    get_supabase_auth,
    require_org_admin,
    require_superadmin,
)
from app.models.user import LoginRequest, OTPVerifyRequest, TokenResponse, RefreshRequest, UserProfile
from app.authz import EffectiveRole, fetch_effective_role

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, supabase: SupabaseClient = Depends(get_supabase_auth)):
    """
    Authenticate with email + password.
    Returns JWT access_token and refresh_token.
    If 2FA is enabled, the first step returns a partial session
    and the client must call /verify-otp.
    """
    try:
        response = supabase.auth.sign_in_with_password({
            "email": payload.email,
            "password": payload.password,
        })

        if not response.session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email ou senha inválidos.",
            )

        return TokenResponse(
            access_token=response.session.access_token,
            refresh_token=response.session.refresh_token,
            expires_in=response.session.expires_in,
            user={
                "id": response.user.id,
                "email": response.user.email,
                "role": response.user.role,
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Falha no login: {str(e)}",
        )


@router.post("/verify-otp")
async def verify_otp(payload: OTPVerifyRequest, supabase: SupabaseClient = Depends(get_supabase_auth)):
    """Verify the 2FA OTP code sent via email."""
    try:
        response = supabase.auth.verify_otp({
            "email": payload.email,
            "token": payload.token,
            "type": "email",
        })

        if not response.session:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Código OTP inválido ou expirado.",
            )

        return TokenResponse(
            access_token=response.session.access_token,
            refresh_token=response.session.refresh_token,
            expires_in=response.session.expires_in,
            user={
                "id": response.user.id,
                "email": response.user.email,
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro na verificação OTP: {str(e)}",
        )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(payload: RefreshRequest, supabase: SupabaseClient = Depends(get_supabase_auth)):
    """Refresh the JWT token using the refresh_token (for 14-day session persistence)."""
    try:
        response = supabase.auth.refresh_session(payload.refresh_token)

        if not response.session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token inválido.",
            )

        return TokenResponse(
            access_token=response.session.access_token,
            refresh_token=response.session.refresh_token,
            expires_in=response.session.expires_in,
            user={
                "id": response.user.id,
                "email": response.user.email,
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Erro ao renovar sessão: {str(e)}",
        )


@router.post("/logout")
async def logout(supabase: SupabaseClient = Depends(get_supabase_auth), user=Depends(get_current_user)):
    """Sign out the current user."""
    try:
        supabase.auth.sign_out()
        return {"message": "Logout realizado com sucesso."}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro no logout: {str(e)}",
        )


@router.get("/me", response_model=UserProfile)
async def get_me(
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Perfil atual + flags RBAC (superadmin, org, read_only, funil atribuído)."""
    eff = fetch_effective_role(supabase, user)
    full_name: Optional[str] = None
    try:
        res = (
            supabase.table("profiles")
            .select("full_name, is_superadmin, organization_id")
            .eq("id", str(user.id))
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            row = rows[0]
            full_name = row.get("full_name")
    except Exception:
        pass

    oid = eff.effective_organization_id
    organization_id = str(oid) if oid is not None else None

    return UserProfile(
        id=str(user.id),
        email=user.email or "",
        full_name=full_name or (user.user_metadata.get("full_name") if user.user_metadata else None),
        role=str(user.role) if user.role is not None else None,
        avatar_url=user.user_metadata.get("avatar_url") if user.user_metadata else None,
        is_superadmin=eff.is_superadmin,
        organization_id=organization_id,
        is_read_only=eff.is_read_only,
        assigned_funnel_id=eff.assigned_funnel_id,
        is_org_admin=eff.is_org_admin,
    )


@router.get("/rbac/superadmin")
async def rbac_probe_superadmin(_role: EffectiveRole = Depends(require_superadmin)):
    """Prova de dependência: 200 só para superadmin; caso contrário 403."""
    return {"ok": True, "scope": "superadmin"}


@router.get("/rbac/org-admin")
async def rbac_probe_org_admin(_role: EffectiveRole = Depends(require_org_admin)):
    """Prova de dependência: 200 para superadmin ou admin de org (ou legado admin sem membership); 403 para read_only."""
    return {"ok": True, "scope": "org_admin"}
