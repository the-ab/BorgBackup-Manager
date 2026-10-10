"""Execute the browser session flow against controlled HTTP responses."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is required for UI behavior tests")

SESSION_FLOW = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const scenario = JSON.parse(process.argv[2]);
function section(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  if (from < 0 || to < 0) throw new Error('Session flow section is missing');
  return source.slice(from, to);
}
const nodes = {};
function node(selector) {
  if (!nodes[selector]) {
    const classes = new Set(
      ['#app', '#login-second-factor-field'].includes(selector) ? ['hidden'] : []
    );
    nodes[selector] = {
      textContent: '', value: 'synthetic-input', required: false,
      classList: {
        add: (name) => classes.add(name),
        remove: (name) => classes.delete(name),
        contains: (name) => classes.has(name),
      },
      focus() {},
    };
  }
  return nodes[selector];
}
const storage = new Map();
if (scenario.reloadToken) storage.set('bbm-session-reload-v1', scenario.reloadToken);
const calls = [];
const state = {currentUser: null};
let loaded = 0;
const context = vm.createContext({
  state,
  $: node,
  sessionStorage: {
    getItem(key) {
      if (scenario.storageBlocked) throw new Error('Browser storage is blocked');
      return storage.get(key) || null;
    },
    setItem(key, value) {
      if (scenario.storageBlocked) throw new Error('Browser storage is blocked');
      storage.set(key, value);
    },
    removeItem(key) { storage.delete(key); },
  },
  fetch: async (url, options) => {
    calls.push({url, credentials: options.credentials, headers: options.headers});
    if (url === '/api/auth/login') {
      return {ok: true, status: 200, json: async () => ({reload_token: 'synthetic-new-session'})};
    }
    if (scenario.networkFailure) throw new TypeError('Network unavailable');
    return {
      ok: scenario.status === 200,
      status: scenario.status,
      headers: {get: (name) => name === 'X-BBM-Session-State' ? (scenario.sessionState || null) : null},
      json: async () => scenario.status === 200
        ? {id: 1, username: 'test-user', must_change_password: false}
        : {detail: scenario.detail || 'Session check failed'},
    };
  },
  applyUserPreferences() {},
  applyUserPermissions() {},
  goToView() {},
  hashView: () => 'dashboard',
  openPasswordDialog() {},
  loadAll: async () => { loaded += 1; },
  scheduleSystemHealthPoll() {},
  scheduleHeaderNetworkPoll() {},
});
vm.runInContext([
  section("const RELOAD_SESSION_KEY =", "const $ ="),
  section("class ApiError extends Error {", "function browserSafeErrorMessage("),
  section("let loginInProgress = false;", "const loginForm ="),
  section("async function restoreBrowserSession() {", "restoreBrowserSession();"),
  "globalThis.runRestore = restoreBrowserSession; globalThis.runLogin = submitLogin;",
].join('\n'), context);
(async () => {
  if (scenario.login) await context.runLogin({preventDefault() {}});
  else await context.runRestore();
  console.log(JSON.stringify({
    error: node('#login-error').textContent,
    loginVisible: !node('#login').classList.contains('hidden'),
    appVisible: !node('#app').classList.contains('hidden'),
    authenticated: Boolean(state.currentUser),
    reloadStored: storage.has('bbm-session-reload-v1'),
    calls,
    loaded,
  }));
})().catch((error) => { console.error(error); process.exit(1); });
"""


def session_flow(**scenario):
    completed = subprocess.run(
        [NODE, "-e", SESSION_FLOW, str(PROJECT_ROOT / "app/static/app.js"), json.dumps(scenario)],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    return json.loads(completed.stdout)


def test_unauthenticated_login_page_reload_does_not_show_session_warning():
    result = session_flow(status=401, sessionState="missing", detail="No session cookie or reload token")
    assert result["loginVisible"] and not result["appVisible"]
    assert not result["authenticated"]
    assert result["error"] == ""
    assert result["calls"] == [{
        "url": "/api/auth/status", "credentials": "same-origin", "headers": {},
    }]


@pytest.mark.parametrize("reload_token", ["", "synthetic-stale-session"])
def test_invalid_or_expired_session_still_shows_warning_and_clears_reload_token(reload_token):
    result = session_flow(status=401, detail="Stored session expired", reloadToken=reload_token)
    assert result["loginVisible"] and not result["authenticated"]
    assert result["error"] == "Sitzung konnte nicht wiederhergestellt werden: Stored session expired"
    assert not result["reloadStored"]


@pytest.mark.parametrize("reload_token", ["", "synthetic-valid-session"])
def test_valid_cookie_or_reload_session_restores_application(reload_token):
    result = session_flow(status=200, reloadToken=reload_token)
    assert result["authenticated"] and result["appVisible"] and not result["loginVisible"]
    assert result["error"] == ""
    assert result["loaded"] == 1
    expected_headers = {"Authorization": f"BBM-Reload {reload_token}"} if reload_token else {}
    assert result["calls"][0]["headers"] == expected_headers


def test_missing_session_after_login_is_still_reported_as_login_failure():
    result = session_flow(
        status=401, sessionState="missing", login=True, storageBlocked=True,
        detail="Browser did not retain the login session",
    )
    assert not result["authenticated"] and result["loginVisible"]
    assert result["error"] == "Anmeldung fehlgeschlagen: Browser did not retain the login session"
    assert [call["url"] for call in result["calls"]] == ["/api/auth/login", "/api/auth/status"]


@pytest.mark.parametrize("scenario", [{"status": 503}, {"networkFailure": True}])
def test_transport_failure_does_not_clear_reload_session_or_claim_expiry(scenario):
    result = session_flow(reloadToken="synthetic-valid-session", **scenario)
    assert result["loginVisible"] and not result["authenticated"]
    assert result["error"] == ""
    assert result["reloadStored"]
