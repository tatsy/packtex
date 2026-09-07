"""Entry point for ``python -m packtex``.

The installed ``packtex`` console script calls :func:`packtex.cli.main`
directly; this module makes the same entry point reachable without relying on
the script directory being on PATH.
"""

import sys

from .cli import main


if __name__ == '__main__':
    sys.exit(main())
