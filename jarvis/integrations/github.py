"""GitHub integration plugin."""

import asyncio
import base64
import os
from pathlib import Path
from typing import Any, Optional
from datetime import datetime

from github import Github, GithubException
from git import Repo, GitCommandError

from ..core.plugin import Plugin, PluginMetadata, PluginStatus
from ..core.events import Event
from ..config.settings import get_settings
from ..config.secrets import get_secrets_manager
from loguru import logger


class GitHubPlugin(Plugin):
    """GitHub integration for repos, issues, PRs, and local git."""

    def __init__(self):
        metadata = PluginMetadata(
            name="github",
            version="1.0.0",
            description="GitHub integration (repos, issues, PRs, actions, local git)",
            author="Jarvis",
            tags=["github", "git", "version-control", "ci-cd"],
            required_permissions=["github.read", "github.write", "git.local"],
        )
        super().__init__(metadata)
        self._gh: Optional[Github] = None
        self._local_repos: dict[str, Repo] = {}

    async def initialize(self, config: dict[str, Any]) -> None:
        await super().initialize(config)
        settings = get_settings()
        secrets = get_secrets_manager()

        token = secrets.get_github_token() or settings.github.token
        if token:
            self._gh = Github(token)
            # Verify auth
            try:
                user = await asyncio.to_thread(lambda: self._gh.get_user().login)
                logger.info(f"GitHub authenticated as: {user}")
            except GithubException as e:
                logger.error(f"GitHub auth failed: {e}")
                self._gh = None
        else:
            logger.warning("No GitHub token configured")

        self.status = PluginStatus.LOADED

    async def start(self) -> None:
        await super().start()
        logger.info("GitHub plugin started")

    async def stop(self) -> None:
        await super().stop()
        # Close local repos
        for repo in self._local_repos.values():
            try:
                repo.close()
            except Exception:
                pass
        self._local_repos.clear()
        logger.info("GitHub plugin stopped")

    # GitHub API methods
    async def get_user_info(self) -> Optional[dict]:
        """Get authenticated user info."""
        if not self._gh:
            return None
        try:
            user = await asyncio.to_thread(self._gh.get_user)
            return {
                "login": user.login,
                "name": user.name,
                "email": user.email,
                "public_repos": user.public_repos,
                "private_repos": user.total_private_repos,
            }
        except GithubException as e:
            logger.error(f"GitHub get_user error: {e}")
            return None

    async def list_repos(
        self,
        org: str = None,
        type: str = "all",
        sort: str = "updated",
    ) -> list[dict]:
        """List repositories."""
        if not self._gh:
            return []

        try:
            if org:
                target = await asyncio.to_thread(self._gh.get_organization, org)
            else:
                target = await asyncio.to_thread(self._gh.get_user)

            repos = await asyncio.to_thread(
                lambda: list(target.get_repos(type=type, sort=sort))
            )
            return [
                {
                    "name": r.name,
                    "full_name": r.full_name,
                    "description": r.description,
                    "private": r.private,
                    "html_url": r.html_url,
                    "clone_url": r.clone_url,
                    "default_branch": r.default_branch,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    "stars": r.stargazers_count,
                    "forks": r.forks_count,
                    "language": r.language,
                }
                for r in repos
            ]
        except GithubException as e:
            logger.error(f"GitHub list_repos error: {e}")
            return []

    async def create_repo(
        self,
        name: str,
        description: str = "",
        private: bool = True,
        org: str = None,
        auto_init: bool = True,
        gitignore_template: str = None,
        license_template: str = None,
    ) -> Optional[dict]:
        """Create a new repository."""
        if not self._gh:
            return None

        try:
            if org:
                target = await asyncio.to_thread(self._gh.get_organization, org)
            else:
                target = await asyncio.to_thread(self._gh.get_user)

            repo = await asyncio.to_thread(
                target.create_repo,
                name=name,
                description=description,
                private=private,
                auto_init=auto_init,
                gitignore_template=gitignore_template,
                license_template=license_template,
            )
            return {
                "name": repo.name,
                "full_name": repo.full_name,
                "html_url": repo.html_url,
                "clone_url": repo.clone_url,
            }
        except GithubException as e:
            logger.error(f"GitHub create_repo error: {e}")
            return None

    async def create_file(
        self,
        repo_full_name: str,
        path: str,
        content: str,
        message: str,
        branch: str = "main",
    ) -> Optional[dict]:
        """Create or update a file in a repo."""
        if not self._gh:
            return None

        try:
            repo = await asyncio.to_thread(self._gh.get_repo, repo_full_name)
            # Check if file exists
            try:
                existing = await asyncio.to_thread(repo.get_contents, path, ref=branch)
                # Update
                result = await asyncio.to_thread(
                    repo.update_file,
                    path=path,
                    message=message,
                    content=content,
                    sha=existing.sha,
                    branch=branch,
                )
            except GithubException:
                # Create new
                result = await asyncio.to_thread(
                    repo.create_file,
                    path=path,
                    message=message,
                    content=content,
                    branch=branch,
                )
            return result
        except GithubException as e:
            logger.error(f"GitHub create_file error: {e}")
            return None

    async def create_readme(
        self,
        repo_full_name: str,
        title: str,
        description: str = "",
        sections: list[dict] = None,
        branch: str = "main",
    ) -> Optional[dict]:
        """Generate and create a README.md."""
        sections = sections or []
        content = f"# {title}\n\n"
        if description:
            content += f"{description}\n\n"

        content += "## Overview\n\n"
        content += "This repository was created and is maintained by Jarvis.\n\n"

        if sections:
            for section in sections:
                content += f"## {section.get('title', 'Section')}\n\n"
                content += f"{section.get('content', '')}\n\n"

        content += "---\n\n"
        content += f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n"
        content += "*Generated by [Jarvis](https://github.com/yourusername/jarvis)*\n"

        return await self.create_file(
            repo_full_name=repo_full_name,
            path="README.md",
            content=content,
            message="Add/update README.md via Jarvis",
            branch=branch,
        )

    async def push_local_repo(
        self,
        local_path: str,
        repo_full_name: str,
        branch: str = "main",
        force: bool = False,
    ) -> bool:
        """Push local repo to GitHub."""
        try:
            repo = self._get_local_repo(local_path)
            remote_name = "origin"

            # Check if remote exists
            try:
                remote = repo.remote(remote_name)
            except ValueError:
                remote = repo.create_remote(remote_name, f"https://github.com/{repo_full_name}.git")

            # Push
            push_info = await asyncio.to_thread(
                lambda: remote.push(refspec=f"{branch}:{branch}", force=force)
            )
            return all(p.flags == 0 for p in push_info)
        except GitCommandError as e:
            logger.error(f"Git push error: {e}")
            return False

    async def commit_and_push(
        self,
        local_path: str,
        message: str,
        files: list[str] = None,
        branch: str = "main",
    ) -> bool:
        """Commit and push local changes."""
        try:
            repo = self._get_local_repo(local_path)

            # Stage files
            if files:
                await asyncio.to_thread(repo.index.add, files)
            else:
                await asyncio.to_thread(repo.index.add, ["."])

            # Commit
            await asyncio.to_thread(repo.index.commit, message)

            # Push
            return await self.push_local_repo(local_path, repo_full_name="", branch=branch)
        except GitCommandError as e:
            logger.error(f"Git commit/push error: {e}")
            return False

    def _get_local_repo(self, path: str) -> Repo:
        """Get or create local repo object."""
        p = Path(path).expanduser().resolve()
        if str(p) in self._local_repos:
            return self._local_repos[str(p)]

        try:
            repo = Repo(p)
        except Exception:
            repo = Repo.init(p)

        self._local_repos[str(p)] = repo
        return repo

    # Local git operations
    async def git_status(self, path: str) -> dict:
        """Get git status."""
        repo = self._get_local_repo(path)
        return {
            "branch": repo.active_branch.name,
            "is_dirty": repo.is_dirty(),
            "untracked": repo.untracked_files,
            "modified": [item.a_path for item in repo.index.diff(None)],
            "staged": [item.a_path for item in repo.index.diff("HEAD")],
        }

    async def git_log(self, path: str, max_count: int = 10) -> list[dict]:
        """Get recent commits."""
        repo = self._get_local_repo(path)
        commits = []
        for commit in repo.iter_commits(max_count=max_count):
            commits.append({
                "hash": commit.hexsha[:8],
                "message": commit.message.strip(),
                "author": str(commit.author),
                "date": datetime.fromtimestamp(commit.committed_date).isoformat(),
            })
        return commits

    async def create_branch(self, path: str, branch_name: str, from_branch: str = None) -> bool:
        """Create and checkout new branch."""
        try:
            repo = self._get_local_repo(path)
            if from_branch:
                repo.git.checkout(from_branch)
            new_branch = repo.create_head(branch_name)
            new_branch.checkout()
            return True
        except GitCommandError as e:
            logger.error(f"Git create branch error: {e}")
            return False

    async def create_pr(
        self,
        repo_full_name: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> Optional[dict]:
        """Create a pull request."""
        if not self._gh:
            return None

        try:
            repo = await asyncio.to_thread(self._gh.get_repo, repo_full_name)
            pr = await asyncio.to_thread(
                repo.create_pull,
                title=title,
                body=body,
                head=head,
                base=base,
            )
            return {
                "number": pr.number,
                "url": pr.html_url,
                "title": pr.title,
            }
        except GithubException as e:
            logger.error(f"GitHub create_pr error: {e}")
            return None