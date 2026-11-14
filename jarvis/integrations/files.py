"""Local file system operations plugin."""

import asyncio
import os
import shutil
import json
import yaml
from pathlib import Path
from typing import Any, Optional
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from ..core.plugin import Plugin, PluginMetadata, PluginStatus
from ..core.events import Event
from ..config.settings import get_settings
from loguru import logger


class FileWatchHandler(FileSystemEventHandler):
    """Watchdog handler for file events."""

    def __init__(self, plugin: "FilesPlugin"):
        self.plugin = plugin
        self.loop = None

    def set_loop(self, loop):
        self.loop = loop

    def on_any_event(self, event):
        if self.loop and not event.is_directory:
            asyncio.run_coroutine_threadsafe(
                self.plugin.emit_event(Event(
                    type="file.changed",
                    source="files",
                    data={
                        "path": event.src_path,
                        "event_type": event.event_type,
                        "is_directory": event.is_directory,
                    }
                )),
                self.loop
            )


class FilesPlugin(Plugin):
    """Local file system operations."""

    def __init__(self):
        metadata = PluginMetadata(
            name="files",
            version="1.0.0",
            description="Local file operations (read, write, search, watch)",
            author="Jarvis",
            tags=["files", "filesystem", "local"],
            required_permissions=["files.read", "files.write"],
        )
        super().__init__(metadata)
        self._observer: Optional[Observer] = None
        self._watched_paths: set[Path] = set()
        self._base_path: Path = Path.home()

    async def initialize(self, config: dict[str, Any]) -> None:
        await super().initialize(config)
        self._base_path = Path(config.get("base_path", str(Path.home())))
        self.status = PluginStatus.LOADED

    async def start(self) -> None:
        await super().start()
        self._observer = Observer()
        self._observer.start()
        logger.info("Files plugin started")

    async def stop(self) -> None:
        await super().stop()
        if self._observer:
            self._observer.stop()
            self._observer.join()
        logger.info("Files plugin stopped")

    def _resolve_path(self, path: str) -> Path:
        """Resolve path relative to base."""
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self._base_path / p
        return p.resolve()

    # Action methods
    async def read_file(self, path: str, encoding: str = "utf-8") -> str:
        """Read file contents."""
        p = self._resolve_path(path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return await asyncio.to_thread(p.read_text, encoding=encoding)

    async def write_file(
        self,
        path: str,
        content: str,
        encoding: str = "utf-8",
        create_dirs: bool = True,
    ) -> Path:
        """Write content to file."""
        p = self._resolve_path(path)
        if create_dirs:
            p.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(p.write_text, content, encoding=encoding)
        return p

    async def append_file(self, path: str, content: str, encoding: str = "utf-8") -> Path:
        """Append content to file."""
        p = self._resolve_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(lambda: p.open("a", encoding=encoding).write(content))
        return p

    async def delete_file(self, path: str) -> bool:
        """Delete a file."""
        p = self._resolve_path(path)
        if p.exists():
            await asyncio.to_thread(p.unlink)
            return True
        return False

    async def list_files(
        self,
        path: str = ".",
        pattern: str = "*",
        recursive: bool = False,
    ) -> list[dict]:
        """List files matching pattern."""
        p = self._resolve_path(path)
        if not p.exists():
            return []

        if recursive:
            files = p.rglob(pattern)
        else:
            files = p.glob(pattern)

        results = []
        for f in files:
            stat = await asyncio.to_thread(f.stat)
            results.append({
                "path": str(f.relative_to(self._base_path)),
                "absolute_path": str(f),
                "name": f.name,
                "is_dir": f.is_dir(),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        return results

    async def search_files(
        self,
        query: str,
        path: str = ".",
        file_types: list[str] = None,
        max_results: int = 100,
    ) -> list[dict]:
        """Search file contents."""
        p = self._resolve_path(path)
        results = []

        # Use ripgrep if available, else Python fallback
        try:
            import subprocess
            cmd = ["rg", "-l", query, str(p)]
            if file_types:
                for ft in file_types:
                    cmd.extend(["-g", f"*.{ft}"])
            result = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line:
                        f = Path(line)
                        rel = f.relative_to(self._base_path)
                        results.append({
                            "path": str(rel),
                            "absolute_path": str(f),
                            "name": f.name,
                        })
                        if len(results) >= max_results:
                            break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # Fallback: simple Python search
            for f in p.rglob("*"):
                if f.is_file() and (not file_types or f.suffix[1:] in file_types):
                    try:
                        content = await asyncio.to_thread(f.read_text, encoding="utf-8", errors="ignore")
                        if query.lower() in content.lower():
                            results.append({
                                "path": str(f.relative_to(self._base_path)),
                                "absolute_path": str(f),
                                "name": f.name,
                            })
                            if len(results) >= max_results:
                                break
                    except Exception:
                        pass

        return results

    async def create_dir(self, path: str) -> Path:
        """Create directory."""
        p = self._resolve_path(path)
        await asyncio.to_thread(p.mkdir, parents=True, exist_ok=True)
        return p

    async def copy_file(self, src: str, dst: str) -> Path:
        """Copy file."""
        src_p = self._resolve_path(src)
        dst_p = self._resolve_path(dst)
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, src_p, dst_p)
        return dst_p

    async def move_file(self, src: str, dst: str) -> Path:
        """Move/rename file."""
        src_p = self._resolve_path(src)
        dst_p = self._resolve_path(dst)
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(src_p), str(dst_p))
        return dst_p

    async def get_file_info(self, path: str) -> dict:
        """Get file metadata."""
        p = self._resolve_path(path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")
        stat = await asyncio.to_thread(p.stat)
        return {
            "path": str(p.relative_to(self._base_path)),
            "absolute_path": str(p),
            "name": p.name,
            "is_dir": p.is_dir(),
            "size": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "permissions": oct(stat.st_mode)[-3:],
        }

    async def read_json(self, path: str) -> dict:
        """Read and parse JSON file."""
        content = await self.read_file(path)
        return json.loads(content)

    async def write_json(self, path: str, data: dict, indent: int = 2) -> Path:
        """Write data as JSON file."""
        content = json.dumps(data, indent=indent)
        return await self.write_file(path, content)

    async def read_yaml(self, path: str) -> dict:
        """Read and parse YAML file."""
        content = await self.read_file(path)
        return yaml.safe_load(content)

    async def write_yaml(self, path: str, data: dict) -> Path:
        """Write data as YAML file."""
        content = yaml.dump(data, default_flow_style=False)
        return await self.write_file(path, content)

    async def watch_path(self, path: str, recursive: bool = True) -> bool:
        """Watch a path for changes."""
        p = self._resolve_path(path)
        if p in self._watched_paths:
            return True

        if not self._observer:
            return False

        handler = FileWatchHandler(self)
        handler.set_loop(asyncio.get_event_loop())
        self._observer.schedule(handler, str(p), recursive=recursive)
        self._watched_paths.add(p)
        logger.info(f"Watching: {p}")
        return True

    async def unwatch_path(self, path: str) -> bool:
        """Stop watching a path."""
        p = self._resolve_path(path)
        # Watchdog doesn't support easy unwatch, would need to track watch IDs
        # For now, just track internally
        self._watched_paths.discard(p)
        return True