"""Unit tests for the LaTeX text parsing helpers."""

from packtex.tex import (
    split_list,
    mask_source,
    mask_comments,
    mask_verbatim,
    balanced_group,
    strip_comments,
    iter_macro_args,
    find_graphics_paths,
)


def names(text, macros=('includegraphics',)):
    return [arg.value for arg in iter_macro_args(mask_source(text), macros)]


class TestBalancedGroup:
    def test_nested_groups(self):
        assert balanced_group('{{a}{b}}', 0) == ('{a}{b}', 8)

    def test_reports_offset_past_closing_brace(self):
        assert balanced_group('x{a}y', 1) == ('a', 4)

    def test_escaped_brace_is_not_a_delimiter(self):
        assert balanced_group(r'{a\}b}', 0) == (r'a\}b', 6)

    def test_unterminated_group(self):
        assert balanced_group('{abc', 0) is None

    def test_not_a_group(self):
        assert balanced_group('abc', 0) is None


class TestGraphicsPath:
    def test_standard_nested_form(self):
        assert find_graphics_paths(r'\graphicspath{{./figs/}{./images/}}') == [
            './figs/',
            './images/',
        ]

    def test_single_directory(self):
        assert find_graphics_paths(r'\graphicspath{{figs/}}') == ['figs/']

    def test_whitespace_between_groups(self):
        assert find_graphics_paths('\\graphicspath{ {a/} {b/} }') == ['a/', 'b/']

    def test_absent(self):
        assert find_graphics_paths(r'\documentclass{article}') == []


class TestMacroArgs:
    def test_without_optional_argument(self):
        assert names(r'\includegraphics{fig.pdf}') == ['fig.pdf']

    def test_with_optional_argument(self):
        assert names(r'\includegraphics[width=.5\linewidth]{figs/a.pdf}') == ['figs/a.pdf']

    def test_starred_form(self):
        assert names(r'\includegraphics*[width=1cm]{b.pdf}') == ['b.pdf']

    def test_legacy_two_optional_arguments(self):
        assert names(r'\includegraphics[0,0][10,10]{c.pdf}') == ['c.pdf']

    def test_several_on_one_line(self):
        assert names(r'\includegraphics[a]{x.pdf}\includegraphics[b]{y.pdf}') == [
            'x.pdf',
            'y.pdf',
        ]

    def test_argument_spanning_lines(self):
        assert names('\\includegraphics[\n  width=1cm\n]{\n  d.pdf}') == ['\n  d.pdf']

    def test_name_with_space(self):
        assert names(r'\includegraphics{my figure.pdf}') == ['my figure.pdf']

    def test_include_is_not_confused_with_includegraphics(self):
        text = r'\include{chapter}\includegraphics{fig.pdf}'
        assert names(text, ('input', 'include')) == ['chapter']
        assert names(text, ('includegraphics',)) == ['fig.pdf']

    def test_commented_out_macro_is_ignored(self):
        assert names('%\\includegraphics{ghost.pdf}\n\\includegraphics{real.pdf}') == ['real.pdf']

    def test_trailing_comment_on_a_real_line(self):
        assert names(r'\includegraphics{real.pdf} % \includegraphics{ghost.pdf}') == ['real.pdf']


class TestComments:
    def test_masking_preserves_length_and_offsets(self):
        text = 'a % note\nb\n'
        masked = mask_comments(text)
        assert len(masked) == len(text)
        assert masked == 'a %     \nb\n'

    def test_escaped_percent_is_not_a_comment(self):
        text = r'50\% done % note'
        assert mask_comments(text) == r'50\% done %     '

    def test_percent_after_a_line_break_macro_starts_a_comment(self):
        assert mask_comments(r'x \\% note') == r'x \\%     '

    def test_verbatim_body_is_left_alone(self):
        text = '\\begin{verbatim}\n100% kept\n\\end{verbatim}\n% dropped\n'
        masked = mask_comments(text)
        assert '100% kept' in masked
        assert 'dropped' not in masked

    def test_stripping_keeps_the_percent(self):
        assert strip_comments('a % note\nb\n') == 'a %\nb\n'

    def test_stripping_is_a_noop_without_comments(self):
        assert strip_comments('a\nb\n') == 'a\nb\n'


class TestVerbatim:
    def test_body_is_blanked_but_offsets_survive(self):
        text = '\\begin{verbatim}\n\\includegraphics{shown}\n\\end{verbatim}\n'
        masked = mask_verbatim(text)
        assert len(masked) == len(text)
        assert 'includegraphics' not in masked
        assert masked.count('\n') == text.count('\n')

    def test_macro_inside_verbatim_is_not_a_reference(self):
        assert names('\\begin{lstlisting}\n\\includegraphics{shown}\n\\end{lstlisting}\n') == []

    def test_macro_after_verbatim_is_a_reference(self):
        text = '\\begin{verbatim}\nx\n\\end{verbatim}\n\\includegraphics{real.pdf}\n'
        assert names(text) == ['real.pdf']

    def test_commented_out_begin_does_not_swallow_the_document(self):
        text = '%\\begin{verbatim}\n\\includegraphics{real.pdf}\n'
        assert names(text) == ['real.pdf']

    def test_unterminated_verbatim_blanks_the_remainder(self):
        assert names('\\begin{verbatim}\n\\includegraphics{shown}\n') == []


class TestSplitList:
    def test_splits_and_trims(self):
        assert split_list('a, b ,c') == ['a', 'b', 'c']

    def test_drops_empty_entries(self):
        assert split_list('a,,b,') == ['a', 'b']
