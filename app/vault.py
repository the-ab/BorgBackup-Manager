from __future__ import annotations

import json
import re

from app.models import Repository
from app.security_store import delete_secret, delete_secret_scope, get_secret, list_secret_names, secret_exists, set_secret

SYSTEM_SCOPE = "system"
SENSITIVE_ENV_RE = re.compile(r"(?:PASS|PASSWORD|PASSPHRASE|SECRET|TOKEN|PRIVATE|CREDENTIAL|KEY)", re.IGNORECASE)


def repository_scope(repository_or_id: Repository | int) -> str:
    repository_id = repository_or_id.id if isinstance(repository_or_id, Repository) else repository_or_id
    if not repository_id:
        raise ValueError("Repository muss vor der Speicherung von Geheimnissen vorhanden sein")
    return f"repository:{int(repository_id)}"


def set_repository_secret(repository_or_id: Repository | int, name: str, value: str | None) -> None:
    scope = repository_scope(repository_or_id)
    if value is None or value == "":
        delete_secret(scope, name)
    else:
        set_secret(scope, name, value)


def get_repository_secret(repository_or_id: Repository | int, name: str, default: str | None = None) -> str | None:
    value = get_secret(repository_scope(repository_or_id), name)
    return value if value is not None else default


def repository_secret_exists(repository_or_id: Repository | int, name: str) -> bool:
    return secret_exists(repository_scope(repository_or_id), name)


def delete_repository_secrets(repository_or_id: Repository | int) -> int:
    return delete_secret_scope(repository_scope(repository_or_id))


def split_repository_environment(values: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    public: dict[str, str] = {}
    sensitive: dict[str, str] = {}
    for key, value in values.items():
        (sensitive if SENSITIVE_ENV_RE.search(key) else public)[key] = value
    return public, sensitive


def store_repository_environment(repository_or_id: Repository | int, values: dict[str, str]) -> dict[str, str]:
    public, sensitive = split_repository_environment(values)
    scope = repository_scope(repository_or_id)
    existing = {name for name in list_secret_names(scope) if name.startswith("env.")}
    desired = {f"env.{key}" for key in sensitive}
    for stale in existing - desired:
        delete_secret(scope, stale)
    for key, value in sensitive.items():
        set_secret(scope, f"env.{key}", value)
    return public


def load_repository_environment(repository: Repository) -> dict[str, str]:
    public = json.loads(repository.extra_env_json or "{}")
    scope = repository_scope(repository)
    for name in list_secret_names(scope):
        if name.startswith("env."):
            value = get_secret(scope, name)
            if value is not None:
                public[name[4:]] = value
    return {str(key): str(value) for key, value in public.items()}



def set_system_secret(name: str, value: str) -> None:
    set_secret(SYSTEM_SCOPE, name, value)


def get_system_secret(name: str, default: str | None = None) -> str | None:
    return get_secret(SYSTEM_SCOPE, name, default)


