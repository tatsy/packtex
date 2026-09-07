# packtex

Pack the LaTeX sources and figures a document actually needs into a ZIP archive
ready for arXiv or a journal submission system.

`packtex` starts from your main `.tex` file and follows what the document really
references — `\input`, `\include`, `\includegraphics`, `\usepackage`,
`\bibliography` — instead of sweeping the directory by extension. Build
artefacts, unused drafts and commented-out figures stay out of the archive, and
every file keeps its path relative to the project root so the extracted tree
compiles exactly like the original.

## Install

```sh
uv sync          # development
uv tool install .  # or: pip install .
```

## Usage

```sh
packtex main.tex -o sources.zip
```

Common options:

| Option | Effect |
| --- | --- |
| `-o, --output PATH` | Archive to write (default `sources.zip`) |
| `--root DIR` | Project root; archive paths are relative to it (default: the main file's directory) |
| `--strict` | Fail instead of warning when a reference cannot be resolved |
| `--strip-comments` | Remove comment text from `.tex` files so private notes are not published |
| `--exclude PATTERN…` | Glob patterns to leave out, *in addition to* the built-in exclusions |
| `--include PATTERN…` | Glob patterns to add for files the document does not reference directly |
| `--compress` | Re-compress PDF figures with Ghostscript |
| `--dpi N` | Image resolution for `--compress` (default 400) |
| `-j, --jobs N` | Parallel compression jobs |
| `--gs PATH` | Ghostscript executable (autodetects `rungs`, `gs`, `gswin64c`, `gswin32c`) |
| `--keep-temp` | Keep the `.packtex` scratch directory |
| `-v, --verbose` | Log debug information, including the figure search path |

## Notes for arXiv

- **Compile locally first.** arXiv does not run BibTeX, so the `.bbl` file has
  to travel with the sources. `packtex` includes `<main>.bbl` when it exists and
  warns when the document cites a bibliography but the `.bbl` is missing.
- **Check the warnings.** Unresolved references are listed at the end of the
  run; each one is a figure or input that will be missing from the submission.
  Use `--strict` in a script to turn them into a failure.
- **`--strip-comments` before submitting.** Comments are shipped verbatim
  otherwise, and reviewer notes left in the source are a well-known leak. The
  `%` itself is kept so line breaks keep their meaning, and `verbatim` /
  `lstlisting` bodies are left untouched.
- **References outside the project root** cannot be represented inside the
  archive and are reported rather than silently dropped. Pass `--root` to widen
  the scope when figures live in a shared parent directory.

## Development

```sh
uv sync
uv run pre-commit install  # once, to enable the ruff hooks
```

```sh
uv run pytest        # tests
uv run ruff check .  # lint
uv run ruff format . # format
uv run ty check      # type check
```

`ruff check` and `ruff format` also run automatically on staged files via
[.pre-commit-config.yaml](.pre-commit-config.yaml). Both read their settings
from `pyproject.toml`, so the hooks and the commands above behave identically.
Run `uv run pre-commit run --all-files` to check the whole tree.

## License

MIT License 2026 (c) Tatsuya Yatagawa
