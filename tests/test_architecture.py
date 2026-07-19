from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

os.environ.setdefault("BBM_ADMIN_TOKEN", "test-token")
os.environ.setdefault("BBM_ALLOW_LEGACY_TOKEN_AUTH", "1")
os.environ.setdefault("BBM_DATABASE_URL", "sqlite://")

from app import service
from app.database import Base, SessionLocal, engine
from app.models import Host, Job, Repository, Run
from app.runner import Command


PROJECT_ROOT = Path(__file__).parents[1]


def test_repository_sshd_is_supervised_and_required_by_healthcheck():
    entrypoint = (PROJECT_ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "/usr/sbin/sshd -D -E /data/logs/sshd.log &" in entrypoint
    assert 'kill -0 "$sshd_pid"' in entrypoint
    assert "Repository sshd stopped unexpectedly" in entrypoint
    assert 'banner.startswith(b"SSH-")' in entrypoint
    assert 'BBM_HEALTH_REQUIRE_SSHD: ${BBM_HEALTH_REQUIRE_SSHD:-1}' in compose
    assert "/api/ready" in compose
    assert "/api/health" not in compose


def test_forced_command_restricts_each_key_to_exact_repository():
    wrapper = (PROJECT_ROOT / "docker/borg-serve.sh").read_text(encoding="utf-8")
    sshd = (PROJECT_ROOT / "docker/sshd_config").read_text(encoding="utf-8")

    assert 'borg serve --restrict-to-repository "$repository"' in wrapper
    assert "--restrict-to-path" not in wrapper
    assert "AuthenticationMethods publickey" in sshd
    assert "AllowTcpForwarding no" in sshd
    assert "PermitTTY no" in sshd


def test_same_repository_runs_are_serialized(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        repository = Repository(
            name=f"serialization-{suffix}",
            location=f"/tmp/serialization-{suffix}",
            extra_env_json="{}",
            initialized=True,
        )
        db.add(repository)
        db.flush()
        first = Run(repository_id=repository.id, action="info", status="queued")
        second = Run(repository_id=repository.id, action="info", status="queued")
        db.add_all([first, second])
        db.commit()
        first_id, second_id = first.id, second.id

    active = 0
    maximum_active = 0

    async def controlled_execute(_command, **_kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.03)
        active -= 1
        return 0, "ok", ""

    monkeypatch.setattr(service, "execute", controlled_execute)

    async def run_both():
        await asyncio.gather(
            service.execute_run(first_id, Command(["true"], "true")),
            service.execute_run(second_id, Command(["true"], "true")),
        )

    asyncio.run(run_both())

    assert maximum_active == 1
    with SessionLocal() as db:
        assert db.get(Run, first_id).status == "success"
        assert db.get(Run, second_id).status == "success"



def test_database_fifo_serializes_repository_runs_without_shared_asyncio_lock(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        repository = Repository(
            name=f"database-fifo-{suffix}",
            location=f"/tmp/database-fifo-{suffix}",
            extra_env_json="{}",
            initialized=True,
        )
        db.add(repository)
        db.flush()
        first = Run(repository_id=repository.id, action="info", status="queued")
        second = Run(repository_id=repository.id, action="info", status="queued")
        db.add_all([first, second])
        db.commit()
        first_id, second_id = first.id, second.id

    active = 0
    maximum_active = 0

    async def controlled_execute(_command, **_kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.03)
        active -= 1
        return 0, "ok", ""

    monkeypatch.setattr(service, "execute", controlled_execute)
    monkeypatch.setattr(service, "_repository_lock", lambda _repository_id: None)

    async def run_both():
        await asyncio.gather(
            service.execute_run(first_id, Command(["true"], "true")),
            service.execute_run(second_id, Command(["true"], "true")),
        )

    asyncio.run(run_both())

    assert maximum_active == 1


def test_same_physical_repository_records_share_one_queue(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    shared_location = f"/tmp/shared-physical-{suffix}"
    with SessionLocal() as db:
        first_repository = Repository(
            name=f"physical-a-{suffix}", location=shared_location,
            extra_env_json="{}", initialized=True,
        )
        second_repository = Repository(
            name=f"physical-b-{suffix}", location=shared_location,
            extra_env_json="{}", initialized=True,
        )
        db.add_all([first_repository, second_repository])
        db.flush()
        first = Run(repository_id=first_repository.id, action="info", status="queued")
        second = Run(repository_id=second_repository.id, action="info", status="queued")
        db.add_all([first, second])
        db.commit()
        first_id, second_id = first.id, second.id

    active = 0
    maximum_active = 0

    async def controlled_execute(_command, **_kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.03)
        active -= 1
        return 0, "ok", ""

    monkeypatch.setattr(service, "execute", controlled_execute)

    async def run_both():
        await asyncio.gather(
            service.execute_run(first_id, Command(["true"], "true")),
            service.execute_run(second_id, Command(["true"], "true")),
        )

    asyncio.run(run_both())

    assert maximum_active == 1


def test_relocation_confirmation_is_deduplicated_per_device_and_repository(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        host = Host(
            name=f"confirm-host-{suffix}", address="127.0.0.1", port=22,
            username="root", host_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest", enabled=True,
        )
        repository = Repository(
            name=f"confirm-repo-{suffix}", location=f"/tmp/confirm-{suffix}",
            extra_env_json="{}", initialized=True,
        )
        db.add_all([host, repository])
        db.flush()
        first_job = Job(
            name=f"confirm-job-a-{suffix}", host_id=host.id, repository_id=repository.id,
            source_paths_json='["/srv/a"]', exclude_patterns_json="[]",
            archive_prefix=f"confirm-a-{suffix}-", archive_prefix_history_json="[]",
            prune_options_json="{}", create_options_json="{}", enabled=True,
        )
        second_job = Job(
            name=f"confirm-job-b-{suffix}", host_id=host.id, repository_id=repository.id,
            source_paths_json='["/srv/b"]', exclude_patterns_json="[]",
            archive_prefix=f"confirm-b-{suffix}-", archive_prefix_history_json="[]",
            prune_options_json="{}", create_options_json="{}", enabled=True,
        )
        db.add_all([first_job, second_job])
        db.commit()
        first_job_id, second_job_id = first_job.id, second_job.id

    class DummyTask:
        pass

    def fake_create_task(coroutine):
        coroutine.close()
        return DummyTask()

    monkeypatch.setattr(service, "repository_command", lambda _job, _action: Command(["true"], "true"))
    monkeypatch.setattr(service.asyncio, "create_task", fake_create_task)

    first_run_id = service.queue_job_action(first_job_id, "confirm-location")
    second_run_id = service.queue_job_action(second_job_id, "confirm-location")

    assert second_run_id == first_run_id
    with SessionLocal() as db:
        rows = db.scalars(select(Run).where(Run.action == "confirm-location", Run.id == first_run_id)).all()
        assert len(rows) == 1

def test_server_logs_are_size_rotated():
    entrypoint = (PROJECT_ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert 'BBM_LOG_MAX_BYTES:-10485760' in entrypoint
    assert 'rotate_log /data/logs/sshd.log' in entrypoint
    assert 'rotate_log /data/logs/borg-serve.log' in entrypoint
    assert 'BBM_LOG_ROTATIONS: ${BBM_LOG_ROTATIONS:-5}' in compose


def test_container_uses_debian_trixie_and_borg_14():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "python:3.13.14-slim-trixie" in dockerfile
    assert "bookworm" not in dockerfile
    assert "backports" not in dockerfile
    assert "borgbackup" in dockerfile
    assert 'dpkg --compare-versions "$borg_version" ge 1.4.0' in dockerfile
    assert 'dpkg --compare-versions "$borg_version" lt 2.0' in dockerfile


def test_webui_is_https_only_with_persistent_tls_and_secure_sessions():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    entrypoint = (PROJECT_ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")
    main = (PROJECT_ROOT / "app/main.py").read_text(encoding="utf-8")
    request_security = (PROJECT_ROOT / "app/request_security.py").read_text(encoding="utf-8")

    assert "EXPOSE 8443 2222" in dockerfile
    assert "${BBM_HTTPS_PORT:-8443}:8443" in compose
    assert ":8080" not in compose
    assert "--ssl-certfile" in entrypoint
    assert "--ssl-keyfile" in entrypoint
    assert "/run/bbm-secrets/tls" in entrypoint
    assert "httponly=True" in main
    assert "secure=_request_uses_https(request)" in main
    assert "x-forwarded-proto" in request_security
    assert "is_trusted_proxy" in request_security
    assert 'samesite="strict"' in main
    assert "--no-proxy-headers" in entrypoint
    assert "runuser -u borg -- env HOME=/repositories" in entrypoint
    assert 'Cache-Control' in main and 'no-store' in main


def test_historical_default_cookie_name_is_normalized_without_replacing_bind_mount():
    config = (PROJECT_ROOT / "app/config.py").read_text(encoding="utf-8")
    entrypoint = (PROJECT_ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")
    updater = (PROJECT_ROOT / "update.sh").read_text(encoding="utf-8")
    assert '_CONFIGURED_SESSION_COOKIE_NAME in {"", "bbm_session"}' in config
    assert 'SESSION_COOKIE_NAME = (' in config
    assert "Historical session cookie name detected; using bbm_session_v2 at runtime" in entrypoint
    assert "sed -i 's/^BBM_SESSION_COOKIE_NAME" not in entrypoint
    assert 'current[index] = "BBM_SESSION_COOKIE_NAME=bbm_session_v2"' in updater


def test_job_actions_and_restore_ui_are_refresh_stable_and_explicit():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert "openJobActions" in javascript
    assert "loadAll(true)" in javascript
    assert "archive-export" in javascript
    assert "restore_mode" in html
    assert "selection-root" in html
    assert "Auswahl exportieren (.tar.gz)" in html
    assert "#job-list { max-height: none; overflow: visible" in css


def test_authentication_uses_hashed_passwords_and_server_side_sessions():
    security_store = (PROJECT_ROOT / "app/security_store.py").read_text(encoding="utf-8")
    security = (PROJECT_ROOT / "app/security.py").read_text(encoding="utf-8")

    assert "hashlib.scrypt" in security_store
    assert "token_hash = hashlib.sha256" in security_store
    assert "CREATE TABLE IF NOT EXISTS sessions" in security_store
    assert "ALLOW_LEGACY_TOKEN_AUTH" in security
    assert "hmac.compare_digest" in security


def test_installer_defaults_to_persistent_docker_data_paths():
    installer = (PROJECT_ROOT / "install.sh").read_text(encoding="utf-8")
    restore = (PROJECT_ROOT / "restore-backup.sh").read_text(encoding="utf-8")
    assert 'DEFAULT_BASE_PATH="/docker_data/borgbackup-manager"' in installer
    assert 'DEFAULT_DATA_PATH="$DEFAULT_BASE_PATH/data"' in installer
    assert 'DEFAULT_REPOSITORY_PATH="$DEFAULT_BASE_PATH/repositories"' in installer
    assert '"${existing_data:-$DEFAULT_DATA_PATH}"' in installer
    assert '"${existing_repositories:-$DEFAULT_REPOSITORY_PATH}"' in installer
    assert 'DEFAULT_BASE_PATH="/docker_data/borgbackup-manager"' in restore
    assert 'DEFAULT_DATA_PATH="$DEFAULT_BASE_PATH/data"' in restore
    assert 'DEFAULT_REPOSITORY_PATH="$DEFAULT_BASE_PATH/repositories"' in restore
    assert 'env_value BBM_DATA_PATH "$DEFAULT_DATA_PATH"' in restore
    assert 'env_value BBM_REPOSITORY_PATH "$DEFAULT_REPOSITORY_PATH"' in restore


def test_update_healthcheck_separates_readiness_from_component_diagnostics():
    update = (PROJECT_ROOT / "update.sh").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "probe_https_endpoint /api/ready" in update
    assert "probe_https_endpoint /api/health/strict" in update
    assert "probe_https_endpoint /" in update
    assert "for attempt in {1..90}" in update
    assert "Das Update wird nicht zurückgerollt" in update
    assert "/api/ready" in compose


def test_release_uses_stable_compose_and_image_names():
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert compose.startswith("name: borgbackup-manager\n")
    assert "image: borgbackup-manager:latest" in compose
    assert "container_name: borgbackup-manager" in compose


def test_exclusion_templates_are_editable_and_reusable_in_job_form():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert 'id="job-exclude-template"' in html
    assert 'id="apply-exclude-template"' in html
    assert 'id="exclude-template-editor"' in html
    assert 'id="add-exclude-template"' in html
    assert "collectExcludeTemplates" in javascript
    assert "Vorlage zur Liste hinzufügen" in html
    assert "if (!merged.includes(pattern)) merged.push(pattern)" in javascript
    assert "#release-content" in css
    assert "white-space: pre-wrap" in css
    assert "overflow-wrap: anywhere" in css


def test_installer_uses_readiness_endpoint():
    installer = (PROJECT_ROOT / "install.sh").read_text(encoding="utf-8")
    assert "https://127.0.0.1:8443/api/ready" in installer
    assert "https://127.0.0.1:8443/api/health" not in installer


def test_operational_views_use_compact_tables_and_filtered_runs():
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")

    assert "bbmAction('goToRuns', 'failed')" in javascript
    assert "status=${encodeURIComponent(state.runFilter)}" in javascript
    assert 'id="runs-filter"' in html
    assert 'id="job-search"' in html
    assert ".data-table" in css
    assert "Europe/Berlin" in html


def test_container_and_remote_borg_commands_use_europe_berlin():
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    runner_source = (PROJECT_ROOT / "app/runner.py").read_text(encoding="utf-8")
    main_source = (PROJECT_ROOT / "app/main.py").read_text(encoding="utf-8")

    assert "TZ: ${TZ:-Europe/Berlin}" in compose
    assert '"TZ": APP_TIMEZONE_NAME' in runner_source
    assert "AsyncIOScheduler(timezone=APP_TIMEZONE)" in main_source
    assert "schedule_expressions(schedule.expressions)" in main_source
    assert "CronTrigger.from_crontab(expression, timezone=APP_TIMEZONE)" in main_source
    assert "id=f\"schedule-{schedule.id}-job-{job_id}-{index}\"" in main_source


def test_job_workspace_and_manager_backup_ui_are_restructured():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert 'class="jobs-stack"' in html
    assert 'class="panel job-form-compact"' in html
    assert html.index('id="job-form"') < html.index('id="job-list"')
    assert '.job-form-grid.basics' in css
    assert '.retention-grid' in css
    assert 'id="rotate-controller-key"' in html
    assert '/system/controller-key/rotate' in javascript
    assert 'id="backup-encrypted"' not in html
    assert 'id="backup-passphrase-fields"' in html
    assert 'minlength="12"' in html
    assert 'id="backup-restore-form"' in html
    assert '/restore`' in javascript
    assert '.bbm' in html


def test_restore_script_supports_encrypted_manager_backups():
    restore = (PROJECT_ROOT / "restore-backup.sh").read_text(encoding="utf-8")
    assert "BBM-BACKUP-1" in restore
    assert "python3-cryptography" in restore
    assert "AESGCM" in restore
    assert "Scrypt" in restore
    assert "Backup-Passphrase" in restore


def test_security_migration_removes_legacy_secrets_from_host_env():
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    entrypoint = (PROJECT_ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")

    assert "env_file:" not in compose
    assert "BBM_ADMIN_TOKEN:" not in compose
    assert "BBM_SECRET_KEY:" not in compose
    assert "./.env:/run/bbm-host.env" in compose
    assert "python -m app.security_bootstrap" in entrypoint
    assert 'legacy = {"BBM_ADMIN_TOKEN", "BBM_SECRET_KEY", "BBM_ALLOW_LEGACY_TOKEN_AUTH"}' in entrypoint
    assert "removed from the host .env" in entrypoint


def test_security_bootstrap_migrates_manager_schema_before_repository_reads():
    bootstrap = (PROJECT_ROOT / "app/security_bootstrap.py").read_text(encoding="utf-8")

    assert "from app.security_migrate import run_security_migration" in bootstrap
    migration_pos = bootstrap.index("migration = run_security_migration()")
    key_material_pos = bootstrap.index("_migrate_or_generate_ed25519(", migration_pos)
    assert migration_pos < key_material_pos


def test_schedule_editor_supports_multiple_times_and_common_presets():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    for mode in ("daily", "weekdays", "weekends", "selected", "monthly", "custom"):
        assert f'value="{mode}"' in html
    assert 'id="add-schedule-time"' in html
    assert "function buildScheduleExpressions()" in javascript
    assert "expressions.join(';')" in javascript


def test_user_password_reset_uses_masked_dialog_not_javascript_prompt():
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")

    assert 'id="user-password-dialog"' in html
    assert 'name="password" type="password"' in html
    assert "$('#user-password-dialog').showModal()" in javascript
    assert "prompt('Neues temporäres Passwort" not in javascript


def test_favicon_density_and_help_are_present():
    project = Path(__file__).resolve().parents[1]
    html = (project / "app/static/index.html").read_text(encoding="utf-8")
    css = (project / "app/static/style.css").read_text(encoding="utf-8")
    assert 'favicon.svg' in html and 'rel="icon"' in html
    assert (project / "app/static/favicon.svg").is_file()
    assert "Maximale Höhe der Archivübersicht und weiterer Scrolllisten" in html
    assert "body.compact input" in css
    assert ".help-toc" in css
    assert "Fehlerausgabe (gefiltert)" in html
    assert (project / "app/static/help.de.html").is_file()
    assert (project / "app/static/help.en.html").is_file()


def test_help_quick_links_use_router_sections_and_checkpoint_controls_exist():
    project = Path(__file__).resolve().parents[1]
    html = (project / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (project / "app/static/app.js").read_text(encoding="utf-8")

    help_de = (project / "app/static/help.de.html").read_text(encoding="utf-8")
    help_en = (project / "app/static/help.en.html").read_text(encoding="utf-8")
    assert 'href="#help?section=help-start"' in help_de
    assert 'href="#help?section=help-start"' in help_en
    assert 'href="#help-start"' not in help_de
    assert "function loadHelpLanguage" in javascript
    assert "function scrollToHelpSection(section" in javascript
    assert "view === 'help'" in javascript
    assert "scrollToHelpSection(parsed.section" in javascript
    assert 'id="archive-consider-checkpoints"' in html
    assert 'name="consider_checkpoints"' in html
    assert "consider_checkpoints=${considerCheckpoints}" in javascript


def test_repository_workspace_is_stacked_responsive_and_distinguishes_add_from_create():
    project = Path(__file__).resolve().parents[1]
    html = (project / "app/static/index.html").read_text(encoding="utf-8")
    css = (project / "app/static/style.css").read_text(encoding="utf-8")
    javascript = (project / "app/static/app.js").read_text(encoding="utf-8")

    assert 'class="repositories-stack"' in html
    assert html.index('id="repo-form"') < html.index('id="repo-list"')
    assert 'Extern – vorhandenes Borg-Repository hinzufügen' in html
    assert '„Hinzufügen“ initialisiert oder überschreibt das externe Repository nicht.' in html
    assert "$('#repo-submit').textContent = 'Repository hinzufügen'" in javascript
    assert "$('#repo-submit').textContent = 'Repository erstellen'" in javascript
    assert "showRepositoryDiagnostic" in javascript
    assert "Größe berechnen" in javascript
    assert ".repositories-table" in css
    assert ".repository-table-scroll { overflow-x: hidden; }" in css
    assert "/data/security/master.key" in html


def test_second_repository_run_remains_queued_until_first_finishes(monkeypatch):
    Base.metadata.create_all(engine)
    suffix = uuid4().hex
    with SessionLocal() as db:
        repository = Repository(
            name=f"queue-state-{suffix}", location=f"/tmp/queue-state-{suffix}",
            extra_env_json="{}", initialized=True,
        )
        db.add(repository); db.flush()
        first = Run(repository_id=repository.id, action="backup", status="queued")
        second = Run(repository_id=repository.id, action="backup", status="queued")
        db.add_all([first, second]); db.commit()
        first_id, second_id = first.id, second.id

    first_started = asyncio.Event()
    release_first = asyncio.Event()
    calls = 0

    async def controlled_execute(_command, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            await release_first.wait()
        return 0, "ok", ""

    monkeypatch.setattr(service, "execute", controlled_execute)

    async def scenario():
        first_task = asyncio.create_task(service.execute_run(first_id, Command(["true"], "true")))
        await first_started.wait()
        second_task = asyncio.create_task(service.execute_run(second_id, Command(["true"], "true")))
        await asyncio.sleep(0.02)
        with SessionLocal() as db:
            assert db.get(Run, first_id).status == "running"
            assert db.get(Run, second_id).status == "queued"
        release_first.set()
        await asyncio.gather(first_task, second_task)

    asyncio.run(scenario())


def test_release_has_central_schedules_queue_metric_hostname_and_typed_key_confirmation():
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    main = (PROJECT_ROOT / "app/main.py").read_text(encoding="utf-8")

    assert "hostname: bbm" in compose
    assert 'id="view-schedules"' in html
    assert 'data-view="schedules"' in html
    assert 'id="schedule-form"' in html
    assert 'name="schedule"' not in html
    assert 'CONTROLLER-SCHLÜSSEL ERNEUERN' in html
    assert "waiting: 'Wartend'" in javascript
    assert "waiting: ['goToRuns', 'queued']" in javascript
    assert "schedule_mode" in javascript and "schedule_names" in javascript
    assert '"waiting": db.scalar' in main


def test_update_output_is_compact_and_reports_authentication_state():
    update = (PROJECT_ROOT / "update.sh").read_text(encoding="utf-8")
    main = (PROJECT_ROOT / "app/main.py").read_text(encoding="utf-8")
    assert 'response.read(1024)' in update
    assert 'content_type == "text/html"' in update
    assert 'attempt >= 15' in update
    assert 'python -m app.account_recovery status --json' in update
    assert 'python -m app.account_recovery reset admin --admin' in update
    assert 'authentication_readiness()' in main
    assert 'payload = {"status": "ready" if is_ready else "starting"}' in main
    assert 'active_administrators' not in main[main.index('@app.get("/api/ready")'):main.index('@app.get("/api/health")')]


def test_frontend_dom_references_exist_and_login_is_not_admin_prefilled():
    import re

    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    html_ids = set(re.findall(r'id="([^"]+)"', html))
    direct_id_selectors = set(re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)", javascript))

    assert direct_id_selectors <= html_ids
    login_match = re.search(r'<form[^>]*id="login-form"[^>]*>.*?</form>', html, flags=re.S)
    assert login_match is not None
    login_form = login_match.group(0)
    assert 'id="login-username"' in login_form
    assert 'autocomplete="username"' in login_form
    assert 'autofocus' in login_form
    assert 'value="admin"' not in login_form
    assert "Sichere HTTPS-Anmeldung mit persönlichem Benutzerkonto" not in login_form
    assert "Erstanmeldung:" not in login_form
    assert 'id="login-version"' in login_form
    assert 'onsubmit="return false"' not in html
    assert '<script>' not in html
    assert "loginForm.addEventListener('submit', submitLogin)" in javascript
    assert "$('#repo-env-field')" not in javascript


def test_public_readiness_exposes_current_version():
    main = (PROJECT_ROOT / "app/main.py").read_text(encoding="utf-8")
    assert '"version": APP_VERSION' in main


def test_release_contains_interactive_recovery_script_and_archive_statistics_ui():
    recovery = (PROJECT_ROOT / "recovery.sh").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    database = (PROJECT_ROOT / "app/database.py").read_text(encoding="utf-8")
    assert "app.account_recovery status" in recovery
    assert "app.initial_admin" in recovery
    assert "app.account_recovery unlock" in recovery
    assert "app.account_recovery reset" in recovery
    assert "reset-admin" in recovery
    update = (PROJECT_ROOT / "update.sh").read_text(encoding="utf-8")
    assert "compose.yaml Dockerfile install.sh update.sh recovery.sh restore-backup.sh" in update
    assert '"install.sh", "update.sh", "recovery.sh", "restore-backup.sh"' in update
    assert "Originalgröße" in javascript
    assert "Komprimierte Größe" in javascript
    assert "Deduplizierte Größe dieses Archivs" in javascript
    assert "formatDuration" in javascript
    assert javascript.index('<small>Original</small>') < javascript.index('<small>Dedupliziert</small>') < javascript.index('<small>Komprimiert</small>')
    css = (PROJECT_ROOT / "app/static/style.css").read_text(encoding="utf-8")
    assert "grid-template-columns: minmax(6.5rem, 1fr) auto" in css
    assert ".archive-row .actions button" in css
    assert '"original_size_bytes": "INTEGER"' in database
    assert '"compressed_size_bytes": "INTEGER"' in database
    assert '"deduplicated_size_bytes": "INTEGER"' in database


def test_update_backup_excludes_repository_tree_and_regenerable_borg_cache():
    update = (PROJECT_ROOT / "update.sh").read_text(encoding="utf-8")
    assert "env_value BBM_REPOSITORY_PATH" in update
    assert "repository_relative" in update
    assert "--exclude='./borg-cache'" in update
    assert "Repository-Unterverzeichnis wird vom Manager-Datenbackup ausgeschlossen" in update
    assert '.tar.gz.partial' not in update  # partial path is derived from final archive, not exposed as a stale release file


def test_repository_location_confirmation_is_admin_only_in_ui_and_api():
    main = (PROJECT_ROOT / "app/main.py").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert 'confirm-repository-location", status_code=202, dependencies=admin_protected' in main
    assert 'if action == "confirm-location"' in main
    assert "Geänderten Repository-Standort bestätigen" in javascript
    assert "confirmRepositoryLocation" in javascript


def test_archive_cache_is_regenerable_and_ui_exposes_explicit_repository_refresh():
    config = (PROJECT_ROOT / "app/config.py").read_text(encoding="utf-8")
    entrypoint = (PROJECT_ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")
    update = (PROJECT_ROOT / "update.sh").read_text(encoding="utf-8")
    html = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    service = (PROJECT_ROOT / "app/service.py").read_text(encoding="utf-8")

    assert 'ARCHIVE_CACHE_DIR = Path(os.getenv("BBM_ARCHIVE_CACHE_DIR"' in config
    assert "/data/archive-cache" in entrypoint
    assert "--exclude='./archive-cache'" in update
    assert 'id="refresh-archives"' in html
    assert "force_refresh=${forceRefresh}" in javascript
    assert "invalidate_archive_cache(repository_id)" in service


def test_env_example_is_complete_and_matches_compose_defaults():
    sample = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    expected = {
        "TZ", "BBM_HTTPS_PORT", "BBM_REPOSITORY_SSH_PORT", "BBM_REPOSITORY_PUBLIC_HOST",
        "BBM_TLS_HOSTS", "BBM_DATA_PATH", "BBM_REPOSITORY_PATH", "BBM_BORG_UID",
        "BBM_BORG_GID", "BBM_SESSION_TTL_SECONDS", "BBM_SESSION_COOKIE_NAME", "BBM_SESSION_COOKIE_SECURE",
        "BBM_COMMAND_TIMEOUT", "BBM_APPEARANCE", "BBM_REPOSITORY_SIZE_AFTER_RUN",
        "BBM_STORAGE_GUARD_ENABLED", "BBM_STORAGE_GUARD_THRESHOLD_PERCENT",
        "BBM_HEALTH_REQUIRE_SSHD", "BBM_LOG_MAX_BYTES", "BBM_LOG_ROTATIONS",
    }
    import re
    keys = {match.group(1) for match in re.finditer(r"^([A-Z][A-Z0-9_]*)=", sample, re.M)}
    assert expected <= keys
    assert "BBM_DATA_PATH=/docker_data/borgbackup-manager/data" in sample
    assert "BBM_REPOSITORY_PATH=/docker_data/borgbackup-manager/repositories" in sample
    assert "BBM_HEALTH_REQUIRE_SSHD: ${BBM_HEALTH_REQUIRE_SSHD:-1}" in compose
    assert "BBM_APPEARANCE: ${BBM_APPEARANCE:-auto}" in compose
    assert "BBM_HTTPS_PORT: ${BBM_HTTPS_PORT:-8443}" in compose
    assert "BBM_DATA_PATH: ${BBM_DATA_PATH:-./data}" in compose
    assert "BBM_REPOSITORY_PATH: ${BBM_REPOSITORY_PATH:-./repositories}" in compose


def test_installer_preserves_extended_env_and_rejects_identical_paths():
    installer = (PROJECT_ROOT / "install.sh").read_text(encoding="utf-8")
    for key in (
        "BBM_SESSION_COOKIE_NAME", "BBM_SESSION_COOKIE_SECURE", "BBM_COMMAND_TIMEOUT", "BBM_APPEARANCE",
        "BBM_REPOSITORY_SIZE_AFTER_RUN", "BBM_HEALTH_REQUIRE_SSHD",
        "BBM_LOG_MAX_BYTES", "BBM_LOG_ROTATIONS",
    ):
        assert f"{key}=" in installer
    assert "Unbekannte/erweiterte Schlüssel" in installer
    assert "Daten- und Repository-Verzeichnis dürfen nicht identisch sein" in installer
    assert "validate_positive_integer" in installer
    assert "validate_boolean" in installer
    assert "validate_cookie_name" in installer


def test_update_validates_complete_release_and_recovers_stopped_container_on_abort():
    update = (PROJECT_ROOT / "update.sh").read_text(encoding="utf-8")
    assert '".env.example", "VERSION"' in update
    assert '"README.md", "README.de.md", "INSTALLATION.md", "INSTALLATION.de.md", "RELEASE_NOTES.md", "RELEASE_NOTES.de.md"' in update
    assert "cleanup_on_exit" in update
    assert "compose start borg-manager" in update
    assert "CONTAINER_STOPPED=1" in update
    assert "ACTIVE_PARTIAL" in update
    assert "--one-file-system" in update
    assert "max(updates, key=lambda item" in update


def test_manager_backup_preserves_extended_environment_values():
    backups = (PROJECT_ROOT / "app/backups.py").read_text(encoding="utf-8")
    restore = (PROJECT_ROOT / "restore-backup.sh").read_text(encoding="utf-8")
    for key in (
        "BBM_SESSION_COOKIE_NAME", "BBM_SESSION_COOKIE_SECURE", "BBM_COMMAND_TIMEOUT", "BBM_APPEARANCE",
        "BBM_REPOSITORY_SIZE_AFTER_RUN", "BBM_HEALTH_REQUIRE_SSHD",
        "BBM_LOG_MAX_BYTES", "BBM_LOG_ROTATIONS",
    ):
        assert key in backups
        assert key in restore


def test_shell_management_scripts_share_safe_runtime_conventions():
    installer = (PROJECT_ROOT / "install.sh").read_text(encoding="utf-8")
    recovery = (PROJECT_ROOT / "recovery.sh").read_text(encoding="utf-8")
    restore = (PROJECT_ROOT / "restore-backup.sh").read_text(encoding="utf-8")
    entrypoint = (PROJECT_ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")

    assert installer.index('timezone="${TZ:-${existing_timezone:-$DEFAULT_TIMEZONE}}"') < installer.index('validate_timezone "$timezone"')
    assert 'PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"' in recovery
    assert 'sudo docker info' in recovery
    assert 'safe_relative_path(relative, "Berechtigungspfad")' in restore
    assert 'Daten- und Repository-Pfad dürfen nicht identisch sein' in restore
    assert 'BBM_LOG_MAX_BYTES must be greater than zero' in entrypoint


def test_repository_reset_ui_is_safe_and_disables_missing_repository_actions():
    app_js = (PROJECT_ROOT / "app/static/app.js").read_text(encoding="utf-8")
    main_py = (PROJECT_ROOT / "app/main.py").read_text(encoding="utf-8")
    service_py = (PROJECT_ROOT / "app/service.py").read_text(encoding="utf-8")

    assert "resetRepositoryState" in app_js
    assert "Es werden keine Repository-Dateien gelöscht" in app_js
    assert "Repository fehlt" in app_js
    assert "repositoryReady" in app_js
    assert '/repositories/${id}/reset' in app_js
    assert '@app.post("/api/repositories/{repository_id}/reset"' in main_py
    assert "require_empty_managed_repository(repository)" in service_py
    assert 'action="repository-reset"' in service_py
