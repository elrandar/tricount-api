"""
Tricount API CLI

A command-line interface for the Tricount API, built on click + rich.
"""

from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from pathlib import Path

import click
from rich.console import Console
from rich.tree import Tree

from .client import Category, Credentials, Member, Tricount, TricountAPI, load_client

# =============================================================================
# Click
# =============================================================================

CONTEXT_SETTINGS = dict(help_option_names=["--help"])
console = Console()
_CATEGORIES = [c.name for c in Category]

# Default credentials file, created in the current directory on first use.
_DEFAULT_CREDS = "tricount_credentials.json"


class OrderedGroup(click.Group):
    """List commands in definition order, not alphabetically."""

    def list_commands(self, ctx):
        return [*self.commands]


@click.group(cls=OrderedGroup, context_settings=CONTEXT_SETTINGS,
             help="Unofficial Tricount (bunq) Python CLI.")
@click.option("--creds", default=_DEFAULT_CREDS, show_default=True,
              type=click.Path(dir_okay=False),
              help="Credentials file, auto-generated on first use.")
@click.version_option(package_name="tricount-api", prog_name="tricount")
@click.pass_context
def cli(ctx, creds):
    ctx.obj = creds


# =============================================================================
# Setup
# =============================================================================

@cli.command(short_help="Generate credentials.",
             help=f"Generate and store credentials, defaulting to {_DEFAULT_CREDS} if no path is given.")
@click.argument("path", required=False, type=click.Path(dir_okay=False))
@click.option("--force", "-f", is_flag=True, help="Overwrite an existing credentials file.")
@click.pass_obj
def init(creds: str, path: str | None, force: bool):
    path = Path(path or creds)
    if path.exists() and not force:
        _err(f"{path} already exists. Use --force to overwrite.")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    Credentials.generate().save(path)
    _ok(f"Initialized credentials at [bold]{path}[/bold].")


# =============================================================================
# Tricounts
# =============================================================================

@cli.command(short_help="Create a tricount",
             help="Create a new tricount, optionally seeding it with members.")
@click.argument("title")
@click.argument("currency")
@click.option("--description", default="", help="Optional description.")
@click.option("--member", "members", multiple=True, metavar="NAME",
              help="Member to add (repeatable).")
@click.pass_obj
def create(creds, title, currency, description, members):
    with _client(creds, "Creating tricount...") as api:
        tri = api.get_tricount_by_id(api.create_tricount(title, currency, description))
        if members:
            api.add_members(tri, [*members])
    _ok(f"Created [bold]{title}[/bold] [dim](token {tri.public_identifier_token})[/dim]")
    if members:
        _step(f"Members: {', '.join(members)}")


@cli.command(short_help="Join a tricount",
             help="Sync a tricount to your account so it shows in `list` and accepts writes.")
@click.argument("token")
@click.pass_obj
def join(creds, token):
    with _client(creds, "Joining tricount...") as api:
        tri = api.join_tricount(token)
    _ok(f"Joined [bold]{tri.title}[/bold] [dim](id {tri.id})[/dim]")


@cli.command(short_help="Leave a tricount", help="Remove a tricount from your synced list.")
@click.argument("token")
@click.pass_obj
def leave(creds, token):
    with _client(creds, "Leaving tricount...") as api:
        api.leave_tricount(api.get_tricount(token))
    _ok("Left tricount.")


# =============================================================================
# Members
# =============================================================================

@cli.group(cls=OrderedGroup, short_help="Manage members",
           help="Add, rename, or remove members of a tricount.")
def member():
    pass


@member.command("add", short_help="Add members")
@click.argument("token")
@click.argument("names", nargs=-1, required=True)
@click.pass_obj
def member_add(creds, token, names):
    with _client(creds, "Adding members...") as api:
        api.add_members(api.join_tricount(token), [*names])
    _ok(f"Added: {', '.join(names)}")


@member.command("rename", short_help="Rename a member")
@click.argument("token")
@click.argument("old")
@click.argument("new")
@click.pass_obj
def member_rename(creds, token, old, new):
    with _client(creds, "Renaming member...") as api:
        tri = api.join_tricount(token)
        api.rename_member(tri, _member(tri, old), new)
    _ok(f"Renamed [bold]{old}[/bold] → [bold]{new}[/bold].")


@member.command("remove", short_help="Remove a member")
@click.argument("token")
@click.argument("name")
@click.pass_obj
def member_remove(creds, token, name):
    with _client(creds, "Removing member...") as api:
        tri = api.join_tricount(token)
        api.delete_member(tri, _member(tri, name))
    _ok(f"Removed [bold]{name}[/bold].")


# =============================================================================
# Transactions
# =============================================================================

@cli.command(short_help="Add an expense", help="Add an expense, splitting it among members.")
@click.argument("token")
@click.argument("description")
@click.argument("amount", type=float)
@click.argument("payer")
@click.option("--among", multiple=True, metavar="NAME",
              help="Member to split among (repeatable; default: everyone).")
@click.option("--category", type=click.Choice(_CATEGORIES), default=None,
              help="Standard expense category.")
@click.pass_obj
def add(creds, token, description, amount, payer, among, category):
    with _client(creds, "Adding expense...") as api:
        tri = api.join_tricount(token)  # writing needs the tricount synced to the account
        split = [_member(tri, n) for n in among] if among else tri.members
        cat = Category[category] if category else None
        tid = api.create_transaction(tri, description, amount, _member(tri, payer), split,
                                     category=cat)
    _step(f"{description}: {_amount(-abs(amount), tri.currency)} by [bold]{payer}[/bold] "
          f"[dim]split {len(split)} ways[/dim]")
    _ok(f"Added expense [dim](id {tid})[/dim]")


@cli.command("delete-tx", short_help="Delete a transaction", help="Delete a transaction by id.")
@click.argument("token")
@click.argument("transaction_id", type=int)
@click.pass_obj
def delete_tx(creds, token, transaction_id):
    with _client(creds, "Deleting transaction...") as api:
        api.delete_transaction(api.join_tricount(token), transaction_id)
    _ok(f"Deleted transaction [dim]{transaction_id}[/dim].")


@cli.command(short_help="Record a reimbursement",
             help="Record one member paying another back directly.")
@click.argument("token")
@click.argument("payer")
@click.argument("receiver")
@click.argument("amount", type=float)
@click.pass_obj
def reimburse(creds, token, payer, receiver, amount):
    with _client(creds, "Recording reimbursement...") as api:
        tri = api.join_tricount(token)
        tid = api.create_reimbursement(tri, _member(tri, payer), _member(tri, receiver), amount)
    _ok(f"[bold]{payer}[/bold] → [bold]{receiver}[/bold]: "
        f"{_amount(amount, tri.currency)} [dim](id {tid})[/dim]")


# =============================================================================
# Read
# =============================================================================

@cli.command("list", short_help="List your tricounts",
             help="List the tricounts linked to your credentials.")
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON instead of the tree view.")
@click.pass_obj
def list_cmd(creds, as_json):
    with _client(creds, "Loading tricounts...") as api:
        tricounts = api.list_tricounts()
    if as_json:
        console.print_json(data=[dataclasses.asdict(t) for t in tricounts])
        return
    if not tricounts:
        _warn("No tricount synced. Join one with `tricount join <token>`.")
        return
    root = Tree(f"[bold]Tricounts[/bold] [dim]· {len(tricounts)}[/dim]", guide_style="dim")
    for t in tricounts:
        archived = " [yellow]archived[/yellow]" if t.is_archived else ""
        node = root.add(f"[bold]{t.title}[/bold] [dim]· {t.currency}[/dim]{archived}")
        node.add(f"[dim]token  [/dim] {t.public_identifier_token}")
        node.add(f"[dim]id     [/dim] {t.id}")
        node.add(f"[dim]members[/dim] {len(t.members)}")
    console.print(root)


@cli.command(short_help="Show balances", help="Show who owes whom (positive = is owed money).")
@click.argument("token")
@click.pass_obj
def balances(creds, token):
    with _client(creds, "Fetching tricount...") as api:
        tri = api.get_tricount(token)
    _print_balances(api, tri)


@cli.command(short_help="Show a tricount", help="Show a tricount's transactions and balances.")
@click.argument("token")
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON instead of the tree view.")
@click.pass_obj
def show(creds, token, as_json):
    with _client(creds, "Fetching tricount...") as api:
        tri = api.get_tricount(token)
    if as_json:
        console.print_json(data=dataclasses.asdict(tri))
    else:
        _tricount_tree(api, tri)


@cli.command(short_help="Download a tricount to a JSON file",
             help="Save a tricount as JSON. Writes <title>.json unless -o is given.")
@click.argument("token")
@click.option("-o", "--output", type=click.Path(dir_okay=False),
              help="Output file (default: <title>.json).")
@click.pass_obj
def download(creds, token, output):
    with _client(creds, "Downloading tricount...") as api:
        path = api.download_tricount(token, output)
    _ok(f"Saved → [bold]{path}[/bold]")


# =============================================================================
# Helpers
# =============================================================================

# Output vocabulary (single source for status-line styling).
def _ok(msg: str) -> None:
    console.print(f"[green]✓[/green] {msg}", highlight=False)

def _warn(msg: str) -> None:
    console.print(f"[yellow]⚠[/yellow] {msg}", highlight=False)

def _step(msg: str) -> None:
    console.print(f"[cyan]→[/cyan] {msg}", highlight=False)

def _err(msg: str) -> None:
    console.print(f"[red]✗[/red] {msg}", highlight=False)


@contextmanager
def _client(creds, status="Working..."):
    """Authenticated TricountAPI under a status spinner; surfaces failures as CLI errors.

    The body runs inside the spinner, so it covers both login and the command's
    network calls. Commands must therefore render their output after the block.
    """
    Path(creds).parent.mkdir(parents=True, exist_ok=True)  # ensure a custom --creds folder exists
    try:
        # spinner on stderr so it never lands in piped stdout (e.g. `show --json | ...`)
        with Console(stderr=True).status(status, spinner="dots2"):
            yield load_client(creds)
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(str(e))


def _member(tri: Tricount, name: str) -> Member:
    m = tri.get_member_by_name(name)
    if not m:
        names = ", ".join(x.display_name for x in tri.members)
        raise click.ClickException(f"No member named {name!r}. Members: {names}")
    return m


def _amount(value: float, currency: str) -> str:
    """Signed amount, green when positive, red when negative."""
    color = "green" if value >= 0 else "red"
    return f"[{color}]{value:,.2f} {currency}[/{color}]"


def _print_balances(api: TricountAPI, tri: Tricount) -> None:
    root = Tree("[bold]Balances[/bold] [dim](positive = is owed money)[/dim]", guide_style="dim")
    for name, value in api.get_balances(tri).items():
        root.add(f"{name}: {_amount(value, tri.currency)}")
    console.print(root)


def _tricount_tree(api: TricountAPI, tri: Tricount) -> None:
    archived = " [yellow]archived[/yellow]" if tri.is_archived else ""
    root = Tree(f"[bold]{tri.title}[/bold] [dim]· {tri.currency} · id {tri.id}[/dim]{archived}",
                guide_style="dim")
    if tri.linked_member:
        root.add(f"[dim]you are[/dim] [bold]{tri.linked_member.display_name}[/bold]")
    txs = root.add(f"[bold]Transactions[/bold] [dim]· {len(tri.transactions)}[/dim]")
    for tx in tri.transactions:
        payer = tri.get_member_by_uuid(tx.membership_uuid_owner)
        payer_name = payer.display_name if payer else "?"
        txs.add(f"[dim][{tx.id}] {tx.date[:10]}[/dim] {tx.description} — "
                f"{_amount(tx.amount.as_float, tx.amount.currency)} [dim]by {payer_name}[/dim]")
    bal = root.add("[bold]Balances[/bold] [dim](positive = is owed money)[/dim]")
    for name, value in api.get_balances(tri).items():
        bal.add(f"{name}: {_amount(value, tri.currency)}")
    console.print(root)


if __name__ == "__main__":
    cli()
