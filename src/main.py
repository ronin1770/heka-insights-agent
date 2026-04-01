"""
file: main.py
description: Main entry point for the software
author: Farhan Munir (ronin1770)
dev_started_on: 2026-04-01
epic_or_related_story: EPIC ID: #2
"""

from logger.config import get_logger

logger = get_logger(__name__)


def main() -> None:
    logger.info("Application startup complete")
    logger.error("Crashed")
    logger.debug("debugging is on")


if __name__ == "__main__":
    main()
