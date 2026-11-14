"""Plugin system for Jarvis integrations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from enum import Enum
import asyncio
from loguru import logger


class PluginStatus(Enum):
    """Plugin lifecycle status."""

    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class PluginMetadata:
    """Plugin metadata and configuration."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    dependencies: list[str] = field(default_factory=list)
    required_permissions: list[str] = field(default_factory=list)
    config_schema: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


class Plugin(ABC):
    """Base class for all Jarvis plugins."""

    def __init__(self, metadata: PluginMetadata):
        self.metadata = metadata
        self.status = PluginStatus.UNLOADED
        self._config: dict[str, Any] = {}
        self._event_bus = None  # Set by PluginManager

    @property
    def name(self) -> str:
        return self.metadata.name

    @abstractmethod
    async def initialize(self, config: dict[str, Any]) -> None:
        """Initialize plugin with configuration."""
        self._config = config
        self.status = PluginStatus.LOADED

    @abstractmethod
    async def start(self) -> None:
        """Start plugin (begin background tasks, connections)."""
        self.status = PluginStatus.RUNNING

    @abstractmethod
    async def stop(self) -> None:
        """Stop plugin gracefully."""
        self.status = PluginStatus.STOPPED

    async def handle_event(self, event: "Event") -> None:
        """Handle events from the event bus. Override if needed."""
        pass

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get plugin configuration value."""
        return self._config.get(key, default)

    def set_event_bus(self, event_bus: "EventBus") -> None:
        """Set the event bus reference."""
        self._event_bus = event_bus

    async def emit_event(self, event: "Event") -> None:
        """Emit an event to the bus."""
        if self._event_bus:
            await self._event_bus.emit(event)


class PluginManager:
    """Manages plugin lifecycle and dependencies."""

    def __init__(self):
        self._plugins: dict[str, Plugin] = {}
        self._metadata: dict[str, PluginMetadata] = {}
        self._event_bus: "EventBus" = None

    def set_event_bus(self, event_bus: "EventBus") -> None:
        self._event_bus = event_bus

    def register(self, plugin: Plugin) -> None:
        """Register a plugin."""
        if plugin.name in self._plugins:
            raise ValueError(f"Plugin {plugin.name} already registered")
        self._plugins[plugin.name] = plugin
        self._metadata[plugin.name] = plugin.metadata
        logger.debug(f"Registered plugin: {plugin.name}")

    def unregister(self, name: str) -> None:
        """Unregister a plugin."""
        if name in self._plugins:
            del self._plugins[name]
            del self._metadata[name]

    async def load_plugin(self, name: str, config: dict[str, Any] = None) -> Plugin:
        """Load and initialize a plugin."""
        if name not in self._plugins:
            raise ValueError(f"Plugin {name} not registered")

        plugin = self._plugins[name]
        if plugin.status != PluginStatus.UNLOADED:
            logger.warning(f"Plugin {name} already loaded")
            return plugin

        plugin.status = PluginStatus.LOADING
        try:
            await plugin.initialize(config or {})
            if self._event_bus:
                plugin.set_event_bus(self._event_bus)
            logger.info(f"Loaded plugin: {name}")
            return plugin
        except Exception as e:
            plugin.status = PluginStatus.ERROR
            logger.error(f"Failed to load plugin {name}: {e}")
            raise

    async def start_plugin(self, name: str) -> None:
        """Start a loaded plugin."""
        plugin = self._plugins.get(name)
        if not plugin:
            raise ValueError(f"Plugin {name} not found")

        if plugin.status != PluginStatus.LOADED:
            raise ValueError(f"Plugin {name} not loaded (status: {plugin.status})")

        plugin.status = PluginStatus.STARTING
        try:
            await plugin.start()
            logger.info(f"Started plugin: {name}")
        except Exception as e:
            plugin.status = PluginStatus.ERROR
            logger.error(f"Failed to start plugin {name}: {e}")
            raise

    async def stop_plugin(self, name: str) -> None:
        """Stop a running plugin."""
        plugin = self._plugins.get(name)
        if not plugin:
            return

        if plugin.status not in (PluginStatus.RUNNING, PluginStatus.STARTING):
            return

        plugin.status = PluginStatus.STOPPING
        try:
            await plugin.stop()
            logger.info(f"Stopped plugin: {name}")
        except Exception as e:
            plugin.status = PluginStatus.ERROR
            logger.error(f"Error stopping plugin {name}: {e}")

    async def load_all(self, configs: dict[str, dict] = None) -> None:
        """Load all registered plugins respecting dependencies."""
        configs = configs or {}
        # Topological sort by dependencies
        loaded = set()
        to_load = list(self._plugins.keys())

        while to_load:
            progress = False
            for name in to_load[:]:
                plugin = self._plugins[name]
                deps = plugin.metadata.dependencies
                if all(d in loaded for d in deps):
                    await self.load_plugin(name, configs.get(name, {}))
                    loaded.add(name)
                    to_load.remove(name)
                    progress = True

            if not progress:
                remaining = [n for n in to_load if n not in loaded]
                raise RuntimeError(f"Circular dependency or missing plugin: {remaining}")

    async def start_all(self) -> None:
        """Start all loaded plugins."""
        for name, plugin in self._plugins.items():
            if plugin.status == PluginStatus.LOADED:
                await self.start_plugin(name)

    async def stop_all(self) -> None:
        """Stop all plugins in reverse dependency order."""
        # Simple reverse order for now
        for name in reversed(list(self._plugins.keys())):
            await self.stop_plugin(name)

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """Get a plugin by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[PluginMetadata]:
        """List all registered plugin metadata."""
        return list(self._metadata.values())

    def get_status(self, name: str) -> PluginStatus:
        """Get plugin status."""
        plugin = self._plugins.get(name)
        return plugin.status if plugin else PluginStatus.UNLOADED