#!/usr/bin/env python3
"""
mailAlfred - Automated email classification for Gmail.

Fetches new emails from Gmail, classifies them using an LLM,
and applies classification labels back to Gmail.
"""

import asyncio
import argparse
from dataclasses import dataclass
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich import print as rprint

from src.connectors.gmail_connector import GmailConnector
from src.models.email import Email
from src.models.classified_email import ClassifiedEmail, ALLOWED_LABELS
from src.utils.prompts import get_email_classification_prompt
from src.utils.inference import do_structured_output_inference


# Default concurrency for parallel processing
DEFAULT_CONCURRENCY = 10
MAX_GMAIL_BATCH_SIZE = 1000
METADATA_HEADERS = ["From", "To", "Cc", "Subject", "Date"]

# Rich console
console = Console()

# Classification label IDs (will be populated on first check)
_classification_label_ids: set[str] = set()


# Label colors for rich output
LABEL_COLORS = {
    "classifications/respond": "bold red",
    "classifications/urgent": "bold yellow",
    "classifications/action": "yellow",
    "classifications/opportunities": "green",
    "classifications/academic": "bright_cyan",
    "classifications/notifications": "blue",
    "classifications/records": "bright_black",
    "classifications/read_later": "cyan",
    "classifications/marketing": "dim",
    "classifications/bulk": "dim",
    "classifications/unsure": "magenta",
    "errors": "red",
}


@dataclass
class ClassificationResult:
    """Result of classifying a single email."""
    email: Email
    label: Optional[str] = None
    error: Optional[str] = None


def _get_classification_label_ids(gmail: GmailConnector) -> set[str]:
    """Get the Gmail label IDs for all classification labels."""
    global _classification_label_ids
    if not _classification_label_ids:
        _classification_label_ids |= {
            label_id for label_name in ALLOWED_LABELS if (label_id := gmail.get_label_id(label_name))
        }
    return _classification_label_ids


def is_already_classified(email: Email, gmail: GmailConnector) -> bool:
    """Check if an email already has a classification label."""
    classification_ids = _get_classification_label_ids(gmail)
    return bool(set(email.labels) & classification_ids)


async def classify_email_task(
    email: Email,
    progress: Progress,
    task_id,
) -> ClassificationResult:
    """Classify a single email using the LLM."""
    try:
        prompt = get_email_classification_prompt(email)
        result = await do_structured_output_inference(
            user_prompt=prompt,
            schema=ClassifiedEmail,
        )
        progress.advance(task_id)
        return ClassificationResult(email=email, label=result.label)
    except Exception as e:
        progress.advance(task_id)
        return ClassificationResult(email=email, error=str(e))


def print_summary(stats: dict[str, int], scanned: int, skipped: int, dry_run: bool) -> None:
    """Print a beautiful summary table."""
    table = Table(title="📊 Classification Summary", show_header=True, header_style="bold")
    table.add_column("Label", style="cyan")
    table.add_column("Count", justify="right", style="green")
    
    total_classified = 0
    for label in sorted(ALLOWED_LABELS):
        count = stats.get(label, 0)
        if count > 0:
            color = LABEL_COLORS.get(label, "white")
            short_label = label.replace("classifications/", "")
            table.add_row(f"[{color}]{short_label}[/{color}]", str(count))
            total_classified += count
    
    if "errors" in stats:
        table.add_row("[red]errors[/red]", str(stats["errors"]))
    
    table.add_section()
    table.add_row("[bold]Total classified[/bold]", f"[bold]{total_classified}[/bold]")
    table.add_row("Already classified (skipped)", str(skipped))
    table.add_row("Total scanned", str(scanned))
    
    if dry_run:
        table.add_row("[yellow]Mode[/yellow]", "[yellow]DRY RUN[/yellow]")
    
    console.print()
    console.print(table)


def _chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _scan_limit_reached(limit: Optional[int], scan_limit: Optional[int], queued: int, scanned: int) -> bool:
    return bool((limit and queued >= limit) or (scan_limit and scanned >= scan_limit))


def _scan_unclassified_emails(
    gmail: GmailConnector,
    progress: Progress,
    task_id,
    limit: Optional[int],
    scan_limit: Optional[int],
) -> tuple[list[Email], int, int]:
    emails_to_process_meta: list[Email] = []
    scanned = 0
    skipped = 0
    for email in gmail.iter_messages(
        use_seen_cache=True,
        message_format="metadata",
        metadata_headers=METADATA_HEADERS,
    ):
        scanned += 1
        progress.update(task_id, completed=scanned, description=f"[cyan]Scanning... ({len(emails_to_process_meta)} to classify, {skipped} done)")
        if is_already_classified(email, gmail):
            skipped += 1
            continue
        emails_to_process_meta.append(email)
        if _scan_limit_reached(limit, scan_limit, len(emails_to_process_meta), scanned):
            break
    return emails_to_process_meta, scanned, skipped


def _preview(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[:limit]}..."


def _record_classification_result(
    result: ClassificationResult,
    dry_run: bool,
    verbose: bool,
    stats: dict[str, int],
    label_groups: dict[str, list[str]],
) -> None:
    subject_preview = _preview(result.email.subject, 60)
    sender_preview = _preview(result.email.sender, 30)
    if result.error:
        console.print(f"[red]✗[/red] [dim]{sender_preview}[/dim]")
        console.print(f"  {subject_preview}")
        console.print(f"  [red]Error: {result.error}[/red]")
        stats["errors"] = stats.get("errors", 0) + 1
        return

    label = result.label
    stats[label] = stats.get(label, 0) + 1
    if not dry_run:
        label_groups.setdefault(label, []).append(result.email.id)
    if not (verbose or label in ("classifications/respond", "classifications/urgent")):
        return

    color = LABEL_COLORS.get(label, "white")
    short_label = label.replace("classifications/", "")
    console.print(f"[{color}]●[/{color}] [{color}]{short_label}[/{color}] [dim]{sender_preview}[/dim]")
    console.print(f"  {subject_preview}")


def _apply_label_groups(gmail: GmailConnector, label_groups: dict[str, list[str]]) -> None:
    for label, email_ids in label_groups.items():
        for batch in _chunked(email_ids, MAX_GMAIL_BATCH_SIZE):
            gmail.add_labels_bulk(batch, [label])


async def _show_countdown(interval: int) -> None:
    with Progress(
        SpinnerColumn(),
        TextColumn("[dim]Next check in {task.fields[remaining]}s...[/dim]"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("waiting", total=interval, remaining=interval)
        for i in range(interval):
            await asyncio.sleep(1)
            progress.update(task, advance=1, remaining=interval - i - 1)


async def _run_watch_iteration(
    gmail: GmailConnector,
    interval: int,
    dry_run: bool,
    verbose: bool,
    concurrency: int,
) -> None:
    stats = await process_emails(
        gmail,
        dry_run=dry_run,
        verbose=verbose,
        concurrency=concurrency,
    )
    if sum(stats.values()) > 0:
        console.print()
    await _show_countdown(interval)


async def process_emails(
    gmail: GmailConnector,
    limit: Optional[int] = None,
    scan_limit: Optional[int] = None,
    dry_run: bool = False,
    verbose: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> dict[str, int]:
    """
    Process and classify emails from Gmail in parallel.
    """
    stats: dict[str, int] = {}
    emails_to_process: list[Email] = []
    scanned = 0
    skipped = 0
    
    # Phase 1: Scan for unclassified emails
    console.print(Panel.fit("📬 [bold]mailAlfred[/bold] - Email Classification", style="blue"))
    console.print()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        scan_task = progress.add_task(
            "[cyan]Scanning inbox...",
            total=scan_limit if scan_limit else None,
        )
        
        emails_to_process_meta, scanned, skipped = _scan_unclassified_emails(
            gmail=gmail,
            progress=progress,
            task_id=scan_task,
            limit=limit,
            scan_limit=scan_limit,
        )
        progress.update(scan_task, completed=scanned, description=f"[green]✓ Scan complete")
    
    if not emails_to_process_meta:
        console.print(f"\n[green]✅ No unclassified emails found.[/green] (Scanned {scanned}, skipped {skipped})")
        return stats

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        fetch_task = progress.add_task(
            "[cyan]Loading email content...",
            total=len(emails_to_process_meta),
        )
        for meta_email in emails_to_process_meta:
            emails_to_process.append(gmail.fetch_email(meta_email.id, message_format="full"))
            progress.advance(fetch_task)
    
    console.print(f"\n[bold]Found {len(emails_to_process)} emails to classify[/bold] (concurrency: {concurrency})")
    if dry_run:
        console.print("[yellow]⚠️  DRY RUN - labels will not be applied[/yellow]")
    console.print()
    
    # Phase 2: Classify emails in parallel
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        classify_task = progress.add_task(
            "[cyan]Classifying emails...",
            total=len(emails_to_process),
        )
        
        results: list[ClassificationResult] = []
        batch_size = max(1, concurrency)
        for batch in _chunked(emails_to_process, batch_size):
            tasks = [
                classify_email_task(email, progress, classify_task)
                for email in batch
            ]
            results.extend(await asyncio.gather(*tasks))
    
    # Phase 3: Apply labels and show results
    console.print()
    
    label_groups: dict[str, list[str]] = {}

    for result in results:
        _record_classification_result(result, dry_run, verbose, stats, label_groups)
    if not dry_run:
        _apply_label_groups(gmail, label_groups)
    
    # Print summary
    print_summary(stats, scanned, skipped, dry_run)
    
    return stats


async def watch_mode(
    interval: int = 30,
    dry_run: bool = False,
    verbose: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> None:
    """Continuously watch for new emails and classify them."""
    console.print(Panel.fit(
        f"👀 [bold]Watch Mode[/bold]\n"
        f"Checking every {interval}s • Concurrency: {concurrency}\n"
        f"[dim]Press Ctrl+C to stop[/dim]",
        style="blue"
    ))
    console.print()
    
    with GmailConnector() as gmail:
        await _watch_loop(gmail, interval, dry_run, verbose, concurrency)


async def _watch_loop(
    gmail: GmailConnector,
    interval: int,
    dry_run: bool,
    verbose: bool,
    concurrency: int,
) -> None:
    while True:
        try:
            await _run_watch_iteration(
                gmail=gmail,
                interval=interval,
                dry_run=dry_run,
                verbose=verbose,
                concurrency=concurrency,
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]👋 Stopping watch mode.[/yellow]")
            break


def _run_cli(args) -> None:
    if args.watch:
        asyncio.run(watch_mode(
            interval=args.interval,
            dry_run=args.dry_run,
            verbose=args.verbose,
            concurrency=args.concurrency,
        ))
        return

    with GmailConnector() as gmail:
        asyncio.run(process_emails(
            gmail=gmail,
            limit=args.limit,
            scan_limit=args.scan_limit,
            dry_run=args.dry_run,
            verbose=args.verbose,
            concurrency=args.concurrency,
        ))


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="mailAlfred - Automated email classification for Gmail"
    )
    parser.add_argument(
        "-n", "--limit",
        type=int,
        default=None,
        help="Maximum number of emails to classify (default: all unclassified)"
    )
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=None,
        help="Max emails to scan (stop early even if not all checked)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't apply labels, just show what would be classified"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show all classification results (not just requires_action)"
    )
    parser.add_argument(
        "-w", "--watch",
        action="store_true",
        help="Continuously watch for new emails"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Seconds between checks in watch mode (default: 30)"
    )
    parser.add_argument(
        "-c", "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Max parallel classification requests (default: {DEFAULT_CONCURRENCY})"
    )
    
    args = parser.parse_args()
    
    try:
        _run_cli(args)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")


if __name__ == "__main__":
    main()
