from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from app.config import DATA_DIR
from app.external_repository import generate_ed25519_keypair, public_key_from_private
from app.security_migrate import run_security_migration
from app.vault import get_system_secret, set_system_secret, system_secret_exists

RUNTIME_ROOT = Path(os.getenv("BBM_RUNTIME_SECRET_DIR", "/run/bbm-secrets"))


def _chmod_if_owned(path: Path, mode: int) -> None:
    """Apply permissions only when the current process owns the path.

    The container entrypoint prepares /run/bbm-secrets as root and deliberately
    keeps the SSH host private key root-owned.  The Web API later runs as the
    unprivileged borg user, so a repeated bootstrap must not try to chmod those
    root-owned paths.
    """
    info = path.stat()
    if os.geteuid() == 0 or info.st_uid == os.geteuid():
        os.chmod(path, mode)


def _safe_prepared_private_file(path: Path) -> bool:
    """Accept an already prepared, root-owned private runtime file.

    This is used only for the repository SSH host key.  Its contents are not
    readable by the Web API by design, but the entrypoint has already generated
    it and validates sshd before starting the API.
    """
    try:
        info = path.stat()
    except FileNotFoundError:
        return False
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == 0
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_size > 0
    )


def _write_runtime(
    path: Path,
    value: str,
    mode: int,
    *,
    allow_prepared_root_private: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = path.read_text(encoding="utf-8") if path.exists() else None
    except PermissionError:
        if allow_prepared_root_private and _safe_prepared_private_file(path):
            return
        raise

    if current == value:
        _chmod_if_owned(path, mode)
        return

    path.write_text(value, encoding="utf-8")
    _chmod_if_owned(path, mode)


def _read_first(paths: list[Path]) -> str | None:
    for path in paths:
        if path.is_file() and path.stat().st_size:
            return path.read_text(encoding="utf-8")
    return None


def _migrate_or_generate_ed25519(private_name: str, public_name: str, old_private: list[Path], comment: str) -> tuple[str, str]:
    private = get_system_secret(private_name)
    public = get_system_secret(public_name)
    if not private:
        private = _read_first(old_private)
        if private:
            public = public_key_from_private(private, comment)
        else:
            private, public = generate_ed25519_keypair(comment)
        set_system_secret(private_name, private)
        set_system_secret(public_name, public)
    elif not public:
        public = public_key_from_private(private, comment)
        set_system_secret(public_name, public)
    for path in old_private:
        path.unlink(missing_ok=True)
        Path(str(path) + ".pub").unlink(missing_ok=True)
    assert public is not None
    return private, public


def _generate_tls(hosts: str) -> tuple[str, str]:
    host_values = [value.strip() for value in hosts.split(",") if value.strip()]
    if not host_values:
        host_values = ["localhost", "127.0.0.1"]
    common_name = host_values[0]
    sans: list[str] = []
    for host in host_values:
        try:
            import ipaddress
            ipaddress.ip_address(host)
            sans.append(f"IP:{host}")
        except ValueError:
            sans.append(f"DNS:{host}")
    with tempfile.TemporaryDirectory(prefix="bbm-tls-") as directory:
        key = Path(directory) / "privkey.pem"
        cert = Path(directory) / "fullchain.pem"
        result = subprocess.run(
            [
                "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:3072", "-sha256", "-days", "825",
                "-keyout", str(key), "-out", str(cert), "-subj", f"/CN={common_name}",
                "-addext", f"subjectAltName={','.join(sans)}",
            ],
            capture_output=True, text=True, check=False, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "TLS-Zertifikat konnte nicht erzeugt werden")
        return cert.read_text(encoding="utf-8"), key.read_text(encoding="utf-8")


def bootstrap_security_material() -> dict[str, int | bool]:
    migration = run_security_migration()
    migrated = int(migration["repository_secrets_migrated"])
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    _chmod_if_owned(RUNTIME_ROOT, 0o700)

    controller_private, controller_public = _migrate_or_generate_ed25519(
        "controller_private_key", "controller_public_key",
        [DATA_DIR / "ssh" / "id_ed25519"], "borgbackup-manager-controller",
    )

    repository_private, repository_public = _migrate_or_generate_ed25519(
        "repository_ssh_host_private_key", "repository_ssh_host_public_key",
        [DATA_DIR / "repository-ssh" / "ssh_host_ed25519_key"], "borgbackup-manager-repository-host",
    )
    _write_runtime(
        RUNTIME_ROOT / "repository-ssh" / "ssh_host_ed25519_key",
        repository_private,
        0o600,
        allow_prepared_root_private=True,
    )
    _write_runtime(RUNTIME_ROOT / "repository-ssh" / "ssh_host_ed25519_key.pub", repository_public.rstrip() + "\n", 0o644)

    tls_cert = get_system_secret("tls_certificate")
    tls_key = get_system_secret("tls_private_key")
    old_cert = Path(os.getenv("BBM_TLS_CERT_FILE", str(DATA_DIR / "tls" / "fullchain.pem")))
    old_key = Path(os.getenv("BBM_TLS_KEY_FILE", str(DATA_DIR / "tls" / "privkey.pem")))
    if not tls_cert or not tls_key:
        if old_cert.is_file() and old_key.is_file() and old_cert.stat().st_size and old_key.stat().st_size:
            tls_cert = old_cert.read_text(encoding="utf-8")
            tls_key = old_key.read_text(encoding="utf-8")
        else:
            hosts = os.getenv("BBM_TLS_HOSTS", f"{os.getenv('BBM_REPOSITORY_PUBLIC_HOST', 'localhost')},localhost,127.0.0.1")
            tls_cert, tls_key = _generate_tls(hosts)
        set_system_secret("tls_certificate", tls_cert)
        set_system_secret("tls_private_key", tls_key)
    old_key.unlink(missing_ok=True)
    old_cert.unlink(missing_ok=True)
    _write_runtime(RUNTIME_ROOT / "tls" / "fullchain.pem", tls_cert, 0o644)
    _write_runtime(RUNTIME_ROOT / "tls" / "privkey.pem", tls_key, 0o600)

    # Remove obsolete persistent controller material and keyfile cache.
    shutil.rmtree(DATA_DIR / "ssh", ignore_errors=True)
    shutil.rmtree(DATA_DIR / "repository-keys", ignore_errors=True)
    # Alte persistente TLS-/Host-Key-Verzeichnisse dürfen keine privaten Schlüssel mehr enthalten.
    for legacy in [DATA_DIR / "tls", DATA_DIR / "repository-ssh"]:
        if legacy.is_dir():
            for item in legacy.iterdir():
                if item.name != "authorized_keys":
                    if item.is_dir(): shutil.rmtree(item, ignore_errors=True)
                    else: item.unlink(missing_ok=True)
    return {"repository_secrets_migrated": migrated, "controller_ready": bool(controller_private), "tls_ready": bool(tls_key)}


if __name__ == "__main__":
    result = bootstrap_security_material()
    print(
        "Security material ready: "
        f"repository_secrets_migrated={result['repository_secrets_migrated']}, "
        f"controller_ready={result['controller_ready']}, tls_ready={result['tls_ready']}"
    )
