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
METADATA_HEADERS = ["From", "To", "Cc", "Subject", "Date"]

# Rich console
console = Console()

# Classification label IDs (will be populated on first check)
_classification_label_ids: set[str] = set()


# Label colors for rich output
LABEL_COLORS = {
    "classifications/bulk_content": "dim",
    "classifications/read_later": "cyan",
    "classifications/records": "yellow",
    "classifications/requires_action": "bold red",
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
        for label_name in ALLOWED_LABELS:
            label_id = gmail.get_label_id(label_name)
            if label_id:
                _classification_label_ids.add(label_id)
    return _classification_label_ids


def is_already_classified(email: Email, gmail: GmailConnector) -> bool:
    """Check if an email already has a classification label."""
    classification_ids = _get_classification_label_ids(gmail)
    return bool(set(email.labels) & classification_ids)


async def classify_email_task(
    email: Email,
    semaphore: asyncio.Semaphore,
    progress: Progress,
    task_id,
) -> ClassificationResult:
    """Classify a single email using the LLM (with concurrency control)."""
    async with semaphore:
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
    emails_to_process_meta: list[Email] = []
    skipped = 0
    scanned = 0
    
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
        
        for email in gmail.iter_messages(
            use_seen_cache=True,
            message_format="metadata",
            metadata_headers=METADATA_HEADERS,
        ):
            scanned += 1
            progress.update(scan_task, completed=scanned, description=f"[cyan]Scanning... ({len(emails_to_process_meta)} to classify, {skipped} done)")
            
            if is_already_classified(email, gmail):
                skipped += 1
                continue
            
            emails_to_process_meta.append(email)
            
            if limit and len(emails_to_process_meta) >= limit:
                break
            
            if scan_limit and scanned >= scan_limit:
                break
        
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
        
        semaphore = asyncio.Semaphore(concurrency)
        tasks = [
            classify_email_task(email, semaphore, progress, classify_task)
            for email in emails_to_process
        ]
        
        results: list[ClassificationResult] = await asyncio.gather(*tasks)
    
    # Phase 3: Apply labels and show results
    console.print()
    
    for result in results:
        subject_preview = result.email.subject[:60] + "..." if len(result.email.subject) > 60 else result.email.subject
        sender_preview = result.email.sender[:30] + "..." if len(result.email.sender) > 30 else result.email.sender
        
        if result.error:
            console.print(f"[red]✗[/red] [dim]{sender_preview}[/dim]")
            console.print(f"  {subject_preview}")
            console.print(f"  [red]Error: {result.error}[/red]")
            stats["errors"] = stats.get("errors", 0) + 1
        else:
            label = result.label
            stats[label] = stats.get(label, 0) + 1
            color = LABEL_COLORS.get(label, "white")
            short_label = label.replace("classifications/", "")
            
            if not dry_run:
                gmail.classify_email(result.email.id, label)
            
            if verbose or label == "classifications/requires_action":
                console.print(f"[{color}]●[/{color}] [{color}]{short_label}[/{color}] [dim]{sender_preview}[/dim]")
                console.print(f"  {subject_preview}")
    
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
        while True:
            try:
                stats = await process_emails(
                    gmail,
                    dry_run=dry_run,
                    verbose=verbose,
                    concurrency=concurrency,
                )
                if sum(stats.values()) > 0:
                    console.print()
                
                # Show countdown
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
                        
            except KeyboardInterrupt:
                console.print("\n[yellow]👋 Stopping watch mode.[/yellow]")
                break


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
        if args.watch:
            asyncio.run(watch_mode(
                interval=args.interval,
                dry_run=args.dry_run,
                verbose=args.verbose,
                concurrency=args.concurrency,
            ))
        else:
            with GmailConnector() as gmail:
                asyncio.run(process_emails(
                    gmail=gmail,
                    limit=args.limit,
                    scan_limit=args.scan_limit,
                    dry_run=args.dry_run,
                    verbose=args.verbose,
                    concurrency=args.concurrency,
                ))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")


if __name__ == "__main__":
    main()
