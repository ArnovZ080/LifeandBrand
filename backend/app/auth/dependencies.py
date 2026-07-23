from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.database import get_db
from app.auth.security import decode_token
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.get(User, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def get_subtree_ids(db: Session, root_org_unit_id: int) -> list[int]:
    """Recursive CTE — returns the ID of root and all descendant OrgUnits."""
    result = db.execute(
        text("""
            WITH RECURSIVE subtree AS (
                SELECT id FROM org_units WHERE id = :root_id
                UNION ALL
                SELECT o.id FROM org_units o
                INNER JOIN subtree s ON o.parent_id = s.id
            )
            SELECT id FROM subtree
        """),
        {"root_id": root_org_unit_id},
    )
    return [row[0] for row in result]


def get_accessible_org_unit_ids(
    requested_org_unit_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[int]:
    """
    Returns org_unit IDs the caller may query.
    - No requested_id: the user's full subtree.
    - Specific requested_id: that unit only, validated to be in the caller's subtree.
    """
    allowed = get_subtree_ids(db, current_user.org_unit_id)
    if requested_org_unit_id is None:
        return allowed
    if requested_org_unit_id not in allowed:
        raise HTTPException(status_code=403, detail="Access to this org unit is not allowed")
    return [requested_org_unit_id]
