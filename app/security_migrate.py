from __future__ import annotations

from sqlalchemy import select

from app.config import LEGACY_ADMIN_TOKEN
from app.database import Base, SessionLocal, engine, migrate_schema
from app.models import Repository
from app.security_store import initialize_security_store
from app.vault import migrate_repository_row_secrets


def migrate_repository_secrets() -> int:
    migrated = 0
    with SessionLocal() as db:
        for repository in db.scalars(select(Repository)):
            migrated += migrate_repository_row_secrets(repository)
        if migrated:
            db.commit()
    return migrated


def run_security_migration() -> dict:
    Base.metadata.create_all(engine)
    migrate_schema()
    result = initialize_security_store(LEGACY_ADMIN_TOKEN)
    result["repository_secrets_migrated"] = migrate_repository_secrets()
    return result


if __name__ == "__main__":
    result = run_security_migration()
    print(
        "Security store ready: "
        f"users={result['users']}, created={result['created']}, "
        f"repository_secrets_migrated={result['repository_secrets_migrated']}"
    )
