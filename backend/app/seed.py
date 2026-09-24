"""Demo users for local development (T03).

Per roadmap §3.4 there are three employee roles (employee, hr, manager);
administrator permission is a separate flag on the user, not a role. These
accounts exist so login can be demonstrated before any admin UI exists.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import User
from backend.app.security import hash_password

logger = logging.getLogger(__name__)

DEMO_PASSWORD = "password123"

# email -> (full name, role, is_admin)
DEMO_USERS: dict[str, tuple[str, str, bool]] = {
    "employee@company.com": ("Dana Employee", "employee", False),
    "hr@company.com": ("Hana HR", "hr", False),
    "manager@company.com": ("Marc Manager", "manager", False),
    # Admin permission is separate from the employee role (§3.4).
    "admin@company.com": ("Ava Admin", "employee", True),
    # Aliases matching UI placeholder / documentation
    "employee@example.com": ("Dana Employee", "employee", False),
    "hr@example.com": ("Hana HR", "hr", False),
    "manager@example.com": ("Marc Manager", "manager", False),
    "admin@example.com": ("Ava Admin", "employee", True),
}


def seed_demo_users(db: Session) -> None:
    """Create the demo users once; safe to call on every startup.

    Demo accounts (including two administrator accounts with a known password)
    are only seeded when the application runs in debug mode. Non-debug
    deployments must provision real users out of band.
    """
    if not get_settings().debug:
        logger.info("Skipping demo user seeding (debug mode disabled)")
        return
    # One existence query for the whole batch instead of one per account.
    existing = set(db.scalars(
        select(User.email).where(User.email.in_(DEMO_USERS))
    ))
    for email, (full_name, role, is_admin) in DEMO_USERS.items():
        if email in existing:
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
    logger.info("Seeded %d demo user(s)", len(DEMO_USERS) - len(existing & set(DEMO_USERS)))