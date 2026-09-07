"""Shared fixtures: a miniature LaTeX project exercising the tricky cases."""

import zipfile
from pathlib import Path

import pytest


MAIN_TEX = r"""\documentclass{article}
\usepackage{local}
\usepackage{amsmath}
\graphicspath{{./figs/}{./images/}}

\begin{document}
\input{sec/intro}
\bibliographystyle{plain}
\bibliography{refs}
\end{document}
"""

INTRO_TEX = r"""\section{Intro}
\includegraphics{plot}
\includegraphics[width=2cm]{model_v1.2}
%\includegraphics{ghost}
\includegraphics[a]{x}\includegraphics[b]{y}
\includegraphics{../outside}
\begin{verbatim}
100% of the time this is not a comment \includegraphics{verbatim_fig}
\end{verbatim}
"""

LOCAL_STY = r"""\ProvidesPackage{local}
\RequirePackage{helper}
\RequirePackage{xcolor}
"""

# Files that must never end up in the archive: build artefacts, an unused
# draft, and a figure that only appears in a comment.
JUNK = ('main.pdf', 'main.aux', 'main.log', 'unused.tex', 'ghost.pdf')


def write(path: Path, content: str = '') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Build the sample project and return its root."""
    root = tmp_path / 'paper'

    write(root / 'main.tex', MAIN_TEX)
    write(root / 'sec' / 'intro.tex', INTRO_TEX)
    write(root / 'local.sty', LOCAL_STY)
    write(root / 'helper.sty', r'\ProvidesPackage{helper}')
    write(root / 'refs.bib', '@misc{a, title={A}}')
    write(root / 'main.bbl', r'\begin{thebibliography}{1}\end{thebibliography}')
    write(root / 'latexmkrc', '$pdf_mode = 1;\n')

    write(root / 'figs' / 'plot.pdf', 'plot')
    write(root / 'figs' / 'x.pdf', 'x')
    write(root / 'figs' / 'y.png', 'y')
    write(root / 'images' / 'model_v1.2.png', 'model')

    for name in JUNK:
        write(root / name, 'junk')

    # Referenced as ../outside from inside the project: reachable on disk but
    # not representable inside the archive.
    write(tmp_path / 'outside.pdf', 'outside')
    return root


def namelist(archive: Path) -> list[str]:
    with zipfile.ZipFile(archive) as zf:
        return sorted(zf.namelist())


def read_entry(archive: Path, name: str) -> bytes:
    with zipfile.ZipFile(archive) as zf:
        assert name in zf.namelist(), f'{name} is missing from {archive}'
        return zf.read(name)
