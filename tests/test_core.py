"""Tests for Jarvis core components."""

import asyncio
import tempfile
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from jarvis.config.settings import Settings, GmailAccountSettings
from jarvis.config.secrets import SecretsManager
from jarvis.core.plugin import Plugin, PluginManager, PluginMetadata, PluginStatus
from jarvis.core.events import EventBus, Event
from jarvis.core.agent import JarvisAgent, Task, TaskStatus, TaskResult


class TestSettings:
    """Test configuration settings."""

    def test_default_settings(self):
        settings = Settings()
        assert settings.data_dir.name == ".jarvis"
        assert settings.log_level == "INFO"
        assert settings.max_concurrent_tasks == 5

    def test_gmail_account_settings(self):
        acc = GmailAccountSettings(email="test@gmail.com")
        assert acc.email == "test@gmail.com"


class TestSecretsManager:
    """Test encrypted secrets management."""

    @pytest.fixture
    def secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secrets.age"
            sm = SecretsManager(secrets_path=path, password="test-password-12345")
            yield sm

    def test_set_get_secret(self, secrets):
        secrets.set("test_key", "test_value")
        assert secrets.get("test_key") == "test_value"

    def test_delete_secret(self, secrets):
        secrets.set("to_delete", "value")
        assert secrets.delete("to_delete") is True
        assert secrets.get("to_delete") is None

    def test_list_keys(self, secrets):
        secrets.set("key1", "val1")
        secrets.set("key2", "val2")
        keys = secrets.list_keys()
        assert "key1" in keys
        assert "key2" in keys


class TestPluginSystem:
    """Test plugin manager and base plugin."""

    class DummyPlugin(Plugin):
        def __init__(self):
            meta = PluginMetadata(name="dummy", description="Test plugin")
            super().__init__(meta)
            self.started = False
            self.stopped = False

        async def initialize(self, config):
            await super().initialize(config)
            self.config = config

        async def start(self):
            await super().start()
            self.started = True

        async def stop(self):
            await super().stop()
            self.stopped = True

    @pytest.fixture
    def plugin_manager(self):
        return PluginManager()

    @pytest.fixture
    def event_bus(self):
        return EventBus()

    @pytest.mark.asyncio
    async def test_register_plugin(self, plugin_manager):
        plugin = self.DummyPlugin()
        plugin_manager.register(plugin)
        assert "dummy" in plugin_manager._plugins

    @pytest.mark.asyncio
    async def test_load_plugin(self, plugin_manager, event_bus):
        plugin_manager.set_event_bus(event_bus)
        plugin = self.DummyPlugin()
        plugin_manager.register(plugin)

        loaded = await plugin_manager.load_plugin("dummy", {"test": "config"})
        assert loaded.status == PluginStatus.LOADED
        assert loaded.config == {"test": "config"}

    @pytest.mark.asyncio
    async def test_start_stop_plugin(self, plugin_manager, event_bus):
        plugin_manager.set_event_bus(event_bus)
        plugin = self.DummyPlugin()
        plugin_manager.register(plugin)
        await plugin_manager.load_plugin("dummy")

        await plugin_manager.start_plugin("dummy")
        assert plugin.started is True
        assert plugin.status == PluginStatus.RUNNING

        await plugin_manager.stop_plugin("dummy")
        assert plugin.stopped is True
        assert plugin.status == PluginStatus.STOPPED


class TestEventBus:
    """Test event bus."""

    @pytest.mark.asyncio
    async def test_emit_subscribe(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("test.event", handler)
        await bus.emit(Event(type="test.event", source="test", data={"foo": "bar"}))

        assert len(received) == 1
        assert received[0].data["foo"] == "bar"

    @pytest.mark.asyncio
    async def test_wildcard_subscribe(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe_all(handler)
        await bus.emit(Event(type="any.event", source="test"))

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_history(self):
        bus = EventBus()
        await bus.emit(Event(type="hist.test", source="test", data={"n": 1}))
        await bus.emit(Event(type="hist.test", source="test", data={"n": 2}))

        history = bus.get_history("hist.test")
        assert len(history) == 2
        assert history[0].data["n"] == 1


class TestAgent:
    """Test task agent."""

    class MockExecutor:
        def can_handle(self, task):
            return task.plugin == "test"

        async def execute(self, task):
            return TaskResult(task_id=task.id, success=True, data={"result": "ok"})

    @pytest.fixture
    def agent(self):
        pm = MagicMock()
        pm._plugins = {"test": MagicMock()}
        eb = EventBus()
        return JarvisAgent(pm, eb)

    @pytest.mark.asyncio
    async def test_submit_task(self, agent):
        agent.register_executor(self.MockExecutor())

        task = Task(name="test", plugin="test", action="do_thing")
        task_id = await agent.submit_task(task)

        assert task_id == task.id
        assert agent._task_queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_submit_and_wait(self, agent):
        agent.register_executor(self.MockExecutor())
        await agent.start(max_concurrent=1)

        task = Task(name="test", plugin="test", action="do_thing")
        result = await agent.submit_and_wait(task, timeout=5)

        assert result.success is True
        assert result.data["result"] == "ok"

        await agent.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])