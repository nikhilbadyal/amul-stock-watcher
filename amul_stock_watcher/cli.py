"""Command-line interface for the Amul stock watcher."""

from __future__ import annotations

import logging

import click

from .checker import ProductAvailabilityChecker

logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--force",
    is_flag=True,
    help="Force send notification for all products regardless of availability status.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print notification to terminal instead of sending to Telegram.",
)
def main(force: bool, dry_run: bool) -> None:
    if dry_run:
        logger.info("DRY RUN mode enabled - notifications will be printed to terminal")
    checker = ProductAvailabilityChecker()
    checker.run(force_notify=force, dry_run=dry_run)
