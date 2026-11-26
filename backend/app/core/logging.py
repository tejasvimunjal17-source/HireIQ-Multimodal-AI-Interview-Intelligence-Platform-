"""Logging setup.

PRIVACY RULE: never log candidate transcripts, names, emails or audio content.
Log identifiers and error class names only.
"""

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
