"""
PDF re-compression through Ghostscript.
"""

import shutil
import logging
import subprocess
from typing import Optional
from pathlib import Path

from .util import human_size


logger = logging.getLogger(__name__)

# 'rungs' is the wrapper shipped with MacTeX; the rest are the usual
# Ghostscript executable names on Linux and Windows.
GS_CANDIDATES = ('rungs', 'gs', 'gswin64c', 'gswin32c')


def find_ghostscript(command: Optional[str] = None) -> Optional[str]:
    """Return the Ghostscript executable to use, or None when unavailable."""
    for name in (command,) if command else GS_CANDIDATES:
        found = shutil.which(name)
        if found is not None:
            return found
    return None


def _build_command(src: Path, dest: Path, dpi: int, gs: str) -> list[str]:
    # Parameters are spelled out rather than relying on -dPDFSETTINGS: the
    # presets bundle their own resolutions, which silently fight with --dpi.
    return [
        gs,
        '-sDEVICE=pdfwrite',
        '-dCompatibilityLevel=1.4',
        '-dEmbedAllFonts=true',
        '-dSubsetFonts=true',
        '-dAutoRotatePages=/None',
        '-dDetectDuplicateImages=true',
        '-dDownsampleColorImages=true',
        '-dColorImageDownsampleType=/Bicubic',
        f'-dColorImageResolution={dpi}',
        '-dDownsampleGrayImages=true',
        '-dGrayImageDownsampleType=/Bicubic',
        f'-dGrayImageResolution={dpi}',
        '-dDownsampleMonoImages=true',
        '-dMonoImageDownsampleType=/Subsample',
        f'-dMonoImageResolution={dpi}',
        '-dNOPAUSE',
        '-dBATCH',
        '-dSAFER',
        f'-sOutputFile={dest}',
        str(src),
    ]


def compress_pdf(src: Path, dest: Path, dpi: int, gs: str) -> bool:
    """Re-compress *src* into *dest*, returning True when *dest* is usable.

    Ghostscript exits non-zero on malformed input and happily produces output
    larger than its input for vector figures, so the result is only accepted
    when the run succeeded and actually saved space.  Output is captured
    rather than streamed so that parallel jobs do not interleave.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        _build_command(src, dest, dpi, gs),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )

    if proc.returncode != 0:
        logger.warning(
            'Ghostscript failed on %s (exit %d); keeping the original', src, proc.returncode
        )
        logger.debug('Ghostscript output for %s:\n%s', src, (proc.stdout or '').strip())
        return False

    if not dest.is_file() or dest.stat().st_size == 0:
        logger.warning('Ghostscript produced no output for %s; keeping the original', src)
        return False

    before = src.stat().st_size
    after = dest.stat().st_size
    if after >= before:
        logger.info(
            'No gain for %s (%s -> %s); keeping the original',
            src,
            human_size(before),
            human_size(after),
        )
        return False

    logger.info('Compressed %s (%s -> %s)', src, human_size(before), human_size(after))
    return True
