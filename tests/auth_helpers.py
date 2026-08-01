from app.config import SESSION_COOKIE_NAME
from app import security_store

TEST_ADMIN_PASSWORD = "Current-Test-Admin-2026!"


def admin_headers() -> dict[str, str]:
    security_store.initialize_security_store()
    users = security_store.list_users()
    admin = next(item for item in users if item["role"] == "admin")
    user = security_store.authenticate_user(str(admin["username"]), TEST_ADMIN_PASSWORD)
    if user is None:
        security_store.set_user_password(int(admin["id"]), TEST_ADMIN_PASSWORD, must_change_password=False)
        user = security_store.authenticate_user(str(admin["username"]), TEST_ADMIN_PASSWORD)
    assert user is not None
    token = security_store.create_session(user, 24 * 60 * 60)
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}", "X-BBM-Request": "1"}
