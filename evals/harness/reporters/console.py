"""Rich console reporter — color-coded summary tables."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from harness.reporters import ReportData


class ConsoleReporter:
    """Prints score summaries to the terminal using Rich tables."""

    def __init__(self, verbose: bool = False) -> None:
        self._verbose = verbose

    def report(self, data: ReportData) -> None:
        """Render summary tables to the console."""
        console = Console()

        if not data.records:
            console.print("No scores collected.")
            return

        # --- Metric Summary ---
        summary_table = Table(title="Behavioral Test Summary")
        summary_table.add_column("Metric", style="bold")
        summary_table.add_column("Mean", justify="right")
        summary_table.add_column("Pass Rate", justify="right")
        summary_table.add_column("Count", justify="right")
        summary_table.add_column("Min", justify="right")
        summary_table.add_column("Max", justify="right")

        for ms in data.summary.values():
            if ms.pass_rate >= 0.9:
                pr_style = "green"
            elif ms.pass_rate >= 0.7:
                pr_style = "yellow"
            else:
                pr_style = "red"

            summary_table.add_row(
                ms.name,
                f"{ms.mean:.2f}",
                f"[{pr_style}]{ms.pass_rate:.0%}[/{pr_style}]",
                str(ms.count),
                f"{ms.min_val:.2f}",
                f"{ms.max_val:.2f}",
            )

        console.print(summary_table)

        # --- Latency Percentiles ---
        if data.latency is not None and data.latency.count > 0:
            lat = data.latency.summary()
            lat_table = Table(title="Latency Percentiles (seconds)")
            for col in ("p50", "p95", "p99", "Min", "Max"):
                lat_table.add_column(col, justify="right")

            lat_table.add_row(
                f"{lat['p50']:.3f}" if lat["p50"] is not None else "-",
                f"{lat['p95']:.3f}" if lat["p95"] is not None else "-",
                f"{lat['p99']:.3f}" if lat["p99"] is not None else "-",
                f"{lat['min']:.3f}" if lat["min"] is not None else "-",
                f"{lat['max']:.3f}" if lat["max"] is not None else "-",
            )
            console.print(lat_table)

        # --- Per-Score Breakdown (verbose only) ---
        if self._verbose:
            detail_table = Table(title="Score Details")
            detail_table.add_column("Query", max_width=50)
            detail_table.add_column("Test")
            detail_table.add_column("Scorer")
            detail_table.add_column("Value", justify="right")
            detail_table.add_column("Result", justify="center")

            for rec in data.records:
                query_display = rec.query
                result_icon = "[green]✓[/green]" if rec.score.passed else "[red]✗[/red]"
                detail_table.add_row(
                    query_display,
                    rec.test_name,
                    rec.score.name,
                    f"{rec.score.value:.2f}",
                    result_icon,
                )

            console.print(detail_table)


__all__ = ["ConsoleReporter"]
