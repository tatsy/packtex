import shutil
import fnmatch
import logging
import zipfile
import contextlib
import dataclasses
from typing import Optional, NamedTuple
from pathlib import Path
from collections.abc import Iterable, Iterator

from joblib import Parallel, delayed

from .pdf import compress_pdf, find_ghostscript
from .tex import (
    split_list,
    mask_source,
    strip_comments,
    iter_macro_args,
    find_graphics_paths,
)
from .util import human_size


logger = logging.getLogger(__name__)

TEMP_DIR_NAME = '.packtex'

# Search order mirrors \DeclareGraphicsExtensions for pdflatex, with the
# formats arXiv also accepts appended.
IMAGE_EXTS = ('.pdf', '.png', '.jpg', '.jpeg', '.eps', '.ps')

INPUT_MACROS = ('input', 'include', 'subfile')
BIB_MACROS = ('bibliography', 'addbibresource')
STYLE_MACROS = {
    'usepackage': '.sty',
    'RequirePackage': '.sty',
    'RequirePackageWithOptions': '.sty',
    'documentclass': '.cls',
    'LoadClass': '.cls',
    'LoadClassWithOptions': '.cls',
}

# Files that are useful for rebuilding the archive locally but are not
# referenced from the document itself.
BUILD_FILES = ('latexmkrc', '.latexmkrc')


class PackError(Exception):
    """A problem that should stop the run with a readable message."""


class Source(NamedTuple):
    """A file to archive, together with the path it gets inside the ZIP."""

    path: Path
    arcname: str


@dataclasses.dataclass
class Options:
    """Everything the CLI can tune."""

    output: str = 'sources.zip'
    root: Optional[Path] = None
    compress: bool = False
    dpi: int = 400
    jobs: int = 1
    gs: Optional[str] = None
    exclude: tuple[str, ...] = ()
    include: tuple[str, ...] = ()
    strip_comments: bool = False
    keep_temp: bool = False
    strict: bool = False


class Packer:
    """
    Resolves what a document needs and writes it to a ZIP archive.
    """

    def __init__(self, main: str, options: Options):
        self.options = options

        absolute_main = Path(main).expanduser().resolve()
        if not absolute_main.is_file():
            raise PackError(f'{main} is not a file')

        root = options.root.expanduser().resolve() if options.root else absolute_main.parent
        if not root.is_dir():
            raise PackError(f'{root} is not a directory')
        self.root = root

        try:
            self.main = absolute_main.relative_to(self.root)
        except ValueError:
            raise PackError(
                f'{main} is outside the project root {self.root}; pass --root to widen the scope'
            ) from None

        self.temp = self.root / TEMP_DIR_NAME
        self.output = Path(options.output).expanduser()
        self.missing: list[str] = []

        self._texts: dict[Path, str] = {}
        self._masked: dict[Path, str] = {}
        self._encodings: dict[Path, str] = {}

        patterns = [TEMP_DIR_NAME, f'{TEMP_DIR_NAME}/*']
        with contextlib.suppress(ValueError):
            patterns.append(self.output.resolve().relative_to(self.root).as_posix())
        self._exclude = tuple(patterns) + tuple(options.exclude)

    def _read(self, rel: Path) -> str:
        """Read a source file, remembering the encoding it decoded with."""
        if rel in self._texts:
            return self._texts[rel]

        data = (self.root / rel).read_bytes()
        text = ''
        for encoding in ('utf-8', 'latin-1'):
            try:
                text = data.decode(encoding)
            except UnicodeDecodeError:
                continue
            self._encodings[rel] = encoding
            break

        self._texts[rel] = text
        self._masked[rel] = mask_source(text)
        return text

    def _masked_text(self, rel: Path) -> str:
        self._read(rel)
        return self._masked[rel]

    def _normalize(self, candidate: Path) -> Optional[Path]:
        """Return *candidate* as a root-relative path, or None if it escapes.

        Collapsing '..' here is what keeps a reference such as
        ``../other-paper/fig.pdf`` from turning into an archive entry that
        climbs out of the extraction directory.
        """
        absolute = (self.root / candidate).resolve()
        try:
            return absolute.relative_to(self.root)
        except ValueError:
            return None

    def _resolve(self, name: str, dirs: Iterable[Path], exts: tuple[str, ...]) -> Optional[Path]:
        """Find the file a LaTeX reference points at, relative to the root.

        LaTeX walks the search directories in order and, within each, tries the
        known extensions.  The reference may already carry one, in which case it
        is used as-is - appending blindly would turn 'fig.png' into 'fig.pdf'
        and 'model_v1.2' into 'model_v1.pdf'.
        """
        name = name.strip()
        if not name:
            return None

        candidates = []
        if Path(name).suffix.lower() in exts:
            candidates.append(name)
        candidates.extend(name + ext for ext in exts)

        for directory in dirs:
            for candidate in candidates:
                found = self._normalize(directory / candidate)
                if found is not None and (self.root / found).is_file():
                    return found
        return None

    def _miss(self, source: Path, macro: str, name: str) -> None:
        self.missing.append(f'{source}: \\{macro}{{{name}}}')

    def _excluded(self, rel: Path) -> bool:
        posix = rel.as_posix()
        return any(
            fnmatch.fnmatch(posix, pattern) or fnmatch.fnmatch(rel.name, pattern)
            for pattern in self._exclude
        )

    def _add(self, sources: dict[str, Source], rel: Path) -> None:
        arcname = rel.as_posix()
        if arcname in sources:
            return
        if self._excluded(rel):
            logger.debug('Excluding %s', arcname)
            return
        sources[arcname] = Source(self.root / rel, arcname)

    # -- collection --------------------------------------------------------

    def _walk_inputs(self) -> list[Path]:
        """Return every .tex file reachable from the main file, in visit order."""
        order: list[Path] = []
        queue = [self.main]
        seen = set()

        while queue:
            rel = queue.pop(0)
            if rel in seen:
                continue
            seen.add(rel)
            order.append(rel)

            masked = self._masked_text(rel)
            # \input resolves against the compilation directory; the including
            # file's own directory is a fallback for subfiles-style projects.
            dirs = [Path('.'), rel.parent]
            for arg in iter_macro_args(masked, INPUT_MACROS):
                child = self._resolve(arg.value, dirs, ('.tex',))
                if child is None:
                    self._miss(rel, arg.macro, arg.value)
                elif child not in seen:
                    queue.append(child)

        return order

    def _graphics_dirs(self, tex_files: Iterable[Path]) -> list[Path]:
        """Return the figure search path declared by the document."""
        dirs: list[Path] = []
        for rel in tex_files:
            for raw in find_graphics_paths(self._masked_text(rel)):
                normalized = self._normalize(Path(raw))
                if normalized is None:
                    logger.warning(
                        '\\graphicspath entry %s is outside the project root; ignoring', raw
                    )
                elif normalized not in dirs:
                    dirs.append(normalized)

        # The compilation directory is always searched, after the declared ones.
        if Path('.') not in dirs:
            dirs.append(Path('.'))
        return dirs

    def _collect_figures(self, tex_files: Iterable[Path]) -> Iterator[Path]:
        tex_files = list(tex_files)
        dirs = self._graphics_dirs(tex_files)
        logger.debug('Figure search path: %s', [str(d) for d in dirs])

        for rel in tex_files:
            for arg in iter_macro_args(self._masked_text(rel), ('includegraphics',)):
                target = self._resolve(arg.value, dirs, IMAGE_EXTS)
                if target is None:
                    self._miss(rel, arg.macro, arg.value)
                else:
                    yield target

    def _collect_support(self, tex_files: Iterable[Path]) -> Iterator[Path]:
        """Yield local classes, styles and bibliography files.

        Only files that exist in the project are yielded: ``\\usepackage{amsmath}``
        resolves to nothing here, which is correct because TeX Live provides it.
        """
        queue = list(tex_files)
        scanned: set[Path] = set()
        cited_bibliography = False

        while queue:
            rel = queue.pop(0)
            if rel in scanned:
                continue
            scanned.add(rel)
            masked = self._masked_text(rel)

            for arg in iter_macro_args(masked, STYLE_MACROS):
                ext = STYLE_MACROS[arg.macro]
                for name in split_list(arg.value):
                    local = self._resolve(name, [Path('.'), rel.parent], (ext,))
                    if local is not None:
                        # A local style may pull in further local styles.
                        queue.append(local)
                        yield local

            for arg in iter_macro_args(masked, BIB_MACROS):
                cited_bibliography = True
                for name in split_list(arg.value):
                    local = self._resolve(name, [Path('.'), rel.parent], ('.bib',))
                    if local is None:
                        self._miss(rel, arg.macro, name)
                    else:
                        yield local

            for arg in iter_macro_args(masked, ('bibliographystyle',)):
                local = self._resolve(arg.value, [Path('.'), rel.parent], ('.bst',))
                if local is not None:
                    yield local

        # arXiv does not run BibTeX, so the .bbl has to travel with the sources.
        bbl = self.main.with_suffix('.bbl')
        if (self.root / bbl).is_file():
            yield bbl
        elif cited_bibliography:
            logger.warning(
                '%s not found - arXiv does not run BibTeX, so references will be missing. '
                'Compile locally first to generate it.',
                bbl,
            )

        for name in BUILD_FILES:
            if (self.root / name).is_file():
                yield Path(name)

    def _collect_include_patterns(self) -> Iterator[Path]:
        for pattern in self.options.include:
            matched = False
            for path in sorted(self.root.glob(pattern)):
                if path.is_file():
                    normalized = self._normalize(path)
                    if normalized is not None:
                        matched = True
                        yield normalized
            if not matched:
                logger.warning('--include pattern %r matched no files', pattern)

    # -- output ------------------------------------------------------------

    def _compress_pdfs(self, sources: list[Source]) -> list[Source]:
        gs = find_ghostscript(self.options.gs)
        if gs is None:
            logger.warning(
                'Ghostscript not found (looked for %s); skipping compression',
                ', '.join(('rungs', 'gs', 'gswin64c', 'gswin32c')),
            )
            return sources

        targets = [source for source in sources if source.path.suffix.lower() == '.pdf']
        if not targets:
            return sources

        logger.info('Compressing %d PDF(s) at %d dpi using %s', len(targets), self.options.dpi, gs)
        results = Parallel(n_jobs=self.options.jobs, prefer='threads')(
            delayed(compress_pdf)(source.path, self.temp / source.arcname, self.options.dpi, gs)
            for source in targets
        )

        replaced = {
            source.arcname: self.temp / source.arcname
            for source, accepted in zip(targets, results)
            if accepted
        }
        return [
            Source(replaced.get(source.arcname, source.path), source.arcname) for source in sources
        ]

    def _strip_tex_comments(self, sources: list[Source]) -> list[Source]:
        result = []
        for source in sources:
            rel = Path(source.arcname)
            if source.path.suffix.lower() != '.tex' or rel not in self._texts:
                result.append(source)
                continue

            target = self.temp / source.arcname
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                strip_comments(self._texts[rel]),
                encoding=self._encodings.get(rel, 'utf-8'),
            )
            result.append(Source(target, source.arcname))
        return result

    def _write_archive(self, sources: list[Source]) -> None:
        parent = self.output.parent
        if str(parent) not in ('', '.'):
            parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(self.output, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
            for source in sources:
                logger.info('Adding %s', source.arcname)
                archive.write(source.path, arcname=source.arcname)

    def run(self) -> list[Source]:
        logger.info('Packing %s (root: %s) into %s', self.main, self.root, self.output)

        collected: dict[str, Source] = {}
        tex_files = self._walk_inputs()
        for rel in tex_files:
            self._add(collected, rel)
        for rel in self._collect_figures(tex_files):
            self._add(collected, rel)
        for rel in self._collect_support(tex_files):
            self._add(collected, rel)
        for rel in self._collect_include_patterns():
            self._add(collected, rel)

        if self.missing:
            logger.warning('%d unresolved reference(s):', len(self.missing))
            for item in self.missing:
                logger.warning('  %s', item)
            if self.options.strict:
                raise PackError('unresolved references; aborting because --strict was given')

        sources = [collected[key] for key in sorted(collected)]
        if not sources:
            raise PackError('nothing to pack')

        created_temp = not self.temp.exists()
        try:
            if self.options.compress:
                sources = self._compress_pdfs(sources)
            if self.options.strip_comments:
                sources = self._strip_tex_comments(sources)
            self._write_archive(sources)
        finally:
            if self.temp.exists() and not self.options.keep_temp and created_temp:
                shutil.rmtree(self.temp, ignore_errors=True)

        total = self.output.stat().st_size
        logger.info('Packed %d files into %s (%s)', len(sources), self.output, human_size(total))
        return sources


def pack(main: Path, options: Options) -> list[Source]:
    """Convenience wrapper around :class:`Packer`."""
    return Packer(main, options).run()
