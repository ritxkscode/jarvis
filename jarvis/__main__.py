"""Jarvis - Personal AI Butler main entry point."""

import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from loguru import logger

from .config.settings import get_settings, reload_settings
from .config.secrets import get_secrets_manager
from .core.plugin import PluginManager
from .core.events import EventBus
from .core.agent import JarvisAgent, TaskExecutor, Task, TaskResult
from .integrations import (
    GmailPlugin,
    CalendarPlugin,
    FilesPlugin,
    GitHubPlugin,
    FinancePlugin,
    AppControlPlugin,
    RemindersPlugin,
)
from .bridge import run_bridge, BridgeConfig


class EmailAnalyzerExecutor(TaskExecutor):
    """Executor for AI-powered email analysis."""

    def can_handle(self, task: Task) -> bool:
        return task.plugin == "agent" and task.action == "analyze"

    async def execute(self, task: Task) -> TaskResult:
        prompt = task.params.get("prompt", "")
        if not prompt:
            return TaskResult(task_id=task.id, success=False, error="No prompt provided")

        try:
            # Use a simple LLM call - for now, we'll use a mock or fallback
            # In production, this would call an actual LLM
            # For now, return structured analysis based on keywords
            analysis = self._analyze_with_keywords(prompt)
            return TaskResult(task_id=task.id, success=True, data=json.dumps(analysis))
        except Exception as e:
            return TaskResult(task_id=task.id, success=False, error=str(e))

    def _analyze_with_keywords(self, prompt: str) -> list[dict]:
        """Fallback keyword-based analysis (replace with real LLM later)."""
        # Extract emails from prompt
        emails = []
        current = {}
        for line in prompt.split("\n"):
            line = line.strip()
            if line.startswith("Email "):
                if current:
                    emails.append(current)
                current = {"index": len(emails) + 1}
            elif line.startswith("From:") and current:
                current["from"] = line[5:].strip()
            elif line.startswith("Subject:") and current:
                current["subject"] = line[8:].strip()
            elif line.startswith("Date:") and current:
                current["date"] = line[5:].strip()
            elif line.startswith("Body:") and current:
                current["body"] = line[5:].strip()
        if current:
            emails.append(current)

        results = []
        for e in emails:
            subject = e.get("subject", "").lower()
            body = e.get("body", "").lower()
            from_addr = e.get("from", "").lower()

            # Assignment detection
            if any(kw in subject + body for kw in ["assignment", "homework", "hw", "project", "due", "submit"]):
                # Try to extract due date
                import re
                due_match = re.search(r"due[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2})", subject + body)
                due_date = due_match.group(1) if due_match else None

                # Try to extract course
                course = None
                for kw in ["cs", "math", "bio", "chem", "phys", "eng", "hist", "econ"]:
                    if kw in subject.lower():
                        course = kw.upper()
                        break

                results.append({
                    "email_index": e["index"],
                    "type": "assignment",
                    "title": e.get("subject", "Assignment"),
                    "description": "Assignment or homework detected",
                    "due_date": due_date,
                    "course": course,
                    "priority": "high",
                    "action_items": ["Review requirements", "Start work", "Submit before deadline"],
                })
            # Meeting detection
            elif any(kw in subject + body for kw in ["meeting", "call", "zoom", "teams", "schedule"]):
                results.append({
                    "email_index": e["index"],
                    "type": "meeting",
                    "title": e.get("subject", "Meeting"),
                    "description": "Meeting or call invitation",
                    "due_date": None,
                    "course": None,
                    "priority": "medium",
                    "action_items": ["Check calendar", "Accept/decline", "Prepare"],
                })
            # Action required
            elif any(kw in subject + body for kw in ["action required", "please review", "approval needed", "respond"]):
                results.append({
                    "email_index": e["index"],
                    "type": "action_required",
                    "title": e.get("subject", "Action Required"),
                    "description": "Email requires response or action",
                    "due_date": None,
                    "course": None,
                    "priority": "high",
                    "action_items": ["Read carefully", "Take required action", "Reply"],
                })

        return results


app = typer.Typer(
    name="jarvis",
    help="🤖 Jarvis - Your Personal AI Butler",
    add_completion=False,
)
console = Console()


class JarvisApp:
    """Main Jarvis application."""

    def __init__(self):
        self.settings = get_settings()
        self.secrets = get_secrets_manager()
        self.event_bus = EventBus()
        self.plugin_manager = PluginManager()
        self.agent = JarvisAgent(self.plugin_manager, self.event_bus)
        self.llm_manager = None
        self._running = False

    async def setup(self) -> None:
        """Initialize all plugins."""
        # Register all built-in plugins
        plugins = [
            GmailPlugin(),
            CalendarPlugin(),
            FilesPlugin(),
            GitHubPlugin(),
            FinancePlugin(),
            AppControlPlugin(),
            RemindersPlugin(),
        ]

        for plugin in plugins:
            self.plugin_manager.register(plugin)

        self.plugin_manager.set_event_bus(self.event_bus)

        # Load plugins with configs
        configs = {
            "files": {"base_path": str(Path.home())},
        }
        await self.plugin_manager.load_all(configs)
        await self.plugin_manager.start_all()

        # Register custom executors
        self.agent.register_executor(EmailAnalyzerExecutor())

        # Start agent
        await self.agent.start(max_concurrent=self.settings.max_concurrent_tasks)

        self._running = True
        logger.info("Jarvis fully initialized")

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down Jarvis...")
        self._running = False
        await self.agent.stop()
        await self.plugin_manager.stop_all()
        if self.llm_manager:
            await self.llm_manager.close()
        logger.info("Jarvis shutdown complete")

    def print_status(self) -> None:
        """Print current status."""
        table = Table(title="🤖 Jarvis Status")
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Details")

        # Plugins
        for meta in self.plugin_manager.list_plugins():
            status = self.plugin_manager.get_status(meta.name)
            table.add_row(f"Plugin: {meta.name}", status.value, meta.description)

        # Agent stats
        stats = self.agent.get_stats()
        table.add_row("Agent Queue", str(stats["queue_size"]), f"Running: {stats['running_tasks']}")

        console.print(table)


jarvis_app = JarvisApp()


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config"),
):
    """Initialize Jarvis configuration and directories."""
    settings = get_settings()

    console.print(Panel.fit(
        "[bold]🤖 Jarvis Initialization[/bold]\n"
        f"Data directory: {settings.data_dir}\n"
        f"Logs directory: {settings.logs_dir}\n"
        f"Plugins directory: {settings.plugins_dir}",
        title="Setup",
    ))

    # Create example .env
    env_path = Path.cwd() / ".env.example"
    if not env_path.exists() or force:
        env_content = """# Jarvis Configuration
# Copy to .env and fill in your values

# Google OAuth (for Gmail + Calendar)
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_PROJECT_ID=your_project_id

# GitHub
GITHUB_TOKEN=ghp_xxxxxxxxxxxx

# Plaid (for finance/bank sync)
PLAID_CLIENT_ID=your_plaid_client_id
PLAID_SECRET=your_plaid_secret
PLAID_ENV=sandbox

# Secrets encryption password
JARVIS_SECRETS_PASSWORD=your_strong_password_here

# Optional: Default settings
JARVIS_DEBUG=false
JARVIS_LOG_LEVEL=INFO
JARVIS_TIMEZONE=America/New_York
"""
        env_path.write_text(env_content)
        console.print(f"[green]Created[/green] {env_path}")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("1. Copy .env.example to .env and fill in your credentials")
    console.print("2. Run [cyan]jarvis setup-oauth[/cyan] to configure Google accounts")
    console.print("3. Run [cyan]jarvis start[/cyan] to start Jarvis")


@app.command()
def setup_oauth():
    """Set up Google OAuth for Gmail and Calendar."""
    async def _setup():
        await jarvis_app.setup()

        gmail = jarvis_app.plugin_manager.get_plugin("gmail")
        if not gmail:
            console.print("[red]Gmail plugin not loaded[/red]")
            return

        settings = get_settings()
        secrets = get_secrets_manager()

        oauth = secrets.get_google_oauth()
        if not oauth:
            console.print("[yellow]No Google OAuth credentials found.[/yellow]")
            client_id = typer.prompt("Google Client ID")
            client_secret = typer.prompt("Google Client Secret", hide_input=True)
            project_id = typer.prompt("Google Project ID")
            secrets.set_google_oauth(client_id, client_secret, project_id)
            console.print("[green]OAuth credentials saved[/green]")
        else:
            client_id = oauth["client_id"]
            client_secret = oauth["client_secret"]
            project_id = oauth["project_id"]

        console.print("\n[bold]Adding Gmail accounts...[/bold]")
        while True:
            email = typer.prompt("Gmail address to add (or press Enter to finish)")
            if not email:
                break
            try:
                added = await gmail.setup_oauth(client_id, client_secret, project_id)
                console.print(f"[green]Added:[/green] {added}")
            except Exception as e:
                console.print(f"[red]Failed to add {email}:[/red] {e}")

        await jarvis_app.shutdown()

    asyncio.run(_setup())


@app.command()
def start(
    daemon: bool = typer.Option(False, "--daemon", "-d", help="Run as daemon"),
):
    """Start Jarvis."""
    async def _start():
        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(jarvis_app.shutdown()))

        await jarvis_app.setup()
        jarvis_app.print_status()

        console.print("\n[green]🤖 Jarvis is running![/green]")
        console.print("Press Ctrl+C to stop\n")

        if daemon:
            # Keep running
            while jarvis_app._running:
                await asyncio.sleep(1)
        else:
            # Interactive mode
            await _interactive_loop()

    asyncio.run(_start())


@app.command()
def secrets(
    action: str = typer.Argument(..., help="Action: set, get, delete, list"),
    key: str = typer.Argument(None, help="Secret key"),
    value: str = typer.Argument(None, help="Secret value (for set)"),
):
    """Manage encrypted secrets."""
    secrets_mgr = get_secrets_manager()

    if action == "set":
        if not key or not value:
            console.print("[red]Usage: jarvis secrets set <key> <value>[/red]")
            return
        secrets_mgr.set(key, value)
        console.print(f"[green]Set secret:[/green] {key}")

    elif action == "get":
        if not key:
            console.print("[red]Usage: jarvis secrets get <key>[/red]")
            return
        val = secrets_mgr.get(key)
        if val:
            console.print(val)
        else:
            console.print(f"[yellow]Secret not found:[/yellow] {key}")

    elif action == "delete":
        if not key:
            console.print("[red]Usage: jarvis secrets delete <key>[/red]")
            return
        if secrets_mgr.delete(key):
            console.print(f"[green]Deleted:[/green] {key}")
        else:
            console.print(f"[yellow]Not found:[/yellow] {key}")

    elif action == "list":
        keys = secrets_mgr.list_keys()
        if keys:
            console.print("Secrets:")
            for k in keys:
                console.print(f"  {k}")
        else:
            console.print("[yellow]No secrets stored[/yellow]")

    else:
        console.print(f"[red]Unknown action:[/red] {action}. Use: set, get, delete, list")


async def _interactive_loop():
    """Interactive command loop."""
    from rich.prompt import Prompt

    console.print("[dim]Type 'help' for commands, 'exit' to quit[/dim]")

    while jarvis_app._running:
        try:
            cmd = await asyncio.to_thread(Prompt.ask, "\n[bold cyan]jarvis>[/bold cyan]")
            await _handle_command(cmd.strip())
        except (KeyboardInterrupt, EOFError):
            break
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")

    await jarvis_app.shutdown()


async def _handle_command(cmd: str):
    """Handle interactive command."""
    parts = cmd.split()
    if not parts:
        return

    command = parts[0].lower()
    args = parts[1:]

    if command in ("exit", "quit", "q"):
        await jarvis_app.shutdown()
        return

    if command in ("help", "h", "?"):
        _print_help()
        return

    if command == "status":
        jarvis_app.print_status()
        return

    if command == "plugins":
        _print_plugins()
        return

    if command == "chat":
        await _run_chat_mode(jarvis_app)
        return

    if command == "email":
        await _cmd_email(args)
        return

    if command == "calendar":
        await _cmd_calendar(args)
        return

    if command == "file":
        await _cmd_file(args)
        return

    if command == "github":
        await _cmd_github(args)
        return

    if command == "finance":
        await _cmd_finance(args)
        return

    if command == "app":
        await _cmd_app(args)
        return

    if command == "remind":
        await _cmd_remind(args)
        return

    console.print(f"[red]Unknown command:[/red] {command}. Type 'help' for commands.")


def _print_help():
    console.print(Panel.fit(
        "[bold]Jarvis Commands[/bold]\n\n"
        "[cyan]General:[/cyan]\n"
        "  help, h, ?     Show this help\n"
        "  status         Show system status\n"
        "  plugins        List loaded plugins\n"
        "  chat           Start conversational mode (talk naturally!)\n"
        "  exit, quit, q  Exit Jarvis\n\n"
        "[cyan]Email:[/cyan]\n"
        "  email list [account] [query]     List emails\n"
        "  email send <account> <to> <subject> <body>  Send email\n"
        "  email search <query>             Search all emails\n"
        "  email analyze [account] [query] [max]  AI analyze emails\n\n"
        "[cyan]Calendar:[/cyan]\n"
        "  calendar list [account]          List upcoming events\n"
        "  calendar create <account> <title> <start> <end>  Create event\n"
        "  calendar free <account> <date>   Find free slots\n\n"
        "[cyan]Files:[/cyan]\n"
        "  file read <path>                 Read file\n"
        "  file write <path> <content>      Write file\n"
        "  file list [path] [pattern]       List files\n"
        "  file search <query> [path]       Search files\n\n"
        "[cyan]GitHub:[/cyan]\n"
        "  github repos [org]               List repositories\n"
        "  github create-repo <name>        Create repository\n"
        "  github readme <repo> <title>     Create README\n"
        "  github push <path> <repo>        Push local repo\n\n"
        "[cyan]Finance:[/cyan]\n"
        "  finance sync                     Sync bank transactions\n"
        "  finance add <amount> <desc> <cat>  Add transaction\n"
        "  finance summary                  Spending summary\n"
        "  finance budget <cat> <amount>    Set budget\n\n"
        "[cyan]Apps:[/cyan]\n"
        "  app launch <name>                Launch app\n"
        "  app quit <name>                  Quit app\n"
        "  app type <text> [app]            Type text\n"
        "  app click <x> <y> [app]          Click coordinates\n"
        "  app notify <title> <msg>         Send notification\n\n"
        "[cyan]Reminders:[/cyan]\n"
        "  remind add <title> <msg> <min>   Remind in minutes\n"
        "  remind list                      List reminders\n"
        "  remind assignment <name> <due>   Assignment reminders\n",
        title="🤖 Jarvis Help",
    ))


def _print_plugins():
    table = Table(title="Loaded Plugins")
    table.add_column("Name", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Description")

    for meta in jarvis_app.plugin_manager.list_plugins():
        status = jarvis_app.plugin_manager.get_status(meta.name)
        table.add_row(meta.name, status.value, meta.description)

    console.print(table)


async def _cmd_email(args: list[str]):
    gmail = jarvis_app.plugin_manager.get_plugin("gmail")
    if not gmail:
        console.print("[red]Gmail plugin not loaded[/red]")
        return

    if not args:
        console.print("Usage: email list|send|search ...")
        return

    subcmd = args[0]

    if subcmd == "list":
        account = args[1] if len(args) > 1 else ""
        query = args[2] if len(args) > 2 else ""
        emails = await gmail.list_emails(account=account, query=query, max_results=20)
        _print_emails(emails)

    elif subcmd == "send":
        if len(args) < 5:
            console.print("Usage: email send <account> <to> <subject> <body>")
            return
        _, account, to, subject, *body_parts = args
        body = " ".join(body_parts)
        result = await gmail.send_email(account, to, subject, body)
        console.print(f"[green]Sent:[/green] {result}")

    elif subcmd == "search":
        query = " ".join(args[1:])
        emails = await gmail.search_emails(query)
        _print_emails(emails)

    elif subcmd == "analyze":
        """Analyze emails with AI to find assignments, deadlines, action items."""
        account = args[1] if len(args) > 1 else ""
        query = args[2] if len(args) > 2 else "is:unread"
        max_results = int(args[3]) if len(args) > 3 else 20
        await _analyze_emails(gmail, account, query, max_results)


async def _analyze_emails(gmail, account: str, query: str, max_results: int):
    """Use AI to analyze emails for assignments, deadlines, action items."""
    console.print(f"[cyan]Fetching emails...[/cyan]")
    emails = await gmail.list_emails(account=account, query=query, max_results=max_results)

    if not emails:
        console.print("[yellow]No emails found[/yellow]")
        return

    console.print(f"[cyan]Analyzing {len(emails)} emails...[/cyan]")

    # Use the executor directly (no agent queue needed)
    from jarvis.__main__ import EmailAnalyzerExecutor
    executor = EmailAnalyzerExecutor()

    # Build prompt
    email_summaries = []
    for i, e in enumerate(emails):
        body = e.get("body", "")[:1000]
        email_summaries.append(f"""
Email {i+1}:
From: {e.get('from', '')}
Subject: {e.get('subject', '')}
Date: {e.get('date', '')}
Body: {body}
""")

    prompt = f"""Analyze these {len(emails)} emails and extract actionable items. Return a JSON array where each item has:
- "email_index": which email (1-based)
- "type": "assignment" | "deadline" | "action_required" | "meeting" | "info" | "spam"
- "title": brief title
- "description": what needs to be done
- "due_date": ISO date if mentioned, else null
- "course": course/class if identifiable, else null
- "priority": "high" | "medium" | "low"
- "action_items": list of specific actions needed

Emails:
{"".join(email_summaries)}

Only return the JSON array, no other text."""

    try:
        from jarvis.core.agent import Task
        task = Task(name="analyze", plugin="agent", action="analyze", params={"prompt": prompt})
        result = await executor.execute(task)

        if result.success and result.data:
            import json
            analysis = json.loads(result.data)
            _print_analysis(analysis, emails)
        else:
            console.print("[red]Analysis failed[/red]")
            if result.error:
                console.print(f"Error: {result.error}")

    except Exception as e:
        console.print(f"[red]Analysis error:[/red] {e}")


def _print_analysis(analysis: list[dict], emails: list[dict]):
    """Print email analysis results."""
    if not analysis:
        console.print("[yellow]No actionable items found[/yellow]")
        return

    # Group by type
    by_type = {}
    for item in analysis:
        t = item.get("type", "info")
        by_type.setdefault(t, []).append(item)

    for type_name, items in by_type.items():
        console.print(f"\n[bold {_type_color(type_name)}]{type_name.upper()} ({len(items)})[/bold {_type_color(type_name)}]")
        for item in items:
            idx = item.get("email_index", 0) - 1
            email = emails[idx] if 0 <= idx < len(emails) else {}
            console.print(f"  [cyan]{item.get('title', 'Untitled')}[/cyan]")
            console.print(f"    {item.get('description', '')}")
            if item.get("due_date"):
                console.print(f"    [yellow]Due:[/yellow] {item['due_date']}")
            if item.get("course"):
                console.print(f"    [blue]Course:[/blue] {item['course']}")
            console.print(f"    [dim]Priority: {item.get('priority', 'medium')}[/dim]")
            for action in item.get("action_items", []):
                console.print(f"    • {action}")

            # Offer to create reminder
            if item.get("due_date") and item["type"] in ("assignment", "deadline"):
                console.print(f"    [green]→ Run: remind assignment \"{item['title']}\" {item['due_date']}[/green]")


def _type_color(t: str) -> str:
    colors = {
        "assignment": "red",
        "deadline": "red",
        "action_required": "yellow",
        "meeting": "blue",
        "info": "green",
        "spam": "dim",
    }
    return colors.get(t, "white")


# ============================================================
# Tool Execution Functions (called by LLM)
# ============================================================

async def _execute_list_emails(account: str = "", query: str = "", max_results: int = 20) -> str:
    gmail = jarvis_app.plugin_manager.get_plugin("gmail")
    if not gmail:
        return "Gmail plugin not loaded"
    # Handle string args from LLM
    if isinstance(max_results, str):
        max_results = int(max_results)
    emails = await gmail.list_emails(account=account, query=query, max_results=max_results)
    if not emails:
        return "I checked your emails and found no messages matching that query."
    lines = [f"I found {len(emails)} email(s):"]
    for e in emails[:10]:
        lines.append(f"  • {e.get('subject', 'No subject')[:60]} | From: {e.get('from', '')[:40]} | {e.get('date', '')[:20]}")
    return "\n".join(lines)


async def _execute_analyze_emails(account: str = "", query: str = "is:unread", max_results: int = 20) -> str:
    gmail = jarvis_app.plugin_manager.get_plugin("gmail")
    if not gmail:
        return "Gmail plugin not loaded"
    # Handle string args from LLM
    if isinstance(max_results, str):
        max_results = int(max_results)
    emails = await gmail.list_emails(account=account, query=query, max_results=max_results)
    if not emails:
        return "I checked your emails and found no messages matching that query."

    from jarvis.__main__ import EmailAnalyzerExecutor
    executor = EmailAnalyzerExecutor()

    email_summaries = []
    for i, e in enumerate(emails):
        body = e.get("body", "")[:1000]
        email_summaries.append(f"""
Email {i+1}:
From: {e.get('from', '')}
Subject: {e.get('subject', '')}
Date: {e.get('date', '')}
Body: {body}
""")

    prompt = f"""Analyze these {len(emails)} emails and extract actionable items. Return a JSON array where each item has:
- "email_index": which email (1-based)
- "type": "assignment" | "deadline" | "action_required" | "meeting" | "info" | "spam"
- "title": brief title
- "description": what needs to be done
- "due_date": ISO date if mentioned, else null
- "course": course/class if identifiable, else null
- "priority": "high" | "medium" | "low"
- "action_items": list of specific actions needed

Emails:
{"".join(email_summaries)}

Only return the JSON array, no other text."""

    from jarvis.core.agent import Task
    task = Task(name="analyze", plugin="agent", action="analyze", params={"prompt": prompt})
    result = await executor.execute(task)

    if result.success and result.data:
        import json
        analysis = json.loads(result.data)
        if not analysis:
            return f"I checked {len(emails)} emails but found no actionable items like assignments or deadlines."

        lines = [f"I analyzed {len(emails)} emails and found {len(analysis)} actionable item(s):"]
        for item in analysis:
            idx = item.get("email_index", 1) - 1
            if 0 <= idx < len(emails):
                email = emails[idx]
                from_addr = email.get('from', 'Unknown')
                subject = email.get('subject', 'No subject')
            else:
                from_addr = 'Unknown'
                subject = item.get('title', 'Unknown')

            lines.append(f"\n• {item.get('type', 'item').title()}: {item.get('title', subject)}")
            lines.append(f"  From: {from_addr}")
            if item.get('due_date'):
                lines.append(f"  Due: {item['due_date']}")
            if item.get('course'):
                lines.append(f"  Course: {item['course']}")
            lines.append(f"  Priority: {item.get('priority', 'medium')}")
            if item.get('description'):
                lines.append(f"  Details: {item['description']}")
            if item.get('action_items'):
                lines.append(f"  Suggested actions: {', '.join(item['action_items'])}")

        return "\n".join(lines)
    return "I wasn't able to complete the email analysis."


async def _execute_list_calendar_events(account: str = "", days_ahead: int = 7) -> str:
    cal = jarvis_app.plugin_manager.get_plugin("calendar")
    if not cal:
        return "Calendar plugin not loaded"
    # Handle string args from LLM
    if isinstance(days_ahead, str):
        days_ahead = int(days_ahead)
    from datetime import datetime, timedelta
    events = await cal.list_events(
        account=account,
        time_min=datetime.now(),
        time_max=datetime.now() + timedelta(days=days_ahead),
    )
    if not events:
        return f"I checked your calendar and found no upcoming events in the next {days_ahead} days."
    lines = [f"Here are your upcoming events for the next {days_ahead} days:"]
    for e in events[:10]:
        start = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", ""))
        lines.append(f"  • {e.get('summary', 'No title')} | {start[:16]} | {e.get('account', '')}")
    return "\n".join(lines)


async def _execute_create_calendar_event(account: str, title: str, start_time: str, end_time: str, description: str = "") -> str:
    cal = jarvis_app.plugin_manager.get_plugin("calendar")
    if not cal:
        return "Calendar plugin not loaded"
    from datetime import datetime
    event = await cal.create_event(account, title, datetime.fromisoformat(start_time), datetime.fromisoformat(end_time), description)
    return f"Created event: {event.get('htmlLink', 'OK')}" if event else "Failed to create event"


async def _execute_create_reminder(title: str, message: str, trigger_at: str, priority: str = "normal") -> str:
    rem = jarvis_app.plugin_manager.get_plugin("reminders")
    if not rem:
        return "Reminders plugin not loaded"
    from jarvis.integrations.reminders import ReminderPriority
    from datetime import datetime, timedelta

    # Parse natural language dates
    trigger_at_lower = trigger_at.lower().strip()
    now = datetime.now()

    if trigger_at_lower == "now":
        trigger_dt = now
    elif trigger_at_lower == "tomorrow":
        trigger_dt = now + timedelta(days=1)
    elif trigger_at_lower.startswith("tomorrow at "):
        time_str = trigger_at_lower.replace("tomorrow at ", "")
        try:
            # Parse time like "5pm", "17:00", "5:00pm"
            time_str = time_str.replace("pm", " PM").replace("am", " AM")
            if ":" not in time_str and ("pm" in time_str.lower() or "am" in time_str.lower()):
                time_str = time_str.replace("pm", ":00 PM").replace("am", ":00 AM")
            time_obj = datetime.strptime(time_str.strip(), "%I:%M %p" if ":" in time_str else "%I %p").time()
            trigger_dt = datetime.combine(now + timedelta(days=1), time_obj)
        except:
            trigger_dt = now + timedelta(days=1)
    elif "in " in trigger_at_lower and ("hour" in trigger_at_lower or "hr" in trigger_at_lower):
        # Parse "in X hours"
        import re
        match = re.search(r'in (\d+)\s*(hour|hr)', trigger_at_lower)
        if match:
            hours = int(match.group(1))
            trigger_dt = now + timedelta(hours=hours)
        else:
            trigger_dt = now + timedelta(hours=1)
    else:
        # Try ISO format
        try:
            trigger_dt = datetime.fromisoformat(trigger_at)
        except:
            # Default to tomorrow if parsing fails
            trigger_dt = now + timedelta(days=1)

    pr = ReminderPriority[priority.upper()]
    reminder = await rem.create_reminder(title, message, trigger_dt, priority=pr)
    return f"Reminder set for {trigger_dt.strftime('%Y-%m-%d %H:%M')}: {title}"


async def _execute_list_reminders(hours_ahead: int = 24) -> str:
    rem = jarvis_app.plugin_manager.get_plugin("reminders")
    if not rem:
        return "Reminders plugin not loaded"
    # Handle string args from LLM
    if isinstance(hours_ahead, str):
        hours_ahead = int(hours_ahead)
    reminders = await rem.list_reminders(upcoming_hours=hours_ahead)
    if not reminders:
        return "No upcoming reminders"
    lines = [f"Reminders (next {hours_ahead}h):"]
    for r in reminders:
        lines.append(f"  • {r.title} | {r.trigger_at.strftime('%m/%d %H:%M')} | {r.priority.name}")
    return "\n".join(lines)


async def _execute_list_github_repos(org: str = "") -> str:
    gh = jarvis_app.plugin_manager.get_plugin("github")
    if not gh:
        return "GitHub plugin not loaded"
    repos = await gh.list_repos(org=org if org else None)
    if not repos:
        return "No repositories found"
    lines = [f"Repositories ({len(repos)}):"]
    for r in repos[:15]:
        lines.append(f"  • {r['name']} | {'🔒' if r['private'] else '🌐'} | {r.get('description', '')[:50]}")
    return "\n".join(lines)


async def _execute_create_github_readme(repo: str, title: str, description: str = "") -> str:
    gh = jarvis_app.plugin_manager.get_plugin("github")
    if not gh:
        return "GitHub plugin not loaded"
    result = await gh.create_readme(repo, title, description)
    return f"README created: {result}" if result else "Failed to create README"


async def _execute_run_app_command(action: str, app: str = "", text: str = "", x: int = 0, y: int = 0, title: str = "", message: str = "", url: str = "", browser: str = "Safari") -> str:
    app_ctrl = jarvis_app.plugin_manager.get_plugin("app_control")
    if not app_ctrl:
        return "App Control plugin not loaded"

    if action == "launch":
        success = await app_ctrl.launch_app(app)
        return f"Launched {app}" if success else f"Failed to launch {app}"
    elif action == "quit":
        success = await app_ctrl.quit_app(app)
        return f"Quit {app}" if success else f"Failed to quit {app}"
    elif action == "type":
        success = await app_ctrl.type_text(text, app)
        return f"Typed in {app}" if success else f"Failed to type"
    elif action == "click":
        success = await app_ctrl.click_at(x, y, app)
        return f"Clicked at ({x},{y})" if success else "Failed to click"
    elif action == "notify":
        success = await app_ctrl.send_notification(title, message)
        return "Notification sent" if success else "Failed to send notification"
    elif action == "open_url":
        success = await app_ctrl.open_url(url, browser)
        return f"Opened {url} in {browser}" if success else f"Failed to open URL"
    return f"Unknown action: {action}"


async def _execute_search_files(query: str, path: str = "~") -> str:
    files = jarvis_app.plugin_manager.get_plugin("files")
    if not files:
        return "Files plugin not loaded"
    results = await files.search_files(query, path)
    if not results:
        return f"No files found for '{query}'"
    lines = [f"Found {len(results)} files:"]
    for f in results[:10]:
        lines.append(f"  • {f['path']}")
    return "\n".join(lines)


async def _execute_read_file(path: str) -> str:
    files = jarvis_app.plugin_manager.get_plugin("files")
    if not files:
        return "Files plugin not loaded"
    try:
        content = await files.read_file(path)
        return content[:3000] + ("..." if len(content) > 3000 else "")
    except Exception as e:
        return f"Error reading file: {e}"


async def _execute_write_file(path: str, content: str) -> str:
    files = jarvis_app.plugin_manager.get_plugin("files")
    if not files:
        return "Files plugin not loaded"
    try:
        await files.write_file(path, content)
        return f"Written to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


# Tool dispatch map
TOOL_FUNCTIONS = {
    "list_emails": _execute_list_emails,
    "analyze_emails": _execute_analyze_emails,
    "list_calendar_events": _execute_list_calendar_events,
    "create_calendar_event": _execute_create_calendar_event,
    "create_reminder": _execute_create_reminder,
    "list_reminders": _execute_list_reminders,
    "list_github_repos": _execute_list_github_repos,
    "create_github_readme": _execute_create_github_readme,
    "run_app_command": _execute_run_app_command,
    "search_files": _execute_search_files,
    "read_file": _execute_read_file,
    "write_file": _execute_write_file,
}


async def _execute_tool_call(name: str, args: dict) -> str:
    """Execute a tool call and return result."""
    func = TOOL_FUNCTIONS.get(name)
    if not func:
        return f"Unknown tool: {name}"
    try:
        return await func(**args)
    except Exception as e:
        return f"Error executing {name}: {e}"


# ============================================================
# Conversational Chat Mode
# ============================================================

async def _run_chat_mode(app: 'JarvisApp'):
    """Run conversational chat mode with LLM."""
    from jarvis.integrations.llm import create_llm_manager, LLMMessage, JARVIS_TOOLS

    console.print(Panel.fit(
        "[bold]🤖 Jarvis Chat Mode[/bold]\n"
        "Talk to me naturally! Examples:\n"
        "  • \"Check my emails for assignments\"\n"
        "  • \"What's on my calendar this week?\"\n"
        "  • \"Create a reminder for my CS101 homework due Friday\"\n"
        "  • \"Search for files about machine learning\"\n"
        "  • \"Open Safari and go to github.com\"\n"
        "Type 'exit' or 'quit' to leave chat mode.",
        title="Chat Mode",
    ))

    llm_manager = create_llm_manager()
    app.llm_manager = llm_manager

    if not llm_manager.default_provider:
        console.print("[yellow]No LLM provider configured. Add OPENAI_API_KEY or ANTHROPIC_API_KEY to .env, or run Ollama locally.[/yellow]")
        console.print("[dim]Falling back to keyword-based mode...[/dim]")
        await _run_keyword_chat_mode()
        return

    # System prompt
    system_prompt = """You are Jarvis, a helpful personal AI assistant. You have access to tools for:
- Email (Gmail): list, search, analyze for assignments/deadlines
- Calendar: list events, create events
- Reminders: create, list
- GitHub: list repos, create READMEs
- macOS Apps: launch, quit, type, click, notify, open_url
- Files: search, read, write

CRITICAL RULES:
1. ALWAYS use tools when the user asks you to do something - never make up answers
2. After a tool returns a result, YOU MUST use that exact result in your response - do not hallucinate or invent information
3. The tool results contain the REAL data - read them carefully and report them accurately
4. If a tool says "No emails found" or returns specific data, that is the truth - do not make up fake emails, assignments, or people
5. Be conversational but factual - only report what the tools actually returned

DATE FORMAT REQUIREMENTS:
- For create_calendar_event: Use ISO 8601 format: "2024-01-15T10:00:00"
- For create_reminder trigger_at: Use ISO 8601 format: "2024-01-15T17:00:00"
- For list_calendar_events days_ahead: Use integer (e.g., 7)

When analyzing emails, use the analyze_emails tool for smart extraction of assignments, deadlines, action items.
Always confirm before taking destructive actions (sending emails, deleting, etc.)."""

    llm_manager.add_system_prompt(system_prompt)

    console.print(f"[dim]Using: {llm_manager.get_provider().get_model_name()}[/dim]\n")

    llm_failed = False

    while True:
        try:
            user_input = await asyncio.to_thread(
                lambda: console.input("[bold cyan]you>[/bold cyan] ")
            )
            user_input = user_input.strip()

            if user_input.lower() in ("exit", "quit", "bye"):
                console.print("[dim]Goodbye![/dim]")
                break

            if not user_input:
                continue

            # If LLM previously failed, fall back to keyword mode
            if llm_failed:
                console.print("[yellow]LLM unavailable, switching to keyword mode...[/yellow]")
                await _run_keyword_chat_mode()
                return

            # Add user message
            llm_manager.add_user_message(user_input)

            # Get LLM response (for tool selection only)
            try:
                response = await llm_manager.chat(
                    llm_manager.get_history(),
                    tools=JARVIS_TOOLS,
                )

                # Handle tool calls
                if response.tool_calls:
                    llm_manager.add_assistant_message(response.content or "", response.tool_calls)

                    for tc in response.tool_calls:
                        fn_name = tc["function"]["name"]
                        fn_args = json.loads(tc["function"]["arguments"])

                        console.print(f"[dim]🔧 Calling {fn_name}({fn_args})...[/dim]")
                        result = await _execute_tool_call(fn_name, fn_args)
                        console.print(f"[dim]   → {result[:200]}[/dim]")

                        # Add tool result to conversation for context
                        llm_manager.add_tool_result(tc["id"], result)

                        # Print tool result directly (no second LLM call to avoid hallucination)
                        console.print(f"[bold green]jarvis>[/bold green] {result}")

                        # Add a summary to conversation so LLM knows what happened
                        summary = f"[Tool {fn_name} executed with result: {result[:100]}]"
                        llm_manager.add_assistant_message(summary)

                elif response.content:
                    # No tool needed, just respond
                    console.print(f"[bold green]jarvis>[/bold green] {response.content}")
                    llm_manager.add_assistant_message(response.content)

            except Exception as e:
                console.print(f"[red]LLM Error: {e}[/red]")
                console.print("[yellow]Falling back to keyword mode...[/yellow]")
                llm_failed = True

        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


async def _run_keyword_chat_mode():
    """Fallback keyword-based chat mode without LLM."""
    console.print("[dim]Keyword mode: I understand simple commands. Try: 'emails', 'calendar', 'remind me to...', 'search files for...'[/dim]")

    while True:
        try:
            user_input = await asyncio.to_thread(
                lambda: console.input("[bold cyan]you>[/bold cyan] ")
            )
            user_input = user_input.strip().lower()

            if user_input in ("exit", "quit", "bye"):
                break

            if not user_input:
                continue

            # Simple keyword matching
            if any(kw in user_input for kw in ["email", "mail", "inbox"]):
                if "analyze" in user_input or "assignment" in user_input:
                    result = await _execute_analyze_emails()
                else:
                    result = await _execute_list_emails()
                console.print(f"[green]jarvis>[/green] {result}")

            elif any(kw in user_input for kw in ["calendar", "schedule", "event", "meeting"]):
                result = await _execute_list_calendar_events()
                console.print(f"[green]jarvis>[/green] {result}")

            elif any(kw in user_input for kw in ["remind", "reminder"]):
                result = await _execute_list_reminders()
                console.print(f"[green]jarvis>[/green] {result}")

            elif any(kw in user_input for kw in ["github", "repo", "repository"]):
                result = await _execute_list_github_repos()
                console.print(f"[green]jarvis>[/green] {result}")

            elif any(kw in user_input for kw in ["file", "search", "find"]):
                # Extract query after "for" or "search"
                query = user_input
                for prefix in ["search files for", "find files for", "search for", "find "]:
                    if prefix in query:
                        query = query.split(prefix)[-1].strip()
                        break
                result = await _execute_search_files(query)
                console.print(f"[green]jarvis>[/green] {result}")

            elif any(kw in user_input for kw in ["open", "launch", "start"]):
                for app_name in ["safari", "chrome", "firefox", "terminal", "vscode", "cursor", "finder", "notes", "mail", "calendar"]:
                    if app_name in user_input:
                        result = await _execute_run_app_command("launch", app_name)
                        console.print(f"[green]jarvis>[/green] {result}")
                        break
                else:
                    console.print("[green]jarvis>[/green] Which app should I open?")

            elif "notify" in user_input or "notification" in user_input:
                result = await _execute_run_app_command("notify", title="Jarvis", message="Hello from your butler!")
                console.print(f"[green]jarvis>[/green] {result}")

            else:
                console.print("[green]jarvis>[/green] I'm not sure what you mean. Try: emails, calendar, reminders, github, search files, open Safari, etc.")

        except (KeyboardInterrupt, EOFError):
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


def _print_emails(emails: list[dict]):
    if not emails:
        console.print("[yellow]No emails found[/yellow]")
        return

    table = Table(title="Emails")
    table.add_column("From", style="cyan")
    table.add_column("Subject", style="white")
    table.add_column("Date", style="dim")
    table.add_column("Account", style="green")
    table.add_column("Snippet", style="dim")

    for e in emails[:20]:
        table.add_row(
            e.get("from", "")[:40],
            e.get("subject", "")[:50],
            e.get("date", "")[:20],
            e.get("account", ""),
            e.get("snippet", "")[:60],
        )
    console.print(table)


async def _cmd_calendar(args: list[str]):
    cal = jarvis_app.plugin_manager.get_plugin("calendar")
    if not cal:
        console.print("[red]Calendar plugin not loaded[/red]")
        return

    if not args:
        console.print("Usage: calendar list|create|free ...")
        return

    subcmd = args[0]

    if subcmd == "list":
        account = args[1] if len(args) > 1 else ""
        events = await cal.list_events(account=account)
        _print_events(events)

    elif subcmd == "create":
        if len(args) < 5:
            console.print("Usage: calendar create <account> <title> <start> <end>")
            console.print("  datetime format: YYYY-MM-DDTHH:MM")
            return
        _, account, title, start_str, end_str = args[:5]
        start = datetime.fromisoformat(start_str)
        end = datetime.fromisoformat(end_str)
        event = await cal.create_event(account, title, start, end)
        console.print(f"[green]Created:[/green] {event}")

    elif subcmd == "free":
        if len(args) < 3:
            console.print("Usage: calendar free <account> <date> [duration_min]")
            return
        _, account, date_str, *rest = args
        date = datetime.fromisoformat(date_str)
        duration = int(rest[0]) if rest else 60
        slots = await cal.find_free_slots(account, duration, date)
        _print_free_slots(slots)


def _print_events(events: list[dict]):
    if not events:
        console.print("[yellow]No events[/yellow]")
        return

    table = Table(title="Calendar Events")
    table.add_column("Title", style="cyan")
    table.add_column("Start", style="white")
    table.add_column("End", style="white")
    table.add_column("Account", style="green")

    for e in events:
        start = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", ""))
        end = e.get("end", {}).get("dateTime", e.get("end", {}).get("date", ""))
        table.add_row(
            e.get("summary", "No title")[:40],
            start[:16],
            end[:16],
            e.get("account", ""),
        )
    console.print(table)


def _print_free_slots(slots: list[dict]):
    if not slots:
        console.print("[yellow]No free slots[/yellow]")
        return

    table = Table(title="Free Slots")
    table.add_column("Start", style="cyan")
    table.add_column("End", style="white")
    table.add_column("Duration", style="green")

    for s in slots:
        start = s["start"].strftime("%H:%M")
        end = s["end"].strftime("%H:%M")
        dur = int((s["end"] - s["start"]).total_seconds() / 60)
        table.add_row(start, end, f"{dur} min")
    console.print(table)


async def _cmd_file(args: list[str]):
    files = jarvis_app.plugin_manager.get_plugin("files")
    if not files:
        console.print("[red]Files plugin not loaded[/red]")
        return

    if not args:
        console.print("Usage: file read|write|list|search ...")
        return

    subcmd = args[0]

    if subcmd == "read":
        path = args[1] if len(args) > 1 else "."
        content = await files.read_file(path)
        console.print(content[:5000])
        if len(content) > 5000:
            console.print(f"\n[dim]... truncated ({len(content)} chars total)[/dim]")

    elif subcmd == "write":
        if len(args) < 3:
            console.print("Usage: file write <path> <content>")
            return
        path = args[1]
        content = " ".join(args[2:])
        await files.write_file(path, content)
        console.print(f"[green]Written:[/green] {path}")

    elif subcmd == "list":
        path = args[1] if len(args) > 1 else "."
        pattern = args[2] if len(args) > 2 else "*"
        results = await files.list_files(path, pattern)
        _print_file_list(results)

    elif subcmd == "search":
        query = args[1] if len(args) > 1 else ""
        path = args[2] if len(args) > 2 else "."
        results = await files.search_files(query, path)
        _print_file_list(results)


def _print_file_list(files: list[dict]):
    if not files:
        console.print("[yellow]No files[/yellow]")
        return

    table = Table(title="Files")
    table.add_column("Name", style="cyan")
    table.add_column("Path", style="white")
    table.add_column("Size", style="green")
    table.add_column("Modified", style="dim")

    for f in files[:30]:
        size = f"{f['size']:,}" if not f['is_dir'] else "DIR"
        table.add_row(f['name'], f['path'], size, f['modified'][:16])
    console.print(table)


async def _cmd_github(args: list[str]):
    gh = jarvis_app.plugin_manager.get_plugin("github")
    if not gh:
        console.print("[red]GitHub plugin not loaded[/red]")
        return

    if not args:
        console.print("Usage: github repos|create-repo|readme|push ...")
        return

    subcmd = args[0]

    if subcmd == "repos":
        org = args[1] if len(args) > 1 else None
        repos = await gh.list_repos(org=org)
        _print_repos(repos)

    elif subcmd == "create-repo":
        if len(args) < 2:
            console.print("Usage: github create-repo <name> [description]")
            return
        name = args[1]
        desc = args[2] if len(args) > 2 else ""
        repo = await gh.create_repo(name, desc)
        console.print(f"[green]Created:[/green] {repo}")

    elif subcmd == "readme":
        if len(args) < 3:
            console.print("Usage: github readme <repo> <title>")
            return
        repo = args[1]
        title = args[2]
        result = await gh.create_readme(repo, title)
        console.print(f"[green]README created:[/green] {result}")

    elif subcmd == "push":
        if len(args) < 3:
            console.print("Usage: github push <local_path> <repo>")
            return
        path = args[1]
        repo = args[2]
        success = await gh.push_local_repo(path, repo)
        console.print(f"[green]Pushed[/green]" if success else "[red]Push failed[/red]")


def _print_repos(repos: list[dict]):
    if not repos:
        console.print("[yellow]No repositories[/yellow]")
        return

    table = Table(title="GitHub Repositories")
    table.add_column("Name", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Private", style="red")
    table.add_column("Updated", style="dim")
    table.add_column("Language", style="green")

    for r in repos[:20]:
        table.add_row(
            r['name'],
            (r['description'] or '')[:50],
            "🔒" if r['private'] else "🌐",
            r['updated_at'][:10] if r['updated_at'] else '',
            r['language'] or '',
        )
    console.print(table)


async def _cmd_finance(args: list[str]):
    fin = jarvis_app.plugin_manager.get_plugin("finance")
    if not fin:
        console.print("[red]Finance plugin not loaded[/red]")
        return

    if not args:
        console.print("Usage: finance sync|add|summary|budget ...")
        return

    subcmd = args[0]

    if subcmd == "sync":
        txns = await fin.sync_transactions()
        console.print(f"[green]Synced {len(txns)} transactions[/green]")

    elif subcmd == "add":
        if len(args) < 4:
            console.print("Usage: finance add <amount> <description> <category> [type]")
            return
        amount = float(args[1])
        desc = args[2]
        cat = args[3]
        txn_type = args[4] if len(args) > 4 else "expense"
        txn = await fin.add_transaction(amount, desc, cat, type=txn_type)
        console.print(f"[green]Added:[/green] {txn}")

    elif subcmd == "summary":
        summary = await fin.get_spending_summary()
        _print_spending_summary(summary)

    elif subcmd == "budget":
        if len(args) < 3:
            console.print("Usage: finance budget <category> <amount>")
            return
        cat = args[1]
        amount = float(args[2])
        budget = await fin.set_budget(cat, amount)
        console.print(f"[green]Budget set:[/green] {budget}")

    elif subcmd == "check":
        budgets = await fin.check_budgets()
        _print_budgets(budgets)


def _print_spending_summary(summary: dict):
    table = Table(title="Spending Summary")
    table.add_column("Category", style="cyan")
    table.add_column("Amount", style="red", justify="right")

    for cat, amt in sorted(summary["by_category"].items(), key=lambda x: -x[1]):
        table.add_row(cat, f"${amt:,.2f}")

    table.add_row("[bold]Total[/bold]", f"[bold]${summary['total']:,.2f}[/bold]")
    console.print(table)


def _print_budgets(budgets: list[dict]):
    table = Table(title="Budget Status")
    table.add_column("Category", style="cyan")
    table.add_column("Budget", style="white", justify="right")
    table.add_column("Spent", style="red", justify="right")
    table.add_column("Remaining", style="green", justify="right")
    table.add_column("Status", style="yellow")

    for b in budgets:
        status = "🔴 OVER" if b["over_budget"] else "🟢 OK"
        table.add_row(
            b["category"],
            f"${b['budget']:,.2f}",
            f"${b['spent']:,.2f}",
            f"${b['remaining']:,.2f}",
            f"{status} ({b['percent_used']:.0f}%)",
        )
    console.print(table)


async def _cmd_app(args: list[str]):
    app_ctrl = jarvis_app.plugin_manager.get_plugin("app_control")
    if not app_ctrl:
        console.print("[red]App Control plugin not loaded[/red]")
        return

    if not args:
        console.print("Usage: app launch|quit|type|click|notify ...")
        return

    subcmd = args[0]

    if subcmd == "launch":
        name = args[1] if len(args) > 1 else ""
        success = await app_ctrl.launch_app(name)
        console.print(f"[green]Launched[/green]" if success else "[red]Failed[/red]")

    elif subcmd == "quit":
        name = args[1] if len(args) > 1 else ""
        success = await app_ctrl.quit_app(name)
        console.print(f"[green]Quit[/green]" if success else "[red]Failed[/red]")

    elif subcmd == "type":
        if len(args) < 2:
            console.print("Usage: app type <text> [app]")
            return
        text = args[1]
        app_name = args[2] if len(args) > 2 else None
        success = await app_ctrl.type_text(text, app_name)
        console.print(f"[green]Typed[/green]" if success else "[red]Failed[/red]")

    elif subcmd == "click":
        if len(args) < 3:
            console.print("Usage: app click <x> <y> [app]")
            return
        x, y = int(args[1]), int(args[2])
        app_name = args[3] if len(args) > 3 else None
        success = await app_ctrl.click_at(x, y, app_name)
        console.print(f"[green]Clicked[/green]" if success else "[red]Failed[/red]")

    elif subcmd == "notify":
        if len(args) < 3:
            console.print("Usage: app notify <title> <message>")
            return
        title = args[1]
        msg = " ".join(args[2:])
        success = await app_ctrl.send_notification(title, msg)
        console.print(f"[green]Notification sent[/green]" if success else "[red]Failed[/red]")

    elif subcmd == "apps":
        apps = await app_ctrl.get_running_apps()
        table = Table(title="Running Apps")
        table.add_column("Name", style="cyan")
        table.add_column("Bundle ID", style="white")
        table.add_column("PID", style="green")
        for a in apps:
            table.add_row(a.name, a.bundle_id, str(a.pid))
        console.print(table)


async def _cmd_remind(args: list[str]):
    rem = jarvis_app.plugin_manager.get_plugin("reminders")
    if not rem:
        console.print("[red]Reminders plugin not loaded[/red]")
        return

    if not args:
        console.print("Usage: remind add|list|assignment ...")
        return

    subcmd = args[0]

    if subcmd == "add":
        if len(args) < 4:
            console.print("Usage: remind add <title> <message> <minutes>")
            return
        title = args[1]
        msg = args[2]
        minutes = int(args[3])
        reminder = await rem.create_reminder_in(title, msg, minutes=minutes)
        console.print(f"[green]Reminder set for {minutes} min:[/green] {reminder.title}")

    elif subcmd == "list":
        reminders = await rem.list_reminders(upcoming_hours=24)
        _print_reminders(reminders)

    elif subcmd == "assignment":
        if len(args) < 3:
            console.print("Usage: remind assignment <name> <due_datetime> [course]")
            return
        name = args[1]
        due = datetime.fromisoformat(args[2])
        course = args[3] if len(args) > 3 else ""
        reminders = await rem.assignment_reminder(name, due, course)
        console.print(f"[green]Created {len(reminders)} assignment reminders[/green]")

    elif subcmd == "complete":
        rid = args[1] if len(args) > 1 else ""
        await rem.complete_reminder(rid)
        console.print("[green]Completed[/green]")

    elif subcmd == "snooze":
        if len(args) < 2:
            console.print("Usage: remind snooze <id> [minutes]")
            return
        rid = args[1]
        minutes = int(args[2]) if len(args) > 2 else 10
        await rem.snooze_reminder(rid, minutes)
        console.print(f"[green]Snoozed {minutes} min[/green]")


def _print_reminders(reminders: list[Reminder]):
    if not reminders:
        console.print("[yellow]No reminders[/yellow]")
        return

    table = Table(title="Reminders")
    table.add_column("ID", style="dim", width=10)
    table.add_column("Title", style="cyan")
    table.add_column("Trigger", style="white")
    table.add_column("Priority", style="yellow")
    table.add_column("Tags", style="green")

    for r in reminders:
        table.add_row(
            r.id[:8],
            r.title[:30],
            r.trigger_at.strftime("%m/%d %H:%M"),
            r.priority.name,
            ", ".join(r.tags) if r.tags else "",
        )
    console.print(table)


# ============================================================
# Bridge Commands (Voice-first Web UI)
# ============================================================

@app.command()
def bridge(
    writes: bool = typer.Option(False, "--writes", "-w", help="Enable effectful tools (send, delete, etc.)"),
    port: int = typer.Option(8787, "--port", "-p", help="Bridge port"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bridge host"),
    model: str = typer.Option("claude-opus-5", "--model", "-m", help="Claude model"),
    effort: str = typer.Option("medium", "--effort", "-e", help="Reasoning effort"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Debug logging"),
):
    """Start the Jarvis bridge server (WebSocket backend for voice UI)."""
    import os

    # Set environment variables for bridge config
    os.environ["JARVIS_BRIDGE_PORT"] = str(port)
    os.environ["JARVIS_BRIDGE_HOST"] = host
    os.environ["JARVIS_MODEL"] = model
    os.environ["JARVIS_EFFORT"] = effort
    os.environ["JARVIS_ALLOW_WRITES"] = "1" if writes else "0"
    os.environ["JARVIS_DEBUG"] = "1" if debug else "0"

    console.print(Panel.fit(
        f"[bold]🤖 Jarvis Bridge[/bold]\n"
        f"Host: {host}:{port}\n"
        f"Model: {model} · Effort: {effort}\n"
        f"Writes: {'Enabled' if writes else 'Disabled (read-only)'}\n"
        f"Debug: {'On' if debug else 'Off'}",
        title="Starting Bridge",
    ))

    console.print("\n[dim]Frontend: Open http://localhost:5173 in Chrome[/dim]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    async def _run():
        server = await run_bridge()
        # Keep running until shutdown
        while server._running:
            await asyncio.sleep(1)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n[dim]Bridge stopped[/dim]")


@app.command()
def face(
    dev: bool = typer.Option(True, "--dev/--prod", help="Run Vite dev server (True) or serve built files (False)"),
    port: int = typer.Option(5173, "--port", "-p", help="Frontend port"),
):
    """Start the Jarvis frontend (React + Three.js UI)."""
    import subprocess
    import os

    frontend_dir = Path(__file__).parent.parent / "frontend"

    if not frontend_dir.exists():
        console.print("[red]Frontend not found. Run 'jarvis init' to set up.[/red]")
        return

    console.print(Panel.fit(
        f"[bold]🌐 Jarvis Frontend[/bold]\n"
        f"Mode: {'Development (Vite)' if dev else 'Production'}\n"
        f"Port: {port}",
        title="Starting Frontend",
    ))

    env = os.environ.copy()
    env["PORT"] = str(port)

    if dev:
        # Run Vite dev server
        subprocess.run(["npm", "run", "dev"], cwd=frontend_dir, env=env)
    else:
        # Build and serve
        subprocess.run(["npm", "run", "build"], cwd=frontend_dir, env=env)
        # Would serve built files here


@app.command()
def start(
    bridge: bool = typer.Option(False, "--bridge", "-b", help="Start with bridge + frontend"),
    writes: bool = typer.Option(False, "--writes", "-w", help="Enable effectful tools"),
    daemon: bool = typer.Option(False, "--daemon", "-d", help="Run as daemon"),
):
    """Start Jarvis (CLI mode by default, or bridge+frontend with --bridge)."""
    if bridge:
        # Start both bridge and frontend
        os.environ["JARVIS_ALLOW_WRITES"] = "1" if writes else "0"

        console.print(Panel.fit(
            "[bold]🤖 Jarvis Full Stack[/bold]\n"
            f"Bridge: http://127.0.0.1:8787\n"
            f"Frontend: http://localhost:5173\n"
            f"Writes: {'Enabled' if writes else 'Disabled'}",
            title="Starting",
        ))

        # Start bridge in background subprocess
        bridge_env = os.environ.copy()
        bridge_env["JARVIS_BRIDGE_PORT"] = "8787"
        bridge_env["JARVIS_ALLOW_WRITES"] = "1" if writes else "0"
        bridge_proc = subprocess.Popen(
            [sys.executable, "-m", "jarvis", "bridge"],
            env=bridge_env,
        )

        # Start frontend
        frontend_dir = Path(__file__).parent.parent / "frontend"
        if frontend_dir.exists():
            try:
                subprocess.run(["npm", "run", "dev"], cwd=frontend_dir)
            finally:
                bridge_proc.terminate()
                bridge_proc.wait(timeout=5)
        else:
            console.print("[red]Frontend not found. Run 'jarvis init' first.[/red]")
            bridge_proc.terminate()
            bridge_proc.wait(timeout=5)
    else:
        # Original CLI mode
        async def _start():
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(jarvis_app.shutdown()))

            await jarvis_app.setup()
            jarvis_app.print_status()

            console.print("\n[green]🤖 Jarvis is running![/green]")
            console.print("Press Ctrl+C to stop\n")

            if daemon:
                while jarvis_app._running:
                    await asyncio.sleep(1)
            else:
                await _interactive_loop()

        asyncio.run(_start())


if __name__ == "__main__":
    app()