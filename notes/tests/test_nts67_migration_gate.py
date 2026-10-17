"""NTS-67 — prove the migration gate's red path with a NON-NOTES unapplied
migration, executing the SAME shell used by deploy.yml.

The deploy gate (scripts/migration-gate.sh) runs `manage.py migrate --check`
after rollout and, on failure, prints a PROJECT-WIDE diagnostic
(`showmigrations` + `migrate --plan`). NTS-58 added the gate but its failure
branch was never exercised, and the old diagnostic (`showmigrations notes`) was
narrower than the check (`migrate --check` scans every app) — a non-notes
unapplied migration would have pointed nowhere.

This test builds an ISOLATED Django project (temp dir, sqlite) with two apps:
  * `notes`  — a fully-applied app (green-converged control)
  * `other`  — a NON-notes app; we introduce an unapplied migration on top of an
               applied base, then run the real gate script.

It proves:
  1. green control  -> gate exits 0
  2. non-notes unapplied migration -> gate exits non-zero
  3. the red output names the actual `other` app/migration and does NOT present
     an all-[X] notes-only listing as the cause.

The proof executes scripts/migration-gate.sh via subprocess (the literal file
deploy.yml calls) — not a reimplementation. Isolated + read-only: no production
schema is touched, and the throwaway project is deleted on teardown.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts" / "migration-gate.sh"

# A settings module adequate for the isolated project. No Postgres / Redis /
# JWT / allauth — sqlite only, deliberately NOT importing notesmanager.settings.
SETTINGS_PY = '''\
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

SECRET_KEY = "nts67-gate-test"
DEBUG = False
USE_TZ = True

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "notes",
    "other",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(BASE_DIR / "gate_test.sqlite3"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
'''

MANAGE_PY = '''\
#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
'''

# Real migrations: they exercise the migration GRAPH and the applied-vs-
# available state that `migrate --check` inspects, against the isolated sqlite
# DB. Deterministic and engine-agnostic (no Postgres-only operations). Migration
# 0001 creates the model; 0002+ add a field — so a chained multi-migration app
# applies cleanly and each later migration depends on its predecessor (single
# chain, no conflicting leaf nodes).
CREATE_MIGRATION = '''\
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = {deps}
    operations = [
        migrations.CreateModel(
            name="{ModelName}",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("label", models.CharField(default="", max_length=64)),
            ],
        ),
    ]
'''

ADDFIELD_MIGRATION = '''\
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = {deps}
    operations = [
        migrations.AddField(
            model_name="{ModelName}",
            name="extra",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
'''

APPS_PY = '''\
from django.apps import AppConfig


class {name}Config(AppConfig):
    name = "{name}"
    default_auto_field = "django.db.models.BigAutoField"
'''

MODELS_PY = '''\
from django.db import models


class {ModelName}(models.Model):
    label = models.CharField(default="", max_length=64)
    extra = models.CharField(blank=True, default="", max_length=64)
'''


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _build_app(base: Path, name: str, migrations_count: int) -> None:
    model = f"{name.title()}Record"
    appdir = base / name
    _write(appdir / "__init__.py", "")
    _write(appdir / "apps.py", APPS_PY.format(name=name))
    _write(appdir / "models.py", MODELS_PY.format(ModelName=model))
    migs = appdir / "migrations"
    _write(migs / "__init__.py", "")
    for i in range(1, migrations_count + 1):
        if i == 1:
            deps = "[]"
            body = CREATE_MIGRATION
        else:
            deps = f'[("{name}", "000{i - 1}_auto")]'
            body = ADDFIELD_MIGRATION
        _write(
            migs / f"000{i}_auto.py",
            body.format(deps=deps, ModelName=model),
        )


def _run_gate(project: Path, python_bin: str) -> "subprocess.CompletedProcess[str]":
    """Run the REAL deploy gate script against the isolated project."""
    env = dict(os.environ)
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env["PYTHON_BIN"] = python_bin
    return subprocess.run(
        ["bash", str(GATE)],
        cwd=str(project),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


class MigrationGateRedPathTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="nts67-gate-")
        self.project = Path(self._tmp)
        _write(self.project / "manage.py", MANAGE_PY)
        _write(self.project / "settings.py", SETTINGS_PY)
        # notes: applied in full (2 migrations, both applied at migrate time).
        _build_app(self.project, "notes", 2)
        # other: applied base (1 migration) + later an UNAPPLIED 2nd migration.
        _build_app(self.project, "other", 1)
        self.python = os.environ.get(
            "NTS67_PYTHON_BIN", sys.executable
        )

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _migrate_all(self):
        run = subprocess.run(
            [self.python, "manage.py", "migrate", "--noinput"],
            cwd=str(self.project),
            env={key:value for key,value in os.environ.items() if key != "DJANGO_SETTINGS_MODULE"},
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_green_converged_project_passes_gate(self):
        self._migrate_all()
        proc = _run_gate(self.project, self.python)
        self.assertEqual(
            proc.returncode, 0,
            f"expected gate exit 0 on a fully-migrated project; got "
            f"{proc.returncode}\nstdout:{proc.stdout}\nstderr:{proc.stderr}",
        )
        self.assertIn("OK schema converged", proc.stdout + proc.stderr)

    def test_non_notes_unapplied_migration_reds_gate_with_project_wide_diagnostic(self):
        self._migrate_all()
        # Introduce an unapplied migration in the NON-notes app `other`.
        _build_app(self.project, "other", 2)

        proc = _run_gate(self.project, self.python)
        combined = proc.stdout + proc.stderr

        self.assertNotEqual(
            proc.returncode, 0,
            "gate must fail when a non-notes app has an unapplied migration "
            f"(NTS-58 was never red); stdout:\n{combined}",
        )

        # The project-wide diagnostic must NAME the actual non-notes app and its
        # unapplied migration. `showmigrations` marks unapplied with `[ ]` and
        # `migrate --plan` lists the pending migration path.
        self.assertIn("other", combined, combined)
        self.assertIn("0002_auto", combined, combined)
        self.assertIn("[ ]", combined, combined)
        self.assertIn("migrate --plan", combined, combined)

    def test_diagnostic_does_not_blame_notes_all_x_listing(self):
        """An all-[X] notes listing must NOT be presented as the cause.

        The old diagnostic (`showmigrations notes`) could only ever print a
        fully-applied notes list, which pointed away from the real culprit.
        The project-wide diagnostic must keep notes green while `other` shows
        its unapplied migration.
        """
        self._migrate_all()
        _build_app(self.project, "other", 2)

        proc = _run_gate(self.project, self.python)
        combined = proc.stdout + proc.stderr

        # Notes must appear fully applied ([X] on all of its migrations).
        notes_section = combined.split("notes", 1)
        self.assertTrue(len(notes_section) > 1, combined)
        self.assertNotIn("[ ]", combined.split("other", 1)[0].split("notes", 1)[-1])

        # The unapplied marker must belong to `other`, the real culprit.
        other_section = combined.split("other", 1)[-1]
        self.assertIn("[ ]", other_section, combined)

    def test_deploy_workflow_invokes_the_same_script(self):
        """deploy.yml must call scripts/migration-gate.sh (the file this test
        executes), so the red path proven here is the one gatekeeping prod."""
        workflow = (ROOT / ".forgejo/workflows/deploy.yml").read_text()
        self.assertIn("bash /app/scripts/migration-gate.sh", workflow)
        self.assertIn("scripts/migration-gate.sh", workflow)
        # The deploy gate must no longer run a notes-scoped showmigrations in its
        # failure branch (that diagnostic could never name a non-notes culprit).
        gate_failure_branch = GATE.read_text().split("if run_dj migrate --check", 1)[1]
        self.assertNotIn("showmigrations notes", workflow)
        self.assertIn("run_dj showmigrations", gate_failure_branch)
        self.assertIn("run_dj migrate --plan", gate_failure_branch)


if __name__ == "__main__":
    unittest.main()
