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

from shared.config import ADMIN_EMAIL, NEXTAUTH_SECRET

_security = HTTPBearer()


def verify_admin_token(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> str:
    """Dependency injected into every admin route. Returns the verified admin email."""
    token = credentials.credentials

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
