"""Terminal visual components for VIVOXG BOT."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

_console = Console()
_trade_header_printed = False


def print_startup_banner(version: str = "") -> None:
    """Full-width ASCII art startup banner shown before login."""
    try:
        import pyfiglet
        art = pyfiglet.figlet_format("VIVOXG BOT", font="slant")
    except Exception:
        art = "  VIVOXG BOT\n"

    _console.print(f"[bold bright_cyan]{art}[/bold bright_cyan]", end="")
    _console.print()
    _console.print("  [dim white]Polymarket Intelligence Engine[/dim white]")
    _console.print("  [cyan]════════════════════════════════════════[/cyan]")
    ver_str = f"v{version}  ·  " if version else ""
    _console.print(f"  [dim white]{ver_str}[/dim white][bold magenta]by vivoxG[/bold magenta]",
                   justify="right")
    _console.print()


def print_status_dashboard(mode: str, username: str, balance: float,
                            pnl: float, win_rate: float, n_trades: int) -> None:
    """Rich Panel with session status shown after login, before trading."""
    mode_upper = mode.upper()
    mode_color = "green" if mode_upper == "PAPER" else "red"
    pnl_color = "green" if pnl >= 0 else "red"
    pnl_sign = "+" if pnl >= 0 else ""
    wr_str = f"{win_rate:.0%} (last {n_trades} trades)" if n_trades else "N/A"

    table = Table(show_header=False, box=None, padding=(0, 1), show_edge=False)
    table.add_column("Key", style="bold dim", min_width=14)
    table.add_column("Value")
    table.add_row("Mode",        f"[bold {mode_color}]{mode_upper}[/bold {mode_color}]")
    table.add_row("User",        f"[white]{username}[/white]")
    table.add_row("Balance",     f"[white]${balance:.2f}[/white]")
    table.add_row("Session P&L", f"[bold {pnl_color}]{pnl_sign}${abs(pnl):.2f}[/bold {pnl_color}]")
    table.add_row("Win Rate",    wr_str)
    table.add_row("Status",      "[bold green]READY[/bold green]")

    _console.print()
    _console.print(Panel(table, title="[bold cyan]● Session Status[/bold cyan]",
                          border_style="cyan", padding=(1, 2)))
    _console.print()


def print_trade_log_header() -> None:
    """Print column headers for the live trade log."""
    global _trade_header_printed
    if _trade_header_printed:
        return
    _trade_header_printed = True
    header = (
        f"{'Time':<9}{'Direction':<12}{'Score':<8}"
        f"{'Conf':<7}{'Bet':<9}{'Result':<8}"
        f"{'P&L':<13}{'Balance'}"
    )
    _console.print(f"[bold dim]{header}[/bold dim]")
    _console.print(f"[dim]{'─' * 78}[/dim]")


def print_trade_row(time_str: str, direction: str, score: float, confidence: float,
                    bet: float, result: str, pnl: float, balance: float) -> None:
    """Print a single trade row, colored by result (WIN=green, LOSS=red, SKIP=dim yellow)."""
    result_upper = result.upper()
    if result_upper == "WIN":
        style = "green"
    elif result_upper == "LOSS":
        style = "red"
    else:
        style = "dim yellow"

    pnl_sign = "+" if pnl >= 0 else ""
    score_str = f"{score:+.1f}"
    conf_str = f"{confidence:.0%}"
    bet_str = f"${bet:.2f}"
    pnl_str = f"{pnl_sign}${abs(pnl):.4f}"
    bal_str = f"${balance:.2f}"

    row = (
        f"{time_str:<9}{direction.upper():<12}{score_str:<8}"
        f"{conf_str:<7}{bet_str:<9}{result_upper:<8}"
        f"{pnl_str:<13}{bal_str}"
    )
    _console.print(f"[{style}]{row}[/{style}]")


def print_session_footer() -> None:
    """Print the closing signature at session end."""
    _console.print()
    _console.print("[dim]  ─────────────────────────────────────────[/dim]")
    _console.print("[dim]  Session ended  ·  vivoxG Polymarket Bot[/dim]")
    _console.print("[dim]  ─────────────────────────────────────────[/dim]")
    _console.print()
