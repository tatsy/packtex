"""End-to-end tests for source collection and archive writing."""

from pathlib import Path

import pytest
from conftest import JUNK, write, namelist, read_entry

from packtex.pack import Packer, Options, PackError, pack


EXPECTED = sorted(
    [
        'main.tex',
        'sec/intro.tex',
        'figs/plot.pdf',
        'figs/x.pdf',
        'figs/y.png',
        'images/model_v1.2.png',
        'refs.bib',
        'main.bbl',
        'local.sty',
        'helper.sty',
        'latexmkrc',
    ]
)


def run(project: Path, tmp_path: Path, **kwargs) -> Path:
    output = kwargs.pop('output', tmp_path / 'out.zip')
    pack(project / 'main.tex', Options(output=output, **kwargs))
    return output


class TestCollection:
    def test_collects_exactly_what_the_document_references(self, project, tmp_path):
        assert namelist(run(project, tmp_path)) == EXPECTED

    def test_build_artefacts_and_unused_drafts_are_left_out(self, project, tmp_path):
        entries = namelist(run(project, tmp_path))
        for name in JUNK:
            assert name not in entries

    def test_follows_input_into_subdirectories(self, project, tmp_path):
        assert 'sec/intro.tex' in namelist(run(project, tmp_path))

    def test_resolves_figures_through_graphicspath(self, project, tmp_path):
        entries = namelist(run(project, tmp_path))
        assert 'figs/plot.pdf' in entries
        assert 'images/model_v1.2.png' in entries

    def test_keeps_an_existing_extension_instead_of_appending_one(self, project, tmp_path):
        # 'model_v1.2' must not be truncated to 'model_v1.pdf'.
        write(project / 'images' / 'model_v1.pdf', 'wrong')
        assert 'images/model_v1.2.png' in namelist(run(project, tmp_path))

    def test_prefers_the_referenced_extension_over_the_search_order(self, project, tmp_path):
        write(project / 'sec' / 'intro.tex', r'\includegraphics{figs/y.png}')
        write(project / 'figs' / 'y.pdf', 'stale')
        assert 'figs/y.png' in namelist(run(project, tmp_path))

    def test_follows_local_styles_recursively(self, project, tmp_path):
        entries = namelist(run(project, tmp_path))
        assert 'local.sty' in entries
        assert 'helper.sty' in entries

    def test_packages_from_texlive_are_not_reported_missing(self, project, tmp_path):
        packer = Packer(project / 'main.tex', Options(output=tmp_path / 'out.zip'))
        packer.run()
        assert not any('amsmath' in item or 'xcolor' in item for item in packer.missing)

    def test_bbl_is_included(self, project, tmp_path):
        assert 'main.bbl' in namelist(run(project, tmp_path))

    def test_missing_bbl_is_reported(self, project, tmp_path, caplog):
        (project / 'main.bbl').unlink()
        run(project, tmp_path)
        assert 'main.bbl not found' in caplog.text

    def test_macros_shown_verbatim_are_not_treated_as_references(self, project, tmp_path):
        packer = Packer(project / 'main.tex', Options(output=tmp_path / 'out.zip'))
        packer.run()
        assert not any('verbatim_fig' in item for item in packer.missing)

    def test_no_duplicate_entries(self, project, tmp_path):
        write(
            project / 'sec' / 'intro.tex',
            r'\includegraphics{plot}\includegraphics{figs/plot.pdf}',
        )
        entries = namelist(run(project, tmp_path))
        assert len(entries) == len(set(entries))


class TestArchivePaths:
    def test_entries_are_relative_to_the_project_root(self, project, tmp_path):
        for name in namelist(run(project, tmp_path)):
            assert not name.startswith('/')
            assert not name.startswith('..')
            assert ':' not in name
            assert '\\' not in name

    def test_local_directory_layout_does_not_leak(self, project, tmp_path):
        assert not any('Users' in name for name in namelist(run(project, tmp_path)))

    def test_root_can_be_widened(self, project, tmp_path):
        output = tmp_path / 'wide.zip'
        pack(project / 'main.tex', Options(output=output, root=tmp_path))
        entries = namelist(output)
        assert 'paper/main.tex' in entries
        assert 'outside.pdf' in entries


class TestUnresolvedReferences:
    def test_reference_escaping_the_root_is_reported(self, project, tmp_path):
        packer = Packer(project / 'main.tex', Options(output=tmp_path / 'out.zip'))
        packer.run()
        assert any('../outside' in item for item in packer.missing)

    def test_commented_out_figure_is_neither_packed_nor_reported(self, project, tmp_path):
        packer = Packer(project / 'main.tex', Options(output=tmp_path / 'out.zip'))
        packer.run()
        assert not any('ghost' in item for item in packer.missing)

    def test_strict_aborts(self, project, tmp_path):
        with pytest.raises(PackError, match='unresolved'):
            run(project, tmp_path, strict=True)

    def test_strict_succeeds_once_references_resolve(self, project, tmp_path):
        write(project / 'sec' / 'intro.tex', r'\includegraphics{plot}')
        assert 'figs/plot.pdf' in namelist(run(project, tmp_path, strict=True))


class TestExcludeAndInclude:
    def test_exclude_adds_to_the_built_in_exclusions(self, project, tmp_path):
        entries = namelist(run(project, tmp_path, exclude=('refs.bib',)))
        assert 'refs.bib' not in entries
        # The built-in exclusions must survive a user-supplied --exclude.
        assert 'main.pdf' not in entries
        assert not any(name.startswith('.packtex') for name in entries)

    def test_exclude_accepts_directory_globs(self, project, tmp_path):
        entries = namelist(run(project, tmp_path, exclude=('figs/*',)))
        assert not any(name.startswith('figs/') for name in entries)

    def test_include_adds_unreferenced_files(self, project, tmp_path):
        assert 'unused.tex' in namelist(run(project, tmp_path, include=('unused.tex',)))

    def test_include_warns_when_a_pattern_matches_nothing(self, project, tmp_path, caplog):
        run(project, tmp_path, include=('nope/*.tex',))
        assert 'matched no files' in caplog.text

    def test_the_archive_never_packs_itself(self, project, tmp_path):
        output = project / 'sources.zip'
        pack(project / 'main.tex', Options(output=output))
        assert 'sources.zip' not in namelist(output)


class TestOutput:
    def test_creates_the_output_directory(self, project, tmp_path):
        output = tmp_path / 'nested' / 'dir' / 'out.zip'
        pack(project / 'main.tex', Options(output=output))
        assert output.is_file()

    def test_original_sources_are_never_modified(self, project, tmp_path):
        before = {path: path.read_bytes() for path in sorted(project.rglob('*')) if path.is_file()}
        run(project, tmp_path, strip_comments=True)
        after = {path: path.read_bytes() for path in before}
        assert after == before

    def test_scratch_directory_is_cleaned_up(self, project, tmp_path):
        run(project, tmp_path, strip_comments=True)
        assert not (project / '.packtex').exists()

    def test_scratch_directory_can_be_kept(self, project, tmp_path):
        run(project, tmp_path, strip_comments=True, keep_temp=True)
        assert (project / '.packtex' / 'main.tex').is_file()

    def test_strip_comments_removes_private_notes(self, project, tmp_path):
        write(project / 'main.tex', 'a % TODO ask the co-author\n\\input{sec/intro}\n')
        archived = read_entry(run(project, tmp_path, strip_comments=True), 'main.tex')
        assert b'TODO' not in archived
        assert b'a %\n' in archived

    def test_comments_are_kept_by_default(self, project, tmp_path):
        write(project / 'main.tex', 'a % TODO ask the co-author\n\\input{sec/intro}\n')
        archived = read_entry(run(project, tmp_path), 'main.tex')
        assert b'TODO' in archived


class TestErrors:
    def test_missing_main_file(self, project, tmp_path):
        with pytest.raises(PackError, match='not a file'):
            pack(project / 'nope.tex', Options(output=tmp_path / 'out.zip'))

    def test_main_file_outside_the_root(self, project, tmp_path):
        with pytest.raises(PackError, match='outside the project root'):
            pack(project / 'main.tex', Options(output=tmp_path / 'out.zip', root=project / 'figs'))


class TestCompression:
    def test_failed_compression_keeps_the_original(self, project, tmp_path):
        # /bin/false stands in for a Ghostscript run that exits non-zero.
        output = run(project, tmp_path, compress=True, gs='/bin/false')
        assert read_entry(output, 'figs/plot.pdf') == b'plot'

    def test_failed_compression_still_produces_a_complete_archive(self, project, tmp_path):
        assert namelist(run(project, tmp_path, compress=True, gs='/bin/false')) == EXPECTED

    def test_missing_ghostscript_is_reported(self, project, tmp_path, caplog):
        run(project, tmp_path, compress=True, gs='definitely-not-ghostscript')
        assert 'Ghostscript not found' in caplog.text

    def test_parallel_jobs_do_not_collide_on_shared_basenames(self, project, tmp_path):
        write(project / 'figs' / 'a' / 'plot.pdf', 'a')
        write(project / 'figs' / 'b' / 'plot.pdf', 'b')
        write(
            project / 'sec' / 'intro.tex',
            r'\includegraphics{figs/a/plot}\includegraphics{figs/b/plot}',
        )
        output = run(project, tmp_path, compress=True, jobs=4, gs='/bin/false')
        assert read_entry(output, 'figs/a/plot.pdf') == b'a'
        assert read_entry(output, 'figs/b/plot.pdf') == b'b'
