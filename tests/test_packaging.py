"""Opt-in tests that the project installs and exposes its entry points.

The flat layout puts the working tree on ``sys.path``, so the rest of the suite
cannot tell a correct wheel from a broken one - ``import packtex`` and
``python -m packtex`` would keep working even if the build configuration stopped
shipping the package.  These tests install the project into a throwaway
virtualenv and drive the *installed* copy instead.

Every subprocess runs from a neutral directory: with the flat layout, running
from the repository root would put the working tree back on ``sys.path`` and
defeat the whole point.  Marked ``slow`` because building the project and
creating a virtualenv takes a few seconds, and needs network access the first
time (pip fetches the build backend).  Run with ``pytest -m slow``.
"""

import os
import venv
import zipfile
import subprocess
from pathlib import Path

import pytest

from packtex import __version__


ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.slow


@pytest.fixture(scope='module')
def installed(tmp_path_factory) -> Path:
    """Install the project into a fresh virtualenv; return its scripts directory."""
    env = tmp_path_factory.mktemp('install') / 'env'
    venv.create(env, with_pip=True)
    binaries = env / ('Scripts' if os.name == 'nt' else 'bin')

    proc = subprocess.run(
        [str(binaries / 'python'), '-m', 'pip', 'install', '--quiet', str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f'pip install failed:\n{proc.stdout}\n{proc.stderr}'
    return binaries


@pytest.fixture(scope='module')
def elsewhere(tmp_path_factory) -> Path:
    """A directory outside the repository, safe to use as a working directory."""
    return tmp_path_factory.mktemp('elsewhere')


def run(binaries: Path, executable: str, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(binaries / executable), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        check=False,
    )


class TestEntryPoints:
    def test_module_entry_point_works(self, installed, elsewhere):
        proc = run(installed, 'python', '-m', 'packtex', '--version', cwd=elsewhere)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == f'packtex {__version__}'

    def test_console_script_works(self, installed, elsewhere):
        proc = run(installed, 'packtex', '--version', cwd=elsewhere)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == f'packtex {__version__}'

    def test_help_names_the_command_not_the_module(self, installed, elsewhere):
        proc = run(installed, 'python', '-m', 'packtex', '--help', cwd=elsewhere)
        assert proc.stdout.startswith('usage: packtex')


class TestWheelContents:
    def test_package_is_imported_from_site_packages(self, installed, elsewhere):
        proc = run(
            installed,
            'python',
            '-c',
            'import packtex; print(packtex.__file__)',
            cwd=elsewhere,
        )
        assert proc.returncode == 0, proc.stderr
        assert 'site-packages' in proc.stdout
        assert str(ROOT) not in proc.stdout

    def test_every_module_ships(self, installed, elsewhere):
        modules = ('cli', 'pack', 'pdf', 'tex', 'util')
        imports = '; '.join(f'import packtex.{name}' for name in modules)
        proc = run(installed, 'python', '-c', f'{imports}; print("ok")', cwd=elsewhere)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == 'ok'

    def test_no_stray_top_level_module_is_installed(self, installed, elsewhere):
        # Regression guard: a wheel built with packages = ["src"] used to install
        # a top-level 'src' module that would collide with other projects.
        proc = run(
            installed,
            'python',
            '-c',
            "import importlib.util as u; print(u.find_spec('src') is not None)",
            cwd=elsewhere,
        )
        assert proc.stdout.strip() == 'False'


class TestInstalledBehaviour:
    def test_the_installed_copy_packs_a_project(self, installed, project, tmp_path):
        output = tmp_path / 'installed.zip'
        proc = run(
            installed,
            'packtex',
            str(project / 'main.tex'),
            '-o',
            str(output),
            cwd=project.parent,
        )
        assert proc.returncode == 0, proc.stderr

        with zipfile.ZipFile(output) as archive:
            entries = sorted(archive.namelist())
        assert 'main.tex' in entries
        assert 'sec/intro.tex' in entries
        assert 'main.pdf' not in entries
