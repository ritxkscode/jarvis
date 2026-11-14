"""Reminders and notifications plugin."""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4
from dataclasses import dataclass, asdict
from enum import Enum

from ..core.plugin import Plugin, PluginMetadata, PluginStatus
from ..core.events import Event
from ..config.settings import get_settings
from loguru import logger


class ReminderPriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


@dataclass
class Reminder:
    """A reminder/notification."""

    id: str
    title: str
    message: str
    trigger_at: datetime  # When to fire
    created_at: datetime
    priority: ReminderPriority = ReminderPriority.NORMAL
    recurring: Optional[str] = None  # cron expression
    tags: list[str] = None
    actions: list[dict] = None  # Buttons/actions
    completed: bool = False
    dismissed: bool = False

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.actions is None:
            self.actions = []


class RemindersPlugin(Plugin):
    """Reminders, notifications, and scheduled tasks."""

    def __init__(self):
        metadata = PluginMetadata(
            name="reminders",
            version="1.0.0",
            description="Reminders, notifications, and scheduled tasks",
            author="Jarvis",
            tags=["reminders", "notifications", "scheduling", "cron"],
            required_permissions=["notifications", "reminders"],
        )
        super().__init__(metadata)
        self._reminders: dict[str, Reminder] = {}
        self._data_file: Path = Path()
        self._scheduler_task: Optional[asyncio.Task] = None
        self._check_interval = 30  # seconds

    async def initialize(self, config: dict[str, Any]) -> None:
        await super().initialize(config)
        settings = get_settings()
        self._data_file = settings.data_dir / "reminders.json"
        await self._load_reminders()
        self.status = PluginStatus.LOADED

    async def start(self) -> None:
        await super().start()
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Reminders plugin started")

    async def stop(self) -> None:
        await super().stop()
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        await self._save_reminders()
        logger.info("Reminders plugin stopped")

    async def _load_reminders(self) -> None:
        if self._data_file.exists():
            content = await asyncio.to_thread(self._data_file.read_text)
            data = json.loads(content)
            for r in data:
                r["trigger_at"] = datetime.fromisoformat(r["trigger_at"])
                r["created_at"] = datetime.fromisoformat(r["created_at"])
                r["priority"] = ReminderPriority(r["priority"])
                reminder = Reminder(**r)
                self._reminders[reminder.id] = reminder

    async def _save_reminders(self) -> None:
        data = []
        for r in self._reminders.values():
            d = asdict(r)
            d["trigger_at"] = r.trigger_at.isoformat()
            d["created_at"] = r.created_at.isoformat()
            d["priority"] = r.priority.value
            data.append(d)
        content = json.dumps(data, indent=2)
        await asyncio.to_thread(self._data_file.write_text, content)

    async def _scheduler_loop(self) -> None:
        """Check for due reminders."""
        while self.status == PluginStatus.RUNNING:
            try:
                await self._check_due_reminders()
            except Exception as e:
                logger.error(f"Reminder scheduler error: {e}")
            await asyncio.sleep(self._check_interval)

    async def _check_due_reminders(self) -> None:
        now = datetime.now()
        due = [
            r for r in self._reminders.values()
            if not r.completed and not r.dismissed and r.trigger_at <= now
        ]

        for reminder in due:
            await self._fire_reminder(reminder)

            if reminder.recurring:
                # Reschedule next occurrence
                from croniter import croniter
                cron = croniter(reminder.recurring, reminder.trigger_at)
                reminder.trigger_at = cron.get_next(datetime)
            else:
                reminder.completed = True

        if due:
            await self._save_reminders()

    async def _fire_reminder(self, reminder: Reminder) -> None:
        """Fire a reminder notification."""
        # Emit event for other plugins
        await self.emit_event(Event(
            type="reminder.fired",
            source="reminders",
            data=asdict(reminder)
        ))

        # Send macOS notification
        try:
            from .app_control import AppControlPlugin
            # We'll use osascript directly
            import subprocess
            script = f'display notification "{reminder.message}" with title "{reminder.title}"'
            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                timeout=5,
            )
        except Exception as e:
            logger.error(f"Failed to show notification: {e}")

        logger.info(f"Fired reminder: {reminder.title}")

    # Action methods
    async def create_reminder(
        self,
        title: str,
        message: str,
        trigger_at: datetime,
        priority: ReminderPriority = ReminderPriority.NORMAL,
        recurring: str = None,
        tags: list[str] = None,
        actions: list[dict] = None,
    ) -> Reminder:
        """Create a new reminder."""
        reminder = Reminder(
            id=str(uuid4()),
            title=title,
            message=message,
            trigger_at=trigger_at,
            created_at=datetime.now(),
            priority=priority,
            recurring=recurring,
            tags=tags or [],
            actions=actions or [],
        )
        self._reminders[reminder.id] = reminder
        await self._save_reminders()
        return reminder

    async def create_reminder_in(
        self,
        title: str,
        message: str,
        minutes: int = 0,
        hours: int = 0,
        days: int = 0,
        **kwargs
    ) -> Reminder:
        """Create reminder relative to now."""
        trigger = datetime.now() + timedelta(minutes=minutes, hours=hours, days=days)
        return await self.create_reminder(title, message, trigger, **kwargs)

    async def get_reminder(self, reminder_id: str) -> Optional[Reminder]:
        """Get a reminder by ID."""
        return self._reminders.get(reminder_id)

    async def list_reminders(
        self,
        include_completed: bool = False,
        include_dismissed: bool = False,
        tags: list[str] = None,
        upcoming_hours: int = None,
    ) -> list[Reminder]:
        """List reminders with filters."""
        results = list(self._reminders.values())

        if not include_completed:
            results = [r for r in results if not r.completed]
        if not include_dismissed:
            results = [r for r in results if not r.dismissed]
        if tags:
            results = [r for r in results if any(t in r.tags for t in tags)]
        if upcoming_hours:
            cutoff = datetime.now() + timedelta(hours=upcoming_hours)
            results = [r for r in results if r.trigger_at <= cutoff]

        # Sort by trigger time
        results.sort(key=lambda r: r.trigger_at)
        return results

    async def update_reminder(self, reminder_id: str, **updates) -> Optional[Reminder]:
        """Update a reminder."""
        reminder = self._reminders.get(reminder_id)
        if not reminder:
            return None

        for key, value in updates.items():
            if hasattr(reminder, key):
                setattr(reminder, key, value)

        await self._save_reminders()
        return reminder

    async def complete_reminder(self, reminder_id: str) -> bool:
        """Mark reminder as completed."""
        reminder = self._reminders.get(reminder_id)
        if reminder:
            reminder.completed = True
            await self._save_reminders()
            return True
        return False

    async def dismiss_reminder(self, reminder_id: str) -> bool:
        """Dismiss a reminder (don't reschedule recurring)."""
        reminder = self._reminders.get(reminder_id)
        if reminder:
            reminder.dismissed = True
            await self._save_reminders()
            return True
        return False

    async def delete_reminder(self, reminder_id: str) -> bool:
        """Delete a reminder."""
        if reminder_id in self._reminders:
            del self._reminders[reminder_id]
            await self._save_reminders()
            return True
        return False

    async def snooze_reminder(self, reminder_id: str, minutes: int = 10) -> bool:
        """Snooze a reminder."""
        reminder = self._reminders.get(reminder_id)
        if reminder:
            reminder.trigger_at = datetime.now() + timedelta(minutes=minutes)
            await self._save_reminders()
            return True
        return False

    # Convenience methods for common patterns
    async def daily_reminder(self, title: str, message: str, time: str, **kwargs) -> Reminder:
        """Create daily recurring reminder (time in HH:MM format)."""
        # Parse time and create cron
        hour, minute = map(int, time.split(":"))
        cron_expr = f"{minute} {hour} * * *"
        return await self.create_reminder(title, message, datetime.now(), recurring=cron_expr, **kwargs)

    async def weekly_reminder(self, title: str, message: str, day: int, time: str, **kwargs) -> Reminder:
        """Create weekly reminder (day 0=Sunday, time HH:MM)."""
        hour, minute = map(int, time.split(":"))
        cron_expr = f"{minute} {hour} * * {day}"
        return await self.create_reminder(title, message, datetime.now(), recurring=cron_expr, **kwargs)

    async def assignment_reminder(
        self,
        assignment_name: str,
        due_date: datetime,
        course: str = "",
        advance_hours: list[int] = None,
    ) -> list[Reminder]:
        """Create multiple reminders for an assignment."""
        advance_hours = advance_hours or [24, 2, 0]  # 1 day, 2 hours, at due
        reminders = []

        for hours_before in advance_hours:
            trigger = due_date - timedelta(hours=hours_before)
            if trigger > datetime.now():
                if hours_before >= 24:
                    msg = f"{assignment_name} due in {hours_before//24} day(s)"
                elif hours_before > 0:
                    msg = f"{assignment_name} due in {hours_before} hour(s)"
                else:
                    msg = f"{assignment_name} is DUE NOW!"

                if course:
                    msg = f"[{course}] {msg}"

                reminder = await self.create_reminder(
                    title=f"Assignment: {assignment_name}",
                    message=msg,
                    trigger_at=trigger,
                    priority=ReminderPriority.HIGH if hours_before <= 2 else ReminderPriority.NORMAL,
                    tags=["assignment", course] if course else ["assignment"],
                )
                reminders.append(reminder)

        return reminders