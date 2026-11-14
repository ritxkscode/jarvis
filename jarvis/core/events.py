"""Event bus for inter-plugin communication."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable
from uuid import uuid4
from collections import defaultdict
import asyncio
from loguru import logger


@dataclass
class Event:
    """Event message."""

    type: str
    source: str
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: str | None = None


EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    """Async event bus for plugin communication."""

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._wildcard_handlers: list[EventHandler] = []
        self._history: list[Event] = []
        self._max_history = 1000

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe to an event type."""
        self._handlers[event_type].append(handler)
        logger.debug(f"Subscribed {handler.__name__} to {event_type}")

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to all events."""
        self._wildcard_handlers.append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> bool:
        """Unsubscribe from an event type."""
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
                return True
            except ValueError:
                pass
        return False

    async def emit(self, event: Event) -> None:
        """Emit an event to all subscribers."""
        # Add to history
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Call specific handlers
        handlers = self._handlers.get(event.type, [])
        # Call wildcard handlers
        all_handlers = handlers + self._wildcard_handlers

        if not all_handlers:
            return

        # Execute all handlers concurrently
        await asyncio.gather(
            *[self._safe_call(handler, event) for handler in all_handlers],
            return_exceptions=True
        )

    async def _safe_call(self, handler: EventHandler, event: Event) -> None:
        """Safely call a handler, logging errors."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Event handler {handler.__name__} failed for {event.type}: {e}")

    def get_history(self, event_type: str | None = None, limit: int = 100) -> list[Event]:
        """Get event history."""
        if event_type:
            return [e for e in self._history if e.type == event_type][-limit:]
        return self._history[-limit:]

    def clear_history(self) -> None:
        """Clear event history."""
        self._history.clear()