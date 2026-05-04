import hashlib
import hmac
import time

import requests
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from src.config_manager import CONFIG_BASE, UserConfig

console = Console()
MAX_VALIDATION_ATTEMPTS = 3


# ── Instruction panels ────────────────────────────────────────────────────────

def _show_polymarket_instructions() -> None:
    console.print(Panel(
        "  1. Open your browser and go to:\n"
        "     [bold]https://polymarket.com[/bold]\n\n"
        "  2. Connect your wallet (MetaMask or Coinbase)\n"
        "     If you don't have one, install MetaMask from:\n"
        "     [bold]https://metamask.io[/bold]\n\n"
        "  3. Once connected, click your profile icon (top right)\n\n"
        "  4. Go to [bold]Settings → API Keys[/bold]\n\n"
        "  5. Click [bold]\"Create API Key\"[/bold]\n\n"
        "  6. Copy the key that looks like:\n"
        "     [dim]xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx[/dim]\n\n"
        "  7. Also copy your [bold]API Secret[/bold] (shown only once!)\n"
        "     and your [bold]Passphrase[/bold]\n\n"
        "  Paste your API Key below ↓",
        title="[bold cyan]HOW TO GET YOUR POLYMARKET API KEY[/bold cyan]",
        border_style="cyan",
    ))


def _show_anthropic_instructions() -> None:
    console.print(Panel(
        "  1. Go to: [bold]https://console.anthropic.com[/bold]\n\n"
        "  2. Sign up or log in\n\n"
        "  3. Click [bold]\"API Keys\"[/bold] in the left sidebar\n\n"
        "  4. Click [bold]\"Create Key\"[/bold] → give it a name\n\n"
        "  5. Copy the key that starts with:\n"
        "     [dim]sk-ant-XXXXXXXXXXXXXXXXXXXXXXXXXX[/dim]\n\n"
        "  [bold yellow]⚠ You can only copy it once. Save it somewhere safe.[/bold yellow]\n\n"
        "  Paste your Anthropic API Key below ↓",
        title="[bold cyan]HOW TO GET YOUR ANTHROPIC API KEY[/bold cyan]",
        border_style="cyan",
    ))


def _show_binance_instructions() -> None:
    console.print(Panel(
        "  1. Go to: [bold]https://www.binance.com[/bold]\n\n"
        "  2. Log in → click your profile icon (top right)\n\n"
        "  3. Go to [bold]API Management[/bold]\n\n"
        "  4. Click [bold]\"Create API\"[/bold] → choose [bold]\"System generated\"[/bold]\n\n"
        "  5. Give it a label (e.g. [dim]\"polymarket-bot\"[/dim])\n\n"
        "  6. [bold]IMPORTANT:[/bold] Under permissions, enable:\n"
        "     [bold green]✓ Read Info only[/bold green]\n"
        "     [bold red]✗ Do NOT enable trading or withdrawals[/bold red]\n\n"
        "  7. Copy the [bold]API Key[/bold] and [bold]Secret Key[/bold]\n\n"
        "  Paste your Binance API Key below ↓",
        title="[bold cyan]HOW TO GET YOUR BINANCE API KEY[/bold cyan]",
        border_style="cyan",
    ))


# ── Validators ────────────────────────────────────────────────────────────────

def _validate_anthropic_key(key: str) -> tuple[bool, str]:
    key = key.strip()
    if key.startswith("sk-ant-") and len(key) > 20:
        return True, ""
    return False, "Anthropic keys start with 'sk-ant-' — check you copied the full key"


def _validate_binance_key(api_key: str, api_secret: str) -> tuple[bool, str]:
    try:
        timestamp = int(time.time() * 1000)
        params = f"timestamp={timestamp}"
        signature = hmac.new(
            api_secret.encode(), params.encode(), hashlib.sha256
        ).hexdigest()
        url = f"https://api.binance.com/api/v3/account?{params}&signature={signature}"
        resp = requests.get(url, headers={"X-MBX-APIKEY": api_key}, timeout=10)
        if resp.status_code == 200:
            return True, ""
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as exc:
        return False, str(exc)


def _validate_polymarket_key(key: str) -> tuple[bool, str]:
    key = key.strip()
    if len(key) >= 10:
        return True, ""
    return False, "Key appears too short — make sure you copied the full key"


# ── Generic prompt-with-validation helper ─────────────────────────────────────

def _prompt_with_validation(
    label: str,
    validator,
    password: bool = False,
) -> "str | None":
    """Prompt for a value and validate it, retrying up to MAX_VALIDATION_ATTEMPTS times.
    Returns the validated value, or None if all attempts fail."""
    for attempt in range(1, MAX_VALIDATION_ATTEMPTS + 1):
        value = Prompt.ask(f"[bold]{label}[/bold]", password=password).strip()
        with console.status("[cyan]Testing connection…[/cyan]", spinner="dots"):
            ok, error = validator(value)
        if ok:
            console.print("[bold green]  ✓ Connected successfully[/bold green]")
            return value
        console.print("[bold red]  ✗ Invalid key[/bold red]")
        console.print(f"[dim red]  {error}[/dim red]")
        console.print(
            "  [yellow]Hint: Double-check you copied the full key including the prefix[/yellow]"
        )
        if attempt < MAX_VALIDATION_ATTEMPTS:
            console.print(f"  [dim]Attempt {attempt}/{MAX_VALIDATION_ATTEMPTS} — try again[/dim]\n")
        else:
            console.print(
                "\n[yellow]Skipping for now — you can re-run setup with: "
                "python btc_agent.py --setup[/yellow]"
            )
    return None


# ── Existing helpers ──────────────────────────────────────────────────────────

def _prompt_password(label: str) -> str:
    while True:
        pw = Prompt.ask(f"[bold]{label}[/bold]", password=True)
        if len(pw) < 8:
            console.print("[red]Password must be at least 8 characters.[/red]")
            continue
        return pw


# ── Account creation ──────────────────────────────────────────────────────────

def _create_account() -> "UserConfig | None":
    console.print("\n[bold cyan]CREATE ACCOUNT[/bold cyan]\n")

    while True:
        username = Prompt.ask("[bold]Choose a username[/bold]").strip()
        if not username or " " in username:
            console.print("[red]Username cannot be empty or contain spaces.[/red]")
            continue
        cfg = UserConfig(username)
        if cfg.exists():
            console.print(f"[red]User '{username}' already exists. Choose 'Login' instead.[/red]")
            continue
        break

    while True:
        password = _prompt_password("Choose a password (min 8 chars)")
        confirm  = _prompt_password("Confirm password")
        if password != confirm:
            console.print("[red]Passwords do not match. Try again.[/red]")
            continue
        break

    # ── Polymarket ────────────────────────────────────────────────────────────
    _show_polymarket_instructions()
    poly_key = _prompt_with_validation("  API Key", _validate_polymarket_key)
    poly_ok = poly_key is not None
    if poly_ok:
        cfg.polymarket_api_key        = poly_key
        cfg.polymarket_api_secret     = Prompt.ask("[bold]  API Secret[/bold]", password=True).strip()
        cfg.polymarket_api_passphrase = Prompt.ask("[bold]  API Passphrase[/bold]", password=True).strip()
        cfg.polymarket_private_key    = Prompt.ask("[bold]  Private Key (0x...)[/bold]", password=True).strip()
        cfg.polymarket_funder_address = Prompt.ask("[bold]  Funder Address (0x...)[/bold]").strip()

    # ── Anthropic ─────────────────────────────────────────────────────────────
    _show_anthropic_instructions()
    ant_key = _prompt_with_validation("  Anthropic API Key", _validate_anthropic_key, password=True)
    cfg.anthropic_api_key = ant_key or ""
    ant_ok = ant_key is not None

    # ── Binance (optional) ────────────────────────────────────────────────────
    bin_ok = False
    if Confirm.ask("\n[bold]Add a Binance API key?[/bold] (optional — enhances market data)", default=False):
        _show_binance_instructions()
        for attempt in range(1, MAX_VALIDATION_ATTEMPTS + 1):
            bin_key    = Prompt.ask("[bold]  Binance API Key[/bold]", password=True).strip()
            bin_secret = Prompt.ask("[bold]  Binance Secret Key[/bold]", password=True).strip()
            with console.status("[cyan]Testing Binance connection…[/cyan]", spinner="dots"):
                ok, error = _validate_binance_key(bin_key, bin_secret)
            if ok:
                console.print("[bold green]  ✓ Binance connected[/bold green]")
                cfg.binance_api_key = bin_key
                bin_ok = True
                break
            console.print("[bold red]  ✗ Invalid key[/bold red]")
            console.print(f"[dim red]  {error}[/dim red]")
            console.print(
                "  [yellow]Hint: Double-check you copied the full key including the prefix[/yellow]"
            )
            if attempt < MAX_VALIDATION_ATTEMPTS:
                console.print(f"  [dim]Attempt {attempt}/{MAX_VALIDATION_ATTEMPTS} — try again[/dim]\n")
            else:
                console.print(
                    "\n[yellow]Skipping Binance — you can re-run setup with: "
                    "python btc_agent.py --setup[/yellow]"
                )

    # ── Paper balance ─────────────────────────────────────────────────────────
    balance_str = Prompt.ask("\n[bold]Starting paper balance[/bold]", default="200")
    try:
        cfg.paper_balance = max(float(balance_str), 1.0)
    except ValueError:
        cfg.paper_balance = 200.0

    cfg.save(password)

    # ── Summary panel ─────────────────────────────────────────────────────────
    def _status(ok: bool) -> str:
        return "[bold green]✓[/bold green] connected" if ok else "[bold red]✗[/bold red] skipped"

    console.print(Panel(
        f"  [bold green]✓[/bold green] Anthropic API       {_status(ant_ok)}\n"
        f"  [bold green]✓[/bold green] Binance API         {_status(bin_ok)}\n"
        f"  [bold green]✓[/bold green] Polymarket API      {_status(poly_ok)}\n"
        f"  [bold green]✓[/bold green] Config saved & encrypted\n\n"
        f"  Starting balance: [bold]${cfg.paper_balance:.2f}[/bold] (paper)\n\n"
        f"  Run the bot:\n"
        f"  [bold]python btc_agent.py --paper[/bold]    ← practice mode\n"
        f"  [bold]python btc_agent.py --real[/bold]     ← live trading",
        title="[bold green]SETUP COMPLETE[/bold green]",
        border_style="cyan",
    ))

    return cfg


# ── Login ─────────────────────────────────────────────────────────────────────

def _login() -> "UserConfig | None":
    console.print("\n[bold cyan]LOGIN[/bold cyan]\n")

    username = Prompt.ask("[bold]Username[/bold]").strip()
    cfg = UserConfig(username)

    if not cfg.exists():
        console.print(f"[red]No account found for '{username}'.[/red]")
        return None

    for attempt in range(3):
        password = _prompt_password("Password")
        if cfg.load(password):
            console.print(f"\n[bold green]✓ Logged in as '{username}'[/bold green]\n")
            return cfg
        remaining = 2 - attempt
        if remaining > 0:
            console.print(f"[red]Incorrect password. {remaining} attempt(s) remaining.[/red]")
        else:
            console.print("[red]Too many failed attempts.[/red]")

    return None


# ── Entry point ───────────────────────────────────────────────────────────────

def run_wizard(force: bool = False, version: str = "") -> "UserConfig | None":
    """
    Run the setup wizard. Returns a loaded UserConfig on success, None on failure.
    force=True re-runs the create/login menu even when users already exist.
    """
    from src.terminal_ui import print_startup_banner
    print_startup_banner(version)

    existing_users = (
        [d.name for d in CONFIG_BASE.iterdir() if d.is_dir()]
        if CONFIG_BASE.exists()
        else []
    )

    if not existing_users or force:
        choice = Prompt.ask(
            "\n[bold]Choose an option[/bold]\n  1. Create account\n  2. Login\n",
            choices=["1", "2"],
            default="1",
        )
    else:
        choice = "2"

    if choice == "1":
        return _create_account()
    return _login()


# ── Reset ─────────────────────────────────────────────────────────────────────

def handle_reset() -> None:
    """Interactively delete a user's local config."""
    if not CONFIG_BASE.exists():
        console.print("[yellow]No configuration directory found.[/yellow]")
        return

    users = [d.name for d in CONFIG_BASE.iterdir() if d.is_dir()]
    if not users:
        console.print("[yellow]No local users found to delete.[/yellow]")
        return

    console.print(f"[bold]Existing users:[/bold] {', '.join(users)}")
    username = Prompt.ask("[bold]Username to delete[/bold]").strip()
    cfg = UserConfig(username)

    if not cfg.exists():
        console.print(f"[red]No config found for '{username}'.[/red]")
        return

    if Confirm.ask(
        f"[bold red]Delete all config data for '{username}'?[/bold red] This cannot be undone.",
        default=False,
    ):
        cfg.delete()
        console.print(f"[green]Config for '{username}' deleted.[/green]")
    else:
        console.print("[yellow]Cancelled.[/yellow]")
