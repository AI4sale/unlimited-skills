"""Shared fixtures for the cross-repo e2e integration tests.

Several e2e runners under ``scripts/run-*-e2e.py`` are imported and executed
IN-PROCESS by these tests (via ``importlib``), and some mutate ``os.environ``
globally — ``UNLIMITED_SKILLS_HOME``, ``HOME``, ``USERPROFILE``, manifest keys —
pointing at a temp dir that is deleted on exit. Without restoration that leaks a
now-dead home into every later test in the same ``pytest`` process: it makes
``unlimited_skills_home()`` resolve to a gone temp path, which has repointed a
real launcher's ``--root`` at a temp library and taken the local router down.

This autouse fixture snapshots and restores the process environment (and the
working directory) around EVERY integration test, so no runner can leak env
across tests or into the developer's real ``~/.claude``. It is defence in depth:
runners should also restore their own env, but this guarantees isolation for the
whole class even if one forgets.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_process_env():
    saved_env = dict(os.environ)
    saved_cwd = os.getcwd()
    try:
        yield
    finally:
        try:
            os.chdir(saved_cwd)
        except OSError:
            pass
        # Restore os.environ exactly: drop keys a test added, restore the rest.
        for key in [k for k in os.environ if k not in saved_env]:
            del os.environ[key]
        for key, value in saved_env.items():
            if os.environ.get(key) != value:
                os.environ[key] = value
