"""Command line entry point."""

import sys
import logging
import argparse
from typing import Optional
from pathlib import Path
from collections.abc import Sequence

import coloredlogs

from . import __version__
from .pack import Packer, Options, PackError


LOG_FORMAT = '[%(asctime)s] %(levelname)s: %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

logger = logging.getLogger('packtex')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='packtex',
        description='Pack the LaTeX sources and figures a document needs into a ZIP archive.',
    )
    parser.add_argument('file', metavar='FILE', type=Path, help='main .tex file')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument(
        '-o',
        '--output',
        type=Path,
        default=Path('sources.zip'),
        help='archive to write (default: %(default)s)',
    )
    parser.add_argument(
        '--root',
        type=Path,
        default=None,
        help='project root; archive paths are relative to it (default: the main file directory)',
    )
    parser.add_argument(
        '--exclude',
        nargs='+',
        action='extend',
        default=[],
        metavar='PATTERN',
        help='glob patterns to leave out, in addition to the built-in exclusions',
    )
    parser.add_argument(
        '--include',
        nargs='+',
        action='extend',
        default=[],
        metavar='PATTERN',
        help='glob patterns to add for files the document does not reference directly',
    )
    parser.add_argument(
        '--strip-comments',
        action='store_true',
        help='remove comment text from .tex files so private notes are not published',
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='fail instead of warning when a reference cannot be resolved',
    )
    parser.add_argument('--compress', action='store_true', help='re-compress PDF figures')
    parser.add_argument(
        '--dpi',
        type=int,
        default=400,
        help='image resolution for --compress (default: %(default)s)',
    )
    parser.add_argument('--gs', default=None, help='Ghostscript executable to use')
    parser.add_argument(
        '-j',
        '--jobs',
        type=int,
        default=1,
        help='parallel compression jobs (default: %(default)s)',
    )
    parser.add_argument(
        '--keep-temp', action='store_true', help='keep the .packtex scratch directory'
    )
    parser.add_argument('-v', '--verbose', action='store_true', help='log debug information')
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    coloredlogs.install(
        level='DEBUG' if args.verbose else 'INFO',
        logger=logger,
        fmt=LOG_FORMAT,
        datefmt=DATE_FORMAT,
    )

    options = Options(
        output=args.output,
        root=args.root,
        compress=args.compress,
        dpi=args.dpi,
        jobs=args.jobs,
        gs=args.gs,
        exclude=tuple(args.exclude),
        include=tuple(args.include),
        strip_comments=args.strip_comments,
        keep_temp=args.keep_temp,
        strict=args.strict,
    )

    try:
        Packer(args.file, options).run()
    except PackError as error:
        logger.error('%s', error)
        return 1
    except OSError as error:
        logger.error('%s', error)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
