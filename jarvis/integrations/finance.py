"""Finance management plugin (Plaid + manual tracking)."""

import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import plaid
from plaid.api import plaid_api
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.accounts_get_request import AccountsGetRequest

from ..core.plugin import Plugin, PluginMetadata, PluginStatus
from ..core.events import Event
from ..config.settings import get_settings
from ..config.secrets import get_secrets_manager
from loguru import logger


class FinancePlugin(Plugin):
    """Finance management with Plaid and manual tracking."""

    def __init__(self):
        metadata = PluginMetadata(
            name="finance",
            version="1.0.0",
            description="Finance tracking (Plaid bank sync, budgets, expenses, investments)",
            author="Jarvis",
            tags=["finance", "plaid", "budget", "expenses", "investments"],
            required_permissions=["finance.read", "finance.write"],
        )
        super().__init__(metadata)
        self._client: Optional[plaid_api.PlaidApi] = None
        self._access_tokens: dict[str, str] = {}  # institution -> access_token
        self._data_dir: Path = Path()
        self._transactions_file: Path = Path()
        self._accounts_file: Path = Path()
        self._budgets_file: Path = Path()

    async def initialize(self, config: dict[str, Any]) -> None:
        await super().initialize(config)
        settings = get_settings()
        secrets = get_secrets_manager()

        # Setup Plaid client
        plaid_creds = secrets.get_plaid_credentials()
        if plaid_creds:
            configuration = plaid.Configuration(
                host=getattr(plaid.Environment, plaid_creds["env"].capitalize()),
                api_key={
                    "clientId": plaid_creds["client_id"],
                    "secret": plaid_creds["secret"],
                },
            )
            api_client = plaid.ApiClient(configuration)
            self._client = plaid_api.PlaidApi(api_client)
            logger.info("Plaid client initialized")

        # Setup local data storage
        self._data_dir = settings.data_dir / "finance"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._transactions_file = self._data_dir / "transactions.json"
        self._accounts_file = self._data_dir / "accounts.json"
        self._budgets_file = self._data_dir / "budgets.json"

        # Load local data
        await self._load_local_data()

        self.status = PluginStatus.LOADED

    async def start(self) -> None:
        await super().start()
        logger.info("Finance plugin started")

    async def stop(self) -> None:
        await super().stop()
        await self._save_local_data()
        logger.info("Finance plugin stopped")

    async def _load_local_data(self) -> None:
        """Load local JSON data files."""
        for attr, file in [
            ("_local_transactions", self._transactions_file),
            ("_local_accounts", self._accounts_file),
            ("_local_budgets", self._budgets_file),
        ]:
            if file.exists():
                content = await asyncio.to_thread(file.read_text)
                setattr(self, attr, json.loads(content))
            else:
                setattr(self, attr, [])

    async def _save_local_data(self) -> None:
        """Save local JSON data files."""
        for attr, file in [
            ("_local_transactions", self._transactions_file),
            ("_local_accounts", self._accounts_file),
            ("_local_budgets", self._budgets_file),
        ]:
            content = json.dumps(getattr(self, attr), indent=2, default=str)
            await asyncio.to_thread(file.write_text, content)

    # Plaid methods
    async def create_link_token(self, user_id: str = "jarvis_user") -> Optional[str]:
        """Create a Plaid Link token for connecting banks."""
        if not self._client:
            return None

        try:
            from plaid.model.link_token_create_request import LinkTokenCreateRequest
            from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
            from plaid.model.products import Products
            from plaid.model.country_code import CountryCode

            request = LinkTokenCreateRequest(
                products=[Products("transactions"), Products("accounts")],
                client_name="Jarvis",
                country_codes=[CountryCode("US")],
                language="en",
                user=LinkTokenCreateRequestUser(client_user_id=user_id),
            )
            response = await asyncio.to_thread(self._client.link_token_create, request)
            return response["link_token"]
        except Exception as e:
            logger.error(f"Plaid create_link_token error: {e}")
            return None

    async def exchange_public_token(self, public_token: str) -> Optional[str]:
        """Exchange public token for access token."""
        if not self._client:
            return None

        try:
            from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest

            request = ItemPublicTokenExchangeRequest(public_token=public_token)
            response = await asyncio.to_thread(self._client.item_public_token_exchange, request)
            access_token = response["access_token"]

            # Get institution info
            from plaid.model.item_get_request import ItemGetRequest
            item_request = ItemGetRequest(access_token=access_token)
            item_response = await asyncio.to_thread(self._client.item_get, item_request)
            institution_id = item_response["item"]["institution_id"]

            self._access_tokens[institution_id] = access_token
            await self._save_access_tokens()
            return access_token
        except Exception as e:
            logger.error(f"Plaid exchange_public_token error: {e}")
            return None

    async def _save_access_tokens(self) -> None:
        """Save access tokens to secrets."""
        secrets = get_secrets_manager()
        for inst_id, token in self._access_tokens.items():
            secrets.set(f"plaid_access_token_{inst_id}", token)

    async def sync_transactions(
        self,
        days_back: int = 30,
        institution_id: str = None,
    ) -> list[dict]:
        """Sync transactions from Plaid."""
        if not self._client:
            return []

        tokens = {institution_id: self._access_tokens[institution_id]} if institution_id else self._access_tokens
        all_transactions = []

        for inst_id, access_token in tokens.items():
            try:
                start_date = (datetime.now() - timedelta(days=days_back)).date()
                end_date = datetime.now().date()

                request = TransactionsGetRequest(
                    access_token=access_token,
                    start_date=start_date,
                    end_date=end_date,
                )
                response = await asyncio.to_thread(self._client.transactions_get, request)

                for txn in response["transactions"]:
                    txn["institution_id"] = inst_id
                    txn["synced_at"] = datetime.now().isoformat()
                    all_transactions.append(txn)

                logger.info(f"Synced {len(response['transactions'])} transactions from {inst_id}")
            except Exception as e:
                logger.error(f"Plaid sync error for {inst_id}: {e}")

        # Merge with local
        self._local_transactions = self._merge_transactions(self._local_transactions, all_transactions)
        await self._save_local_data()

        # Emit events for new transactions
        for txn in all_transactions:
            await self.emit_event(Event(
                type="finance.transaction",
                source="finance",
                data=txn
            ))

        return all_transactions

    async def sync_accounts(self, institution_id: str = None) -> list[dict]:
        """Sync accounts from Plaid."""
        if not self._client:
            return []

        tokens = {institution_id: self._access_tokens[institution_id]} if institution_id else self._access_tokens
        all_accounts = []

        for inst_id, access_token in tokens.items():
            try:
                request = AccountsGetRequest(access_token=access_token)
                response = await asyncio.to_thread(self._client.accounts_get, request)

                for acct in response["accounts"]:
                    acct["institution_id"] = inst_id
                    acct["synced_at"] = datetime.now().isoformat()
                    all_accounts.append(acct)
            except Exception as e:
                logger.error(f"Plaid accounts error for {inst_id}: {e}")

        self._local_accounts = all_accounts
        await self._save_local_data()
        return all_accounts

    def _merge_transactions(self, existing: list, new: list) -> list:
        """Merge transactions, avoiding duplicates by transaction_id."""
        existing_ids = {t.get("transaction_id") for t in existing}
        merged = list(existing)
        for t in new:
            if t.get("transaction_id") not in existing_ids:
                merged.append(t)
        # Sort by date descending
        merged.sort(key=lambda x: x.get("date", ""), reverse=True)
        return merged

    # Manual tracking methods
    async def add_transaction(
        self,
        amount: float,
        description: str,
        category: str,
        date: datetime = None,
        account: str = "manual",
        type: str = "expense",  # expense, income, transfer
        tags: list[str] = None,
    ) -> dict:
        """Add a manual transaction."""
        txn = {
            "id": str(uuid4()),
            "transaction_id": f"manual_{uuid4().hex[:8]}",
            "amount": amount,
            "description": description,
            "category": category,
            "date": (date or datetime.now()).date().isoformat(),
            "account": account,
            "type": type,
            "tags": tags or [],
            "manual": True,
            "created_at": datetime.now().isoformat(),
        }
        self._local_transactions.insert(0, txn)
        await self._save_local_data()
        return txn

    async def get_transactions(
        self,
        start_date: datetime = None,
        end_date: datetime = None,
        category: str = None,
        account: str = None,
        type: str = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get filtered transactions."""
        results = self._local_transactions

        if start_date:
            results = [t for t in results if t.get("date", "") >= start_date.date().isoformat()]
        if end_date:
            results = [t for t in results if t.get("date", "") <= end_date.date().isoformat()]
        if category:
            results = [t for t in results if t.get("category") == category]
        if account:
            results = [t for t in results if t.get("account") == account]
        if type:
            results = [t for t in results if t.get("type") == type]

        return results[:limit]

    async def get_spending_summary(
        self,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> dict:
        """Get spending summary by category."""
        start = start_date or (datetime.now() - timedelta(days=30))
        end = end_date or datetime.now()

        txns = await self.get_transactions(start_date=start, end_date=end, type="expense")

        by_category = {}
        total = Decimal("0")
        for t in txns:
            cat = t.get("category", "Other")
            amt = Decimal(str(t.get("amount", 0)))
            by_category[cat] = by_category.get(cat, Decimal("0")) + amt
            total += amt

        return {
            "period": {"start": start.date().isoformat(), "end": end.date().isoformat()},
            "total": float(total),
            "by_category": {k: float(v) for k, v in by_category.items()},
            "transaction_count": len(txns),
        }

    # Budget methods
    async def set_budget(
        self,
        category: str,
        amount: float,
        period: str = "monthly",  # weekly, monthly, yearly
    ) -> dict:
        """Set a budget for a category."""
        budget = {
            "category": category,
            "amount": amount,
            "period": period,
            "updated_at": datetime.now().isoformat(),
        }
        # Remove existing
        self._local_budgets = [b for b in self._local_budgets if b["category"] != category]
        self._local_budgets.append(budget)
        await self._save_local_data()
        return budget

    async def get_budgets(self) -> list[dict]:
        """Get all budgets."""
        return self._local_budgets

    async def check_budgets(self) -> list[dict]:
        """Check budget status."""
        budgets = await self.get_budgets()
        results = []

        for budget in budgets:
            cat = budget["category"]
            limit = Decimal(str(budget["amount"]))
            period = budget["period"]

            if period == "monthly":
                start = datetime.now().replace(day=1)
            elif period == "weekly":
                start = datetime.now() - timedelta(days=datetime.now().weekday())
            else:
                start = datetime.now().replace(month=1, day=1)

            summary = await self.get_spending_summary(start_date=start)
            spent = Decimal(str(summary["by_category"].get(cat, 0)))

            results.append({
                "category": cat,
                "budget": float(limit),
                "spent": float(spent),
                "remaining": float(limit - spent),
                "percent_used": float(spent / limit * 100) if limit > 0 else 0,
                "over_budget": spent > limit,
            })

        return results

    # Investment tracking (manual)
    async def add_investment(
        self,
        symbol: str,
        shares: float,
        price: float,
        date: datetime = None,
        account: str = "investments",
    ) -> dict:
        """Record an investment purchase."""
        inv = {
            "id": str(uuid4()),
            "symbol": symbol.upper(),
            "shares": shares,
            "price": price,
            "date": (date or datetime.now()).date().isoformat(),
            "account": account,
            "created_at": datetime.now().isoformat(),
        }
        if not hasattr(self, "_local_investments"):
            self._local_investments = []
        self._local_investments.append(inv)
        await self._save_local_data()
        return inv

    async def get_portfolio_value(self) -> dict:
        """Get current portfolio value (using yfinance)."""
        try:
            import yfinance as yf
        except ImportError:
            return {"error": "yfinance not installed"}

        if not hasattr(self, "_local_investments"):
            return {"holdings": [], "total_value": 0}

        holdings = []
        total = Decimal("0")

        for inv in self._local_investments:
            symbol = inv["symbol"]
            shares = Decimal(str(inv["shares"]))

            try:
                ticker = yf.Ticker(symbol)
                current_price = Decimal(str(ticker.info.get("currentPrice", 0)))
                value = shares * current_price
                cost = shares * Decimal(str(inv["price"]))

                holdings.append({
                    "symbol": symbol,
                    "shares": float(shares),
                    "avg_price": float(inv["price"]),
                    "current_price": float(current_price),
                    "value": float(value),
                    "cost": float(cost),
                    "gain_loss": float(value - cost),
                    "gain_loss_pct": float((value - cost) / cost * 100) if cost > 0 else 0,
                })
                total += value
            except Exception as e:
                logger.error(f"Error fetching {symbol}: {e}")

        return {"holdings": holdings, "total_value": float(total)}

    def get_accounts(self) -> list[dict]:
        """Get all accounts."""
        return self._local_accounts