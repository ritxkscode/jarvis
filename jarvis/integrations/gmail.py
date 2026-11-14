"""Gmail integration plugin for multiple accounts."""

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any, Optional
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..core.plugin import Plugin, PluginMetadata, PluginStatus
from ..core.events import Event, EventBus
from ..config.settings import get_settings
from ..config.secrets import get_secrets_manager
from loguru import logger

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailAccount:
    """Single Gmail account handler."""

    def __init__(self, email: str, credentials: Credentials):
        self.email = email
        self.credentials = credentials
        self.service = build("gmail", "v1", credentials=credentials)

    async def list_messages(
        self,
        query: str = "",
        max_results: int = 50,
        label_ids: list[str] = None,
    ) -> list[dict]:
        """List messages matching query with retry on transient errors."""
        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                request = self.service.users().messages().list(
                    userId="me",
                    q=query,
                    maxResults=max_results,
                    labelIds=label_ids,
                )
                response = await asyncio.to_thread(request.execute)
                messages = response.get("messages", [])

                # Get full message details
                results = []
                for msg in messages:
                    detail = await self.get_message(msg["id"])
                    if detail:
                        results.append(detail)
                return results
            except HttpError as e:
                logger.error(f"Gmail list error for {self.email}: {e}")
                return []
            except Exception as e:
                # Retry on transient SSL/network errors
                if "SSL" in str(e) or "RECORD_LAYER_FAILURE" in str(e) or "connection" in str(e).lower():
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Transient Gmail error (attempt {attempt + 1}/{max_retries}), retrying in {delay}s: {e}")
                        await asyncio.sleep(delay)
                        continue
                logger.error(f"Gmail list error for {self.email}: {e}")
                return []

        return []

    async def get_message(self, msg_id: str) -> Optional[dict]:
        """Get full message by ID with retry on transient errors."""
        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                request = self.service.users().messages().get(
                    userId="me", id=msg_id, format="full"
                )
                msg = await asyncio.to_thread(request.execute)
                return self._parse_message(msg)
            except HttpError as e:
                logger.error(f"Gmail get error for {self.email}: {e}")
                return None
            except Exception as e:
                # Retry on transient SSL/network errors
                if "SSL" in str(e) or "RECORD_LAYER_FAILURE" in str(e) or "connection" in str(e).lower():
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Transient Gmail error (attempt {attempt + 1}/{max_retries}), retrying in {delay}s: {e}")
                        await asyncio.sleep(delay)
                        continue
                logger.error(f"Gmail get error for {self.email}: {e}")
                return None

        return None

    async def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
        attachments: list[dict] = None,
    ) -> Optional[dict]:
        """Send an email."""
        try:
            message = MIMEMultipart("alternative")
            message["to"] = to
            message["subject"] = subject

            if html:
                message.attach(MIMEText(body, "html"))
            else:
                message.attach(MIMEText(body, "plain"))

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            request = self.service.users().messages().send(
                userId="me", body={"raw": raw}
            )
            return await asyncio.to_thread(request.execute)
        except HttpError as e:
            logger.error(f"Gmail send error for {self.email}: {e}")
            return None

    async def mark_read(self, msg_id: str) -> bool:
        """Mark message as read."""
        try:
            request = self.service.users().messages().modify(
                userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
            )
            await asyncio.to_thread(request.execute)
            return True
        except HttpError:
            return False

    async def add_label(self, msg_id: str, label: str) -> bool:
        """Add label to message."""
        try:
            # Create label if needed
            label_id = await self._get_or_create_label(label)
            request = self.service.users().messages().modify(
                userId="me", id=msg_id, body={"addLabelIds": [label_id]}
            )
            await asyncio.to_thread(request.execute)
            return True
        except HttpError:
            return False

    async def _get_or_create_label(self, name: str) -> str:
        """Get or create a label."""
        try:
            labels = await asyncio.to_thread(
                self.service.users().labels().list(userId="me").execute
            )
            for label in labels.get("labels", []):
                if label["name"] == name:
                    return label["id"]

            # Create new
            body = {"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
            label = await asyncio.to_thread(
                self.service.users().labels().create(userId="me", body=body).execute
            )
            return label["id"]
        except HttpError:
            return name

    def _parse_message(self, msg: dict) -> dict:
        """Parse Gmail message into standardized format."""
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

        # Get body
        body = ""
        payload = msg.get("payload", {})
        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    data = part["body"].get("data", "")
                    body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                    break
        elif payload.get("body", {}).get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")

        return {
            "id": msg["id"],
            "thread_id": msg.get("threadId"),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
            "body": body[:5000],  # Truncate
            "labels": msg.get("labelIds", []),
            "account": self.email,
        }


class GmailPlugin(Plugin):
    """Gmail integration for multiple accounts."""

    def __init__(self):
        metadata = PluginMetadata(
            name="gmail",
            version="1.0.0",
            description="Multi-account Gmail integration (read, send, organize)",
            author="Jarvis",
            tags=["email", "gmail", "google"],
            required_permissions=["gmail.read", "gmail.send"],
        )
        super().__init__(metadata)
        self._accounts: dict[str, GmailAccount] = {}
        self._polling_task: Optional[asyncio.Task] = None
        self._poll_interval = 60  # seconds

    async def initialize(self, config: dict[str, Any]) -> None:
        await super().initialize(config)
        settings = get_settings()
        secrets = get_secrets_manager()

        # Load Google OAuth config (from secrets first, then settings/.env)
        oauth = secrets.get_google_oauth()
        if not oauth and settings.google_cloud:
            oauth = {
                "client_id": settings.google_cloud.client_id,
                "client_secret": settings.google_cloud.client_secret,
                "project_id": settings.google_cloud.project_id,
            }
            # Save to secrets for future use
            secrets.set_google_oauth(**oauth)
        if not oauth:
            logger.warning("No Google OAuth config found. Run setup_oauth() first.")
            return

        # Load accounts from settings (explicit config)
        for acc_config in settings.gmail_accounts:
            email = acc_config.email
            creds_data = secrets.get_gmail_credentials(email)
            if creds_data:
                try:
                    creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
                    if creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                        secrets.set_gmail_credentials(email, json.loads(creds.to_json()))
                    self._accounts[email] = GmailAccount(email, creds)
                    logger.info(f"Loaded Gmail account: {email}")
                except Exception as e:
                    logger.error(f"Failed to load Gmail account {email}: {e}")

        # Also load any accounts found in secrets (from setup_oauth)
        for key in secrets.list_keys():
            if key.startswith("gmail_") and "_at_" in key:
                # key format: gmail_user_at_domain.com
                email = key.replace("gmail_", "").replace("_at_", "@")
                if email not in self._accounts:
                    creds_data = secrets.get_gmail_credentials(email)
                    if creds_data:
                        try:
                            creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
                            if creds.expired and creds.refresh_token:
                                creds.refresh(Request())
                                secrets.set_gmail_credentials(email, json.loads(creds.to_json()))
                            self._accounts[email] = GmailAccount(email, creds)
                            logger.info(f"Loaded Gmail account from secrets: {email}")
                        except Exception as e:
                            logger.error(f"Failed to load Gmail account {email}: {e}")

        self.status = PluginStatus.LOADED

    async def start(self) -> None:
        await super().start()
        # Start background polling
        self._polling_task = asyncio.create_task(self._poll_loop())
        logger.info("Gmail plugin started")

    async def stop(self) -> None:
        await super().stop()
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
        logger.info("Gmail plugin stopped")

    async def _poll_loop(self) -> None:
        """Background polling for new emails."""
        while self.status == PluginStatus.RUNNING:
            try:
                await self.check_new_emails()
            except Exception as e:
                logger.error(f"Gmail poll error: {e}")
            await asyncio.sleep(self._poll_interval)

    async def check_new_emails(self) -> list[dict]:
        """Check all accounts for new unread emails."""
        all_new = []
        for email, account in self._accounts.items():
            messages = await account.list_messages(
                query="is:unread", max_results=20
            )
            for msg in messages:
                # Emit event for each new email
                await self.emit_event(Event(
                    type="email.received",
                    source="gmail",
                    data={"account": email, "message": msg}
                ))
                all_new.append(msg)
        return all_new

    # Action methods for task execution
    async def list_emails(
        self,
        account: str = "",
        query: str = "",
        max_results: int = 50,
        unread_only: bool = False,
    ) -> list[dict]:
        """List emails from account(s)."""
        if account:
            accounts = {account: self._accounts.get(account)}
        else:
            accounts = self._accounts

        results = []
        for email, acc in accounts.items():
            if not acc:
                continue
            q = query
            if unread_only:
                q = f"{q} is:unread" if q else "is:unread"
            msgs = await acc.list_messages(q, max_results)
            results.extend(msgs)
        return results

    async def send_email(
        self,
        account: str,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
    ) -> Optional[dict]:
        """Send email from specific account."""
        acc = self._accounts.get(account)
        if not acc:
            raise ValueError(f"Account {account} not found")
        return await acc.send_message(to, subject, body, html)

    async def mark_read(self, account: str, msg_id: str) -> bool:
        """Mark email as read."""
        acc = self._accounts.get(account)
        if not acc:
            return False
        return await acc.mark_read(msg_id)

    async def label_email(self, account: str, msg_id: str, label: str) -> bool:
        """Add label to email."""
        acc = self._accounts.get(account)
        if not acc:
            return False
        return await acc.add_label(msg_id, label)

    async def search_emails(
        self,
        query: str,
        accounts: list[str] = None,
        max_results: int = 50,
    ) -> list[dict]:
        """Search emails across accounts."""
        target_accounts = accounts or list(self._accounts.keys())
        results = []
        for email in target_accounts:
            acc = self._accounts.get(email)
            if acc:
                msgs = await acc.list_messages(query, max_results)
                results.extend(msgs)
        return results

    async def setup_oauth(self, client_id: str, client_secret: str, project_id: str) -> str:
        """Run OAuth flow to authorize a new account."""
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost:8080"],
                }
            },
            SCOPES,
        )
        creds = flow.run_local_server(port=8080)

        # Get email from credentials
        service = build("gmail", "v1", credentials=creds)
        profile = await asyncio.to_thread(
            service.users().getProfile(userId="me").execute
        )
        email = profile["emailAddress"]

        # Save credentials
        secrets = get_secrets_manager()
        secrets.set_google_oauth(client_id, client_secret, project_id)
        secrets.set_gmail_credentials(email, json.loads(creds.to_json()))

        # Add to settings if not present
        settings = get_settings()
        if not any(a.email == email for a in settings.gmail_accounts):
            from ..config.settings import GmailAccountSettings
            settings.gmail_accounts.append(GmailAccountSettings(email=email))

        # Load the new account
        self._accounts[email] = GmailAccount(email, creds)
        logger.info(f"Added Gmail account: {email}")
        return email

    def get_accounts(self) -> list[str]:
        """Get list of configured accounts."""
        return list(self._accounts.keys())