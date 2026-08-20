import re
import glob
import logging
import zipfile
import argparse
import subprocess
from pathlib import Path

import coloredlogs
from joblib import Parallel, delayed


TEMP_DIR = Path('./.packtex')
IMG_EXTS = ['.pdf', '.jpg', '.png']
FILE_EXTS = ['.tex', '.bst', '.pdf', '.jpg', '.png', '.cls', '.sty', '.bib', 'latexmkrc']
EXCLUDE = ['main.pdf', TEMP_DIR.name]

logging.basicConfig(format='[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def compress_pdf(input_path: Path, dpi: int = 400) -> Path:
    TEMP_DIR.mkdir(exist_ok=True, parents=True)

    out_path = TEMP_DIR / input_path.name
    cmd = [
        'rungs',
        '-sDEVICE=pdfwrite',
        '-dCompatibilityLevel=1.4',
        '-dPDFSETTINGS=/ebook',
        '-dEmbedAllFonts=true',
        '-dSubsetFonts=true',
        '-dAutoRotatePages=/None',
        '-dColorImageDownsampleType=/Bicubic',
        f'-dColorImageResolution={dpi}',
        '-dGrayImageDownsampleType=/Bicubic',
        f'-dGrayImageResolution={dpi}',
        '-dMonoImageDownsampleType=/Bicubic',
        f'-dMonoImageResolution={dpi}',
        '-dNOPAUSE',
        '-dQUIET',
        '-dBATCH',
        f'-sOutputFile={out_path}',
        str(input_path),
    ]

    logger.info(f'Compressing {input_path} to {out_path}')
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
    ) as proc:
        assert proc.stdout is not None, 'Failed to start subprocess'
        for line in proc.stdout:
            print(line, end='', flush=True)

    return out_path


def main(args: argparse.Namespace):
    logger.info(f'Packing {args.file} into {args.output}')
    with open(args.file, encoding='utf-8') as f:
        content = f.readlines()

    # Get graphics paths
    paths = [Path('.')]
    pat = re.compile(r'\\graphicspath\{(\S+?)\}')
    for line in content:
        match = pat.search(line)
        if match:
            p2 = re.compile(r'\{(\S+?)\}')
            for m in p2.finditer(match[1]):
                paths.append(Path(m[1]))

    # Extract figures
    names = []
    pat = re.compile(r'\\includegraphics\[(.+?)\]\{(\S+?)\}')
    new_lines = []
    for line in content:
        match = pat.search(line)
        if match:
            names.append(match[2])
            name = Path(match[2]).name
            line = line.replace(match[2], name)

        new_lines.append(line)

    new_main = TEMP_DIR / args.file
    TEMP_DIR.mkdir(exist_ok=True, parents=True)
    with open(new_main, mode='w', encoding='utf-8') as f:
        f.writelines(new_lines)

    files: list[Path] = [new_main]
    image_files: list[Path] = []
    for path in paths:
        for name in names:
            for ext in IMG_EXTS:
                filename = path / (Path(name).with_suffix(ext))
                if filename.exists():
                    image_files.append(filename)
                    break

    if args.compress:
        pdf_files = [p for p in image_files if p.suffix == '.pdf']
        compressed_files = Parallel(n_jobs=args.jobs, prefer='threads')(
            delayed(compress_pdf)(p, dpi=args.dpi) for p in pdf_files
        )
        source_to_compress = dict(zip(pdf_files, compressed_files))
        image_files = [source_to_compress.get(p, p) for p in image_files]

    for filename in image_files:
        if filename.name not in EXCLUDE:
            files.append(filename)

    # Correct files to exclude
    exclude_files: list[Path] = []
    for pattern in args.exclude:
        for filename in glob.glob(pattern):
            exclude_files.append(Path(filename).resolve())

    # Extract other files
    for f in Path('.').iterdir():
        if f.name == args.file:
            continue

        for ext in FILE_EXTS:
            if f.name.endswith(ext) and f.resolve() not in exclude_files:
                files.append(f.resolve())

    # Create a zip file
    files = sorted(list(set(files)))
    with zipfile.ZipFile(
        args.output,
        mode='w',
        compression=zipfile.ZIP_DEFLATED,
    ) as zf:
        for f in files:
            file_path = Path(f)
            arcname = file_path.name if TEMP_DIR in file_path.parents else str(file_path)
            logger.info(f'Adding {arcname} to archive')
            zf.write(str(f), arcname=arcname)

    logger.info(f'Packed {len(files)} files into {args.output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pack a LaTeX project into a ZIP archive.')
    parser.add_argument('file', metavar='FILE', type=str)
    parser.add_argument('--compress', action='store_true')
    parser.add_argument('--dpi', type=int, default=400)
    parser.add_argument('-o', '--output', type=str, default='sources.zip')
    parser.add_argument('-j', '--jobs', type=int, default=1)
    parser.add_argument('--exclude', nargs='+', default=EXCLUDE)
    args = parser.parse_args()

    coloredlogs.install(
        level='INFO',
        logger=logger,
        fmt='[%(asctime)s] %(levelname)s: %(message)s',
    )

    main(args)
