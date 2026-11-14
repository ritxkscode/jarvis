"""Core Jarvis agent with task execution."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4
import asyncio
from loguru import logger


class TaskStatus(Enum):
    """Task execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """A task for Jarvis to execute."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    plugin: str = ""  # Which plugin should handle this
    action: str = ""  # Action/method to call
    params: dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # Higher = more urgent
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Any = None
    error: Optional[str] = None
    requires_approval: bool = False
    approved: bool = False


@dataclass
class TaskResult:
    """Result of task execution."""

    task_id: str
    success: bool
    data: Any = None
    error: Optional[str] = None
    duration_ms: float = 0


class TaskExecutor(ABC):
    """Abstract task executor."""

    @abstractmethod
    async def execute(self, task: Task) -> TaskResult:
        """Execute a task and return result."""
        pass

    @abstractmethod
    def can_handle(self, task: Task) -> bool:
        """Check if this executor can handle the task."""
        pass


class JarvisAgent:
    """Main Jarvis agent coordinating plugins and tasks."""

    def __init__(self, plugin_manager: "PluginManager", event_bus: "EventBus"):
        self.plugin_manager = plugin_manager
        self.event_bus = event_bus
        self._executors: dict[str, TaskExecutor] = {}
        self._task_queue: asyncio.PriorityQueue[Task] = asyncio.PriorityQueue()
        self._running_tasks: dict[str, Task] = {}
        self._completed_tasks: dict[str, TaskResult] = {}
        self._worker_tasks: list[asyncio.Task] = []
        self._running = False
        self._max_concurrent = 5

    def register_executor(self, executor: TaskExecutor) -> None:
        """Register a task executor."""
        # Use plugin name as key
        for plugin_name in self.plugin_manager._plugins:
            if executor.can_handle(Task(plugin=plugin_name, action="test")):
                self._executors[plugin_name] = executor
                break

    async def start(self, max_concurrent: int = 5) -> None:
        """Start the agent workers."""
        self._running = True
        self._max_concurrent = max_concurrent
        for i in range(max_concurrent):
            task = asyncio.create_task(self._worker(f"worker-{i}"))
            self._worker_tasks.append(task)
        logger.info(f"Jarvis agent started with {max_concurrent} workers")

    async def stop(self) -> None:
        """Stop the agent."""
        self._running = False
        # Cancel workers
        for task in self._worker_tasks:
            task.cancel()
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()
        logger.info("Jarvis agent stopped")

    async def submit_task(self, task: Task) -> str:
        """Submit a task for execution."""
        # Priority queue uses (priority, task), negative priority for max-heap
        await self._task_queue.put((-task.priority, task))
        logger.debug(f"Submitted task: {task.name} ({task.id})")
        return task.id

    async def submit_and_wait(self, task: Task, timeout: float = 300) -> TaskResult:
        """Submit task and wait for completion."""
        task_id = await self.submit_task(task)
        return await self.wait_for_task(task_id, timeout)

    async def wait_for_task(self, task_id: str, timeout: float = 300) -> TaskResult:
        """Wait for a task to complete."""
        start = asyncio.get_event_loop().time()
        while True:
            if task_id in self._completed_tasks:
                return self._completed_tasks.pop(task_id)

            if task_id in self._running_tasks:
                task = self._running_tasks[task_id]
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    result = TaskResult(
                        task_id=task_id,
                        success=task.status == TaskStatus.COMPLETED,
                        data=task.result,
                        error=task.error,
                    )
                    return result

            if asyncio.get_event_loop().time() - start > timeout:
                raise TimeoutError(f"Task {task_id} timed out after {timeout}s")

            await asyncio.sleep(0.1)

    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """Get task status."""
        if task_id in self._running_tasks:
            return self._running_tasks[task_id].status
        if task_id in self._completed_tasks:
            return TaskStatus.COMPLETED if self._completed_tasks[task_id].success else TaskStatus.FAILED
        # Check queue (expensive)
        return TaskStatus.PENDING

    async def _worker(self, name: str) -> None:
        """Worker loop processing tasks."""
        logger.debug(f"Worker {name} started")
        while self._running:
            try:
                # Get next task with timeout
                try:
                    priority, task = await asyncio.wait_for(
                        self._task_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                if task.id in self._running_tasks:
                    continue

                # Check approval
                if task.requires_approval and not task.approved:
                    task.status = TaskStatus.PENDING
                    # Re-queue with lower priority
                    await self._task_queue.put((-task.priority + 1000, task))
                    continue

                # Execute task
                await self._execute_task(task)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {name} error: {e}")
                await asyncio.sleep(1)

        logger.debug(f"Worker {name} stopped")

    async def _execute_task(self, task: Task) -> None:
        """Execute a single task."""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        self._running_tasks[task.id] = task

        logger.info(f"Executing task: {task.name} ({task.id})")

        try:
            # Find executor
            executor = self._executors.get(task.plugin)
            if not executor:
                # Try plugin directly
                plugin = self.plugin_manager.get_plugin(task.plugin)
                if plugin and hasattr(plugin, task.action):
                    method = getattr(plugin, task.action)
                    result = await method(**task.params)
                    task.result = result
                    task.status = TaskStatus.COMPLETED
                else:
                    raise ValueError(f"No executor for plugin {task.plugin} action {task.action}")
            else:
                result = await executor.execute(task)
                task.result = result.data
                task.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
                task.error = result.error

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error(f"Task {task.name} failed: {e}")

        finally:
            task.completed_at = datetime.now()
            self._running_tasks.pop(task.id, None)

            # Store result
            result = TaskResult(
                task_id=task.id,
                success=task.status == TaskStatus.COMPLETED,
                data=task.result,
                error=task.error,
                duration_ms=(task.completed_at - task.started_at).total_seconds() * 1000
                if task.started_at and task.completed_at
                else 0,
            )
            self._completed_tasks[task.id] = result

            # Emit completion event
            await self.event_bus.emit(Event(
                type="task.completed",
                source="agent",
                data={"task_id": task.id, "success": result.success}
            ))

    def get_stats(self) -> dict:
        """Get agent statistics."""
        return {
            "queue_size": self._task_queue.qsize(),
            "running_tasks": len(self._running_tasks),
            "completed_tasks": len(self._completed_tasks),
            "workers": len(self._worker_tasks),
        }