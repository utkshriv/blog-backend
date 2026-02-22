"""
JWT validation for admin routes.

The frontend (NextAuth.js) must send an HS256-signed JWT in the Authorization header:

    Authorization: Bearer <token>

The token must contain an "email" claim matching ADMIN_EMAIL.

Frontend reference (Next.js API route or server action):
    import { SignJWT } from "jose"
    const token = await new SignJWT({ email: session.user.email })
        .setProtectedHeader({ alg: "HS256" })
        .setExpirationTime("1h")
        .sign(new TextEncoder().encode(process.env.NEXTAUTH_SECRET))
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt

from shared.config import ADMIN_EMAIL, NEXTAUTH_SECRET, MCP_API_KEY

_security = HTTPBearer()


def verify_admin_token(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> str:
    """
    Dependency injected into every admin route. Returns the verified admin email.

    Supports two authentication methods:
    1. JWT tokens from NextAuth (for frontend)
    2. Long-lived API keys (for MCP server and automation)
    """
    token = credentials.credentials

    # Check if it's an API key (starts with "btf_")
    if token.startswith("btf_"):
        if not MCP_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="MCP_API_KEY not configured",
            )

        if token == MCP_API_KEY:
            return "mcp-server"  # Return a synthetic identity for API key auth
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Otherwise, validate as JWT
    if not NEXTAUTH_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="NEXTAUTH_SECRET not configured",
        )

    try:
        payload = jwt.decode(token, NEXTAUTH_SECRET, algorithms=["HS256"])
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    email: str | None = payload.get("email")
    if not email or email.lower() != ADMIN_EMAIL.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized",
        )

    return email
