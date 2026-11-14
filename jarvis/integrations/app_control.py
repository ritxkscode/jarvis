"""macOS app control via Accessibility API and AppleScript."""

import asyncio
import subprocess
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass

from ..core.plugin import Plugin, PluginMetadata, PluginStatus
from ..core.events import Event
from ..config.settings import get_settings
from loguru import logger


@dataclass
class AppInfo:
    """Application information."""

    name: str
    bundle_id: str
    pid: int
    running: bool


class AppControlPlugin(Plugin):
    """macOS app control using Accessibility API and AppleScript."""

    def __init__(self):
        metadata = PluginMetadata(
            name="app_control",
            version="1.0.0",
            description="macOS app control (launch, click, type, automate via Accessibility)",
            author="Jarvis",
            tags=["macos", "accessibility", "automation", "applescript"],
            required_permissions=["accessibility", "screen_recording"],
        )
        super().__init__(metadata)
        self._accessibility_enabled = False
        self._allowed_apps: set[str] = set()

    async def initialize(self, config: dict[str, Any]) -> None:
        await super().initialize(config)
        settings = get_settings()
        self._allowed_apps = set(settings.app_control.allowed_apps)
        self._accessibility_enabled = await self._check_accessibility()
        self.status = PluginStatus.LOADED

    async def start(self) -> None:
        await super().start()
        logger.info("App Control plugin started")

    async def stop(self) -> None:
        await super().stop()
        logger.info("App Control plugin stopped")

    async def _check_accessibility(self) -> bool:
        """Check if Accessibility permission is granted."""
        try:
            # Try to access System Events
            result = await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", 'tell application "System Events" to get name of every process'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    async def request_accessibility(self) -> bool:
        """Prompt user to grant Accessibility permission."""
        try:
            # Open System Preferences to Accessibility
            await asyncio.to_thread(
                subprocess.run,
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            )
            # Wait and recheck
            await asyncio.sleep(2)
            self._accessibility_enabled = await self._check_accessibility()
            return self._accessibility_enabled
        except Exception:
            return False

    # App management
    async def launch_app(self, app_name: str, hide: bool = False) -> bool:
        """Launch an application."""
        # Case-insensitive check
        allowed_lower = {a.lower() for a in self._allowed_apps}
        if app_name.lower() not in allowed_lower:
            logger.warning(f"App {app_name} not in allowed list")
            # Still try
            pass

        try:
            script = f'tell application "{app_name}" to launch'
            if hide:
                script += ' tell application "System Events" to set visible of process "{app_name}" to false'
            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                check=True,
                timeout=10,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to launch {app_name}: {e}")
            return False

    async def quit_app(self, app_name: str) -> bool:
        """Quit an application."""
        allowed_lower = {a.lower() for a in self._allowed_apps}
        if app_name.lower() not in allowed_lower:
            logger.warning(f"App {app_name} not in allowed list")
            # Still try
            pass
        try:
            script = f'tell application "{app_name}" to quit'
            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                check=True,
                timeout=10,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to quit {app_name}: {e}")
            return False

    async def activate_app(self, app_name: str) -> bool:
        """Bring app to front."""
        allowed_lower = {a.lower() for a in self._allowed_apps}
        if app_name.lower() not in allowed_lower:
            logger.warning(f"App {app_name} not in allowed list")
            # Still try
            pass
        try:
            script = f'tell application "{app_name}" to activate'
            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                check=True,
                timeout=5,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to activate {app_name}: {e}")
            return False

    async def get_running_apps(self) -> list[AppInfo]:
        """Get list of running applications."""
        try:
            script = '''
            tell application "System Events"
                set appList to {}
                repeat with p in (every process whose background only is false)
                    set end of appList to {name:name of p, bundle identifier:bundle identifier of p, unix id:unix id of p}
                end repeat
                return appList
            end tell
            '''
            result = await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10,
            )

            apps = []
            # Parse AppleScript record list
            # Output format: {name:"App", bundle identifier:"com.app", unix id:123}, ...
            import re
            for match in re.finditer(r'\{name:"([^"]+)", bundle identifier:"([^"]*)", unix id:(\d+)\}', result.stdout):
                apps.append(AppInfo(
                    name=match.group(1),
                    bundle_id=match.group(2),
                    pid=int(match.group(3)),
                    running=True,
                ))
            return apps
        except Exception as e:
            logger.error(f"Failed to get running apps: {e}")
            return []

    # UI Automation (Accessibility)
    async def click_at(self, x: int, y: int, app_name: str = None) -> bool:
        """Click at screen coordinates."""
        try:
            script = f'''
            tell application "System Events"
                click at {{{x}, {y}}}
            end tell
            '''
            if app_name:
                script = f'tell application "{app_name}" to activate\n' + script

            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                check=True,
                timeout=5,
            )
            return True
        except Exception as e:
            logger.error(f"Click failed: {e}")
            return False

    async def type_text(self, text: str, app_name: str = None, delay: float = 0.01) -> bool:
        """Type text via keystrokes."""
        try:
            # Escape special characters
            escaped = text.replace('"', '\\"').replace('\\', '\\\\')
            script = f'''
            tell application "System Events"
                keystroke "{escaped}"
            end tell
            '''
            if app_name:
                script = f'tell application "{app_name}" to activate\n' + script

            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                check=True,
                timeout=10,
            )
            return True
        except Exception as e:
            logger.error(f"Type text failed: {e}")
            return False

    async def press_key(self, key: str, app_name: str = None, modifiers: list[str] = None) -> bool:
        """Press a key combination."""
        try:
            mod_str = ""
            if modifiers:
                mod_map = {"cmd": "command down", "shift": "shift down", "opt": "option down", "ctrl": "control down"}
                mod_str = " using {" + ", ".join(mod_map.get(m, m) for m in modifiers) + "}"

            script = f'''
            tell application "System Events"
                keystroke "{key}"{mod_str}
            end tell
            '''
            if app_name:
                script = f'tell application "{app_name}" to activate\n' + script

            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                check=True,
                timeout=5,
            )
            return True
        except Exception as e:
            logger.error(f"Press key failed: {e}")
            return False

    async def get_window_bounds(self, app_name: str) -> Optional[dict]:
        """Get window position and size."""
        try:
            script = f'''
            tell application "System Events"
                tell process "{app_name}"
                    set frontWindow to front window
                    return {{position of frontWindow, size of frontWindow}}
                end tell
            end tell
            '''
            result = await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5,
            )

            # Parse: {{x, y}, {width, height}}
            import re
            match = re.search(r'\{\{(\d+), (\d+)\}, \{(\d+), (\d+)\}\}', result.stdout)
            if match:
                return {
                    "x": int(match.group(1)),
                    "y": int(match.group(2)),
                    "width": int(match.group(3)),
                    "height": int(match.group(4)),
                }
            return None
        except Exception as e:
            logger.error(f"Get window bounds failed: {e}")
            return None

    async def screenshot(self, path: str, region: tuple = None) -> bool:
        """Take a screenshot."""
        try:
            cmd = ["screencapture", "-x"]
            if region:
                x, y, w, h = region
                cmd.extend(["-R", f"{x},{y},{w},{h}"])
            cmd.append(path)

            await asyncio.to_thread(subprocess.run, cmd, check=True, timeout=10)
            return True
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return False

    # Higher-level automation
    async def open_url(self, url: str, browser: str = "Safari") -> bool:
        """Open URL in browser."""
        # Case-insensitive check for browser
        allowed_lower = {a.lower() for a in self._allowed_apps}
        if browser.lower() not in allowed_lower:
            logger.warning(f"Browser {browser} not in allowed list")
            # Still try
            pass
        try:
            script = f'tell application "{browser}" to open location "{url}"'
            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                check=True,
                timeout=10,
            )
            return True
        except Exception as e:
            logger.error(f"Open URL failed: {e}")
            return False

    async def run_applescript(self, script: str) -> tuple[bool, str]:
        """Run arbitrary AppleScript."""
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0, result.stdout.strip()
        except Exception as e:
            logger.error(f"AppleScript failed: {e}")
            return False, str(e)

    async def send_notification(
        self,
        title: str,
        message: str,
        sound: str = "default",
    ) -> bool:
        """Send macOS notification."""
        try:
            script = f'display notification "{message}" with title "{title}" sound name "{sound}"'
            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                check=True,
                timeout=5,
            )
            return True
        except Exception as e:
            logger.error(f"Notification failed: {e}")
            return False

    # File operations via Finder
    async def reveal_in_finder(self, path: str) -> bool:
        """Reveal file in Finder."""
        try:
            script = f'tell application "Finder" to reveal POSIX file "{path}"'
            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                check=True,
                timeout=5,
            )
            return True
        except Exception as e:
            logger.error(f"Reveal in Finder failed: {e}")
            return False

    async def open_file(self, path: str, app: str = None) -> bool:
        """Open file with default or specific app."""
        try:
            if app:
                script = f'tell application "{app}" to open POSIX file "{path}"'
            else:
                script = f'tell application "Finder" to open POSIX file "{path}"'

            await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                check=True,
                timeout=10,
            )
            return True
        except Exception as e:
            logger.error(f"Open file failed: {e}")
            return False

    def is_accessibility_enabled(self) -> bool:
        return self._accessibility_enabled

    def add_allowed_app(self, app_name: str) -> None:
        self._allowed_apps.add(app_name)

    def remove_allowed_app(self, app_name: str) -> None:
        self._allowed_apps.discard(app_name)

    def get_allowed_apps(self) -> list[str]:
        return list(self._allowed_apps)