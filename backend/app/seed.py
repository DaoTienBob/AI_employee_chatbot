"""Demo users for local development (T03).

Per roadmap §3.4 there are three employee roles (employee, hr, manager);
administrator permission is a separate flag on the user, not a role. These
accounts exist so login can be demonstrated before any admin UI exists.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import User
from backend.app.security import hash_password

DEMO_PASSWORD = "password123"

# email -> (full name, role, is_admin)
DEMO_USERS: dict[str, tuple[str, str, bool]] = {
    "employee@company.com": ("Dana Employee", "employee", False),
    "hr@company.com": ("Hana HR", "hr", False),
    "manager@company.com": ("Marc Manager", "manager", False),
    # Admin permission is separate from the employee role (§3.4).
    "admin@company.com": ("Ava Admin", "employee", True),
}


def seed_demo_users(db: Session) -> None:
    """Create the demo users once; safe to call on every startup."""
    for email, (full_name, role, is_admin) in DEMO_USERS.items():
        exists = db.scalar(select(User).where(User.email == email))
        if exists is not None:
            continue
        db.add(
            User(
                email=email,
                full_name=full_name,
                hashed_password=hash_password(DEMO_PASSWORD),
                role=role,
                is_admin=is_admin,
            )
        )
    db.commit()