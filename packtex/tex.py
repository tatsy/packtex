"""
Pure-text parsing helpers for LaTeX sources.

Nothing here touches the filesystem: every function takes source text and
returns plain data, which keeps the fiddly brace and comment handling unit
testable.  Callers are expected to run text through :func:`mask_comments`
before scanning for macros so that commented-out code is ignored.
"""

import re
from typing import Optional, NamedTuple
from collections.abc import Iterable, Iterator


# Environments whose bodies are typeset verbatim: a '%' inside them is
# literal text rather than the start of a comment.
VERBATIM_ENVS = frozenset(
    {
        'verbatim',
        'Verbatim',
        'BVerbatim',
        'LVerbatim',
        'lstlisting',
        'minted',
        'alltt',
        'comment',
    }
)

_BEGIN_END = re.compile(r'\\(begin|end)\s*\{([^}]*)\}')


class MacroArg(NamedTuple):
    """The mandatory argument of one macro occurrence."""

    macro: str
    value: str
    start: int
    end: int


def _first_comment(line: str) -> Optional[int]:
    """Return the index of the first unescaped '%' in *line*."""
    index = 0
    while index < len(line):
        char = line[index]
        if char == '\\':
            # Skip the escaped character, so '\%' is literal while the '%'
            # in '\\%' still starts a comment.
            index += 2
            continue
        if char == '%':
            return index
        index += 1
    return None


def _opens_verbatim(line: str) -> Optional[str]:
    """Return the verbatim environment left open by *line*, if any."""
    active = None
    for match in _BEGIN_END.finditer(line):
        name = match[2].strip()
        if name in VERBATIM_ENVS:
            active = name if match[1] == 'begin' else None
    return active


def _closes_env(line: str, name: str) -> bool:
    return re.search(r'\\end\s*\{\s*' + re.escape(name) + r'\s*\}', line) is not None


def _comment_spans(text: str) -> Iterator[tuple[int, int]]:
    """Yield (start, end) spans covering the body of every comment.

    A span starts just after the '%' and stops before the line ending, so the
    '%' itself - which is significant to TeX at the end of a line - always
    survives.  Verbatim environments are skipped.
    """
    offset = 0
    verbatim: Optional[str] = None
    for line in text.splitlines(keepends=True):
        content = line.rstrip('\r\n')
        if verbatim is not None:
            if _closes_env(content, verbatim):
                verbatim = None
            offset += len(line)
            continue

        index = _first_comment(content)
        if index is not None:
            yield offset + index + 1, offset + len(content)
            content = content[:index]
        verbatim = _opens_verbatim(content)
        offset += len(line)


def mask_comments(text: str) -> str:
    """Blank out comment bodies while preserving the length of *text*.

    Every character after an unescaped '%' is replaced with a space, so
    offsets into the result are also valid offsets into the original text.
    """
    pieces = []
    cursor = 0
    for start, end in _comment_spans(text):
        pieces.append(text[cursor:start])
        pieces.append(' ' * (end - start))
        cursor = end
    pieces.append(text[cursor:])
    return ''.join(pieces)


def _verbatim_spans(text: str) -> Iterator[tuple[int, int]]:
    """Yield (start, end) spans covering the body of verbatim environments."""
    offset = 0
    active: Optional[str] = None
    start = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip('\r\n')
        if active is None:
            active = _opens_verbatim(content)
            if active is not None:
                start = offset + len(line)
        elif _closes_env(content, active):
            yield start, offset
            active = None
        offset += len(line)

    if active is not None:
        yield start, offset


def mask_verbatim(text: str) -> str:
    """Blank out verbatim bodies while preserving the length of *text*.

    Macros shown inside ``verbatim`` or ``lstlisting`` are displayed, not
    executed, so they must not be mistaken for real references.  Line breaks
    are kept so the result still lines up with the original.
    """
    pieces = []
    cursor = 0
    for start, end in _verbatim_spans(text):
        pieces.append(text[cursor:start])
        pieces.append(''.join(char if char in '\r\n' else ' ' for char in text[start:end]))
        cursor = end
    pieces.append(text[cursor:])
    return ''.join(pieces)


def mask_source(text: str) -> str:
    """Blank out everything TeX will not execute, preserving offsets.

    Comments go first so that a commented-out ``\\begin{verbatim}`` cannot
    swallow the rest of the file.
    """
    return mask_verbatim(mask_comments(text))


def strip_comments(text: str) -> str:
    """Delete comment bodies, keeping the '%' itself.

    Useful before submission: private notes left in comments are shipped
    verbatim otherwise, but removing the '%' too would change how TeX treats
    the following line break.
    """
    pieces = []
    cursor = 0
    for start, end in _comment_spans(text):
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return ''.join(pieces)


def balanced_group(text: str, index: int) -> Optional[tuple[str, int]]:
    """Return (inner, end) for the brace group starting at *index*.

    *end* is the offset just past the closing brace.  Nested groups are
    tracked, which a regular expression cannot do - and which
    ``\\graphicspath{{a/}{b/}}`` requires.  Returns None when *index* is not
    an opening brace or the group is unterminated.
    """
    if index >= len(text) or text[index] != '{':
        return None

    depth = 0
    cursor = index
    while cursor < len(text):
        char = text[cursor]
        if char == '\\':
            cursor += 2
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return text[index + 1 : cursor], cursor + 1
        cursor += 1
    return None


def iter_macro_args(text: str, macros: Iterable[str]) -> Iterator[MacroArg]:
    """Yield the mandatory argument of every ``\\macro[...]{...}`` in *text*.

    A trailing star and any number of optional arguments are tolerated, so
    both ``\\includegraphics{f}`` and the legacy
    ``\\includegraphics*[llx,lly][urx,ury]{f}`` are recognised.
    """
    names = sorted(macros, key=lambda name: (-len(name), name))
    if not names:
        return
    pattern = re.compile(r'\\(' + '|'.join(re.escape(name) for name in names) + r')\b\*?')

    for match in pattern.finditer(text):
        cursor = match.end()
        while cursor < len(text):
            if text[cursor] in ' \t\r\n':
                cursor += 1
            elif text[cursor] == '[':
                close = text.find(']', cursor)
                if close < 0:
                    break
                cursor = close + 1
            else:
                break

        group = balanced_group(text, cursor)
        if group is None:
            continue
        value = group[0]
        yield MacroArg(match[1], value, cursor + 1, cursor + 1 + len(value))


def find_graphics_paths(text: str) -> list[str]:
    """Return the directories declared by ``\\graphicspath``."""
    paths = []
    for arg in iter_macro_args(text, ('graphicspath',)):
        cursor = 0
        while cursor < len(arg.value):
            if arg.value[cursor] != '{':
                cursor += 1
                continue
            group = balanced_group(arg.value, cursor)
            if group is None:
                break
            inner, cursor = group
            inner = inner.strip()
            if inner:
                paths.append(inner)
    return paths


def split_list(value: str) -> list[str]:
    """Split a comma-separated macro argument such as ``\\usepackage{a,b}``."""
    return [item.strip() for item in value.split(',') if item.strip()]
