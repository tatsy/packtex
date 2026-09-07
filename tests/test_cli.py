"""Tests for the command line surface, including ``python -m packtex``."""

import sys
import subprocess

import pytest
from conftest import namelist

from packtex import __version__
from packtex.cli import main, build_parser


def module_run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, '-m', 'packtex', *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestModuleInvocation:
    def test_reports_its_version(self):
        proc = module_run('--version')
        assert proc.returncode == 0
        assert proc.stdout.strip() == f'packtex {__version__}'

    def test_help_uses_the_command_name_not_the_module_path(self):
        # argparse would otherwise print '__main__.py' as the program name.
        proc = module_run('--help')
        assert proc.returncode == 0
        assert proc.stdout.startswith('usage: packtex')

    def test_packs_a_project(self, project, tmp_path):
        output = tmp_path / 'out.zip'
        proc = module_run(str(project / 'main.tex'), '-o', str(output))
        assert proc.returncode == 0, proc.stderr
        assert 'main.tex' in namelist(output)

    def test_reports_failure_through_the_exit_code(self, project, tmp_path):
        proc = module_run(str(project / 'nope.tex'), '-o', str(tmp_path / 'out.zip'))
        assert proc.returncode == 1
        assert 'is not a file' in proc.stderr


class TestMain:
    def test_returns_zero_and_writes_the_archive(self, project, tmp_path):
        output = tmp_path / 'out.zip'
        assert main([str(project / 'main.tex'), '-o', str(output)]) == 0
        assert output.is_file()

    def test_returns_one_when_the_main_file_is_missing(self, project, tmp_path):
        assert main([str(project / 'nope.tex'), '-o', str(tmp_path / 'out.zip')]) == 1

    def test_returns_one_on_unresolved_references_under_strict(self, project, tmp_path):
        assert main([str(project / 'main.tex'), '-o', str(tmp_path / 'out.zip'), '--strict']) == 1


class TestParser:
    def test_exclude_takes_several_values(self):
        args = build_parser().parse_args(['main.tex', '--exclude', 'a', 'b'])
        assert args.exclude == ['a', 'b']

    def test_repeated_exclude_flags_accumulate(self):
        args = build_parser().parse_args(['main.tex', '--exclude', 'a', '--exclude', 'b'])
        assert args.exclude == ['a', 'b']

    def test_exclude_defaults_to_empty(self):
        assert build_parser().parse_args(['main.tex']).exclude == []

    def test_default_does_not_leak_between_parses(self):
        build_parser().parse_args(['main.tex', '--exclude', 'a'])
        assert build_parser().parse_args(['main.tex']).exclude == []

    def test_version_exits_cleanly(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            build_parser().parse_args(['--version'])
        assert excinfo.value.code == 0
        assert capsys.readouterr().out.strip() == f'packtex {__version__}'
