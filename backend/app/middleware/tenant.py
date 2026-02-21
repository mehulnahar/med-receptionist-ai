from uuid import UUID
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.middleware.auth import get_current_user


async def get_practice_id(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> UUID:
    """
    Extract practice_id from the current user.
    Super admins must specify practice_id via X-Practice-Id header or practice_id query param.
    Practice admins and secretaries use their own practice_id.
    """
    if current_user.role == "super_admin":
        # Try header first, then query param
        resolved = None
        header_val = request.headers.get("X-Practice-Id")
        if header_val:
            try:
                resolved = UUID(header_val)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid UUID in X-Practice-Id header.",
                )
        else:
            qp = request.query_params.get("practice_id")
            if qp:
                try:
                    resolved = UUID(qp)
                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid UUID in practice_id query param.",
                    )

        if resolved is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Super admin must specify a practice context. Use X-Practice-Id header or practice_id query param.",
            )
        return resolved

    if current_user.practice_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with any practice.",
        )

    return current_user.practice_id


async def get_optional_practice_id(
    current_user: User = Depends(get_current_user),
) -> UUID | None:
    """
    Same as get_practice_id but returns None for super admins
    without a practice context (useful for global views).
    """
    return current_user.practice_id
