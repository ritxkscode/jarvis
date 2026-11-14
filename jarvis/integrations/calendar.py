"""Google Calendar integration plugin."""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..core.plugin import Plugin, PluginMetadata, PluginStatus
from ..core.events import Event
from ..config.settings import get_settings
from ..config.secrets import get_secrets_manager
from loguru import logger

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarPlugin(Plugin):
    """Google Calendar integration."""

    def __init__(self):
        metadata = PluginMetadata(
            name="calendar",
            version="1.0.0",
            description="Google Calendar integration (events, reminders, scheduling)",
            author="Jarvis",
            tags=["calendar", "google", "scheduling"],
            required_permissions=["calendar.read", "calendar.write"],
            dependencies=["gmail"],  # Uses same OAuth
        )
        super().__init__(metadata)
        self._services: dict[str, Any] = {}  # email -> service
        self._polling_task: Optional[asyncio.Task] = None
        self._poll_interval = 300  # 5 minutes

    async def initialize(self, config: dict[str, Any]) -> None:
        await super().initialize(config)
        secrets = get_secrets_manager()
        settings = get_settings()

        oauth = secrets.get_google_oauth()
        if not oauth:
            logger.warning("No Google OAuth config. Calendar needs Gmail OAuth first.")
            return

        # Load credentials for each Gmail account
        for acc_config in settings.gmail_accounts:
            email = acc_config.email
            creds_data = secrets.get_gmail_credentials(email)
            if creds_data:
                try:
                    creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
                    if creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                        secrets.set_gmail_credentials(email, json.loads(creds.to_json()))

                    service = build("calendar", "v3", credentials=creds)
                    self._services[email] = service
                    logger.info(f"Loaded Calendar for: {email}")
                except Exception as e:
                    logger.error(f"Failed to load Calendar for {email}: {e}")

        self.status = PluginStatus.LOADED

    async def start(self) -> None:
        await super().start()
        self._polling_task = asyncio.create_task(self._poll_loop())
        logger.info("Calendar plugin started")

    async def stop(self) -> None:
        await super().stop()
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
        logger.info("Calendar plugin stopped")

    async def _poll_loop(self) -> None:
        """Check for upcoming events."""
        while self.status == PluginStatus.RUNNING:
            try:
                await self.check_upcoming_events()
            except Exception as e:
                logger.error(f"Calendar poll error: {e}")
            await asyncio.sleep(self._poll_interval)

    async def check_upcoming_events(self, minutes_ahead: int = 30) -> list[dict]:
        """Check all calendars for upcoming events."""
        now = datetime.utcnow().isoformat() + "Z"
        later = (datetime.utcnow() + timedelta(minutes=minutes_ahead)).isoformat() + "Z"
        all_events = []

        for email, service in self._services.items():
            try:
                events_result = await asyncio.to_thread(
                    service.events().list(
                        calendarId="primary",
                        timeMin=now,
                        timeMax=later,
                        singleEvents=True,
                        orderBy="startTime",
                    ).execute
                )
                events = events_result.get("items", [])
                for event in events:
                    event["account"] = email
                    all_events.append(event)
                    # Emit reminder event
                    await self.emit_event(Event(
                        type="calendar.event_upcoming",
                        source="calendar",
                        data={"account": email, "event": event, "minutes_until": minutes_ahead}
                    ))
            except HttpError as e:
                logger.error(f"Calendar list error for {email}: {e}")

        return all_events

    # Action methods
    async def list_events(
        self,
        account: str = "",
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 50,
    ) -> list[dict]:
        """List calendar events."""
        accounts = {account: self._services.get(account)} if account else self._services
        time_min = time_min or datetime.utcnow()
        time_max = time_max or (time_min + timedelta(days=7))

        results = []
        for email, service in accounts.items():
            if not service:
                continue
            try:
                events_result = await asyncio.to_thread(
                    service.events().list(
                        calendarId="primary",
                        timeMin=time_min.isoformat() + "Z",
                        timeMax=time_max.isoformat() + "Z",
                        maxResults=max_results,
                        singleEvents=True,
                        orderBy="startTime",
                    ).execute
                )
                for event in events_result.get("items", []):
                    event["account"] = email
                    results.append(event)
            except HttpError as e:
                logger.error(f"Calendar list error for {email}: {e}")
        return results

    async def create_event(
        self,
        account: str,
        summary: str,
        start_time: datetime,
        end_time: datetime,
        description: str = "",
        location: str = "",
        attendees: list[str] = None,
        reminders: list[dict] = None,
    ) -> Optional[dict]:
        """Create a calendar event."""
        service = self._services.get(account)
        if not service:
            raise ValueError(f"Account {account} not found")

        event = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "America/New_York",
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "America/New_York",
            },
        }

        if attendees:
            event["attendees"] = [{"email": a} for a in attendees]

        if reminders:
            event["reminders"] = {"useDefault": False, "overrides": reminders}
        else:
            event["reminders"] = {"useDefault": True}

        try:
            created = await asyncio.to_thread(
                service.events().insert(calendarId="primary", body=event).execute
            )
            logger.info(f"Created event: {created.get('htmlLink')}")
            return created
        except HttpError as e:
            logger.error(f"Calendar create error: {e}")
            return None

    async def update_event(
        self,
        account: str,
        event_id: str,
        **updates
    ) -> Optional[dict]:
        """Update an existing event."""
        service = self._services.get(account)
        if not service:
            raise ValueError(f"Account {account} not found")

        try:
            # Get existing event
            event = await asyncio.to_thread(
                service.events().get(calendarId="primary", eventId=event_id).execute
            )
            # Apply updates
            event.update(updates)
            updated = await asyncio.to_thread(
                service.events().update(calendarId="primary", eventId=event_id, body=event).execute
            )
            return updated
        except HttpError as e:
            logger.error(f"Calendar update error: {e}")
            return None

    async def delete_event(self, account: str, event_id: str) -> bool:
        """Delete an event."""
        service = self._services.get(account)
        if not service:
            return False

        try:
            await asyncio.to_thread(
                service.events().delete(calendarId="primary", eventId=event_id).execute
            )
            return True
        except HttpError:
            return False

    async def find_free_slots(
        self,
        account: str,
        duration_minutes: int,
        date: datetime,
        work_hours: tuple = (9, 17),
    ) -> list[dict]:
        """Find free time slots in a day."""
        service = self._services.get(account)
        if not service:
            return []

        day_start = date.replace(hour=work_hours[0], minute=0, second=0)
        day_end = date.replace(hour=work_hours[1], minute=0, second=0)

        try:
            body = {
                "timeMin": day_start.isoformat() + "Z",
                "timeMax": day_end.isoformat() + "Z",
                "items": [{"id": "primary"}],
            }
            freebusy = await asyncio.to_thread(
                service.freebusy().query(body=body).execute
            )
            busy = freebusy["calendars"]["primary"].get("busy", [])

            # Calculate free slots
            slots = []
            current = day_start
            for period in busy:
                busy_start = datetime.fromisoformat(period["start"].replace("Z", "+00:00"))
                busy_end = datetime.fromisoformat(period["end"].replace("Z", "+00:00"))

                if (busy_start - current).total_seconds() >= duration_minutes * 60:
                    slots.append({"start": current, "end": busy_start})
                current = max(current, busy_end)

            # Check after last busy period
            if (day_end - current).total_seconds() >= duration_minutes * 60:
                slots.append({"start": current, "end": day_end})

            return slots
        except HttpError as e:
            logger.error(f"Freebusy error: {e}")
            return []

    def get_calendars(self, account: str) -> list[dict]:
        """List available calendars for an account."""
        service = self._services.get(account)
        if not service:
            return []

        try:
            calendars = service.calendarList().list().execute()
            return calendars.get("items", [])
        except HttpError:
            return []