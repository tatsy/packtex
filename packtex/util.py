"""
Shared helpers
"""


def human_size(size: int) -> str:
    """Format a byte count for log messages."""
    value = float(size)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            precision = 0 if unit == 'B' else 1
            return f'{value:.{precision}f} {unit}'
        value /= 1024

    raise AssertionError('unreachable')
