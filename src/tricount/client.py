"""
Tricount API Client

A clean Python client for the Tricount (bunq) API.
Based on reverse engineering of the bunq Tricount Android app.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


# =============================================================================
# Constants
# =============================================================================

BASE_URL = "https://api.tricount.bunq.com"
USER_AGENT = "com.bunq.tricount.android:RELEASE:7.0.7:3174:ANDROID:13:C"
REQUEST_ID = "049bfcdf-6ae4-4cee-af7b-45da31ea85d0"


# =============================================================================
# Enums
# =============================================================================


class TricountStatus(str, Enum):
    """Tricount status (for archiving)"""

    READ_WRITE = "READ_WRITE"  # Active tricount
    READ_ONLY = "READ_ONLY"  # Archived tricount


class MemberStatus(str, Enum):
    """Member status"""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DELETED = "DELETED"


class PaymentStatus(str, Enum):
    """Settlement payment status"""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    REFUNDED = "REFUND_REQUESTED"


class TransactionType(str, Enum):
    """Transaction type"""

    NORMAL = "NORMAL"
    INCOME = "INCOME"
    BALANCE = "BALANCE"


class TransactionStatus(str, Enum):
    """Transaction status"""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SETTLED = "SETTLED"


class AllocationType(str, Enum):
    """How an expense is split"""

    AMOUNT = "AMOUNT"  # Fixed amounts
    RATIO = "RATIO"  # Proportional shares


class Category(str, Enum):
    """Standard expense categories with their emojis"""

    TRAVEL = "TRAVEL"  # 🛏 Accommodation
    ENTERTAINMENT = "ENTERTAINMENT"  # 🎤 Entertainment
    GROCERIES = "GROCERIES"  # 🛒 Groceries
    HEALTHCARE = "HEALTHCARE"  # 🦷 Healthcare
    INSURANCE = "INSURANCE"  # 🧯 Insurance
    RENT_AND_UTILITIES = "RENT_AND_UTILITIES"  # 🏠 Rent
    FOOD_AND_DRINK = "FOOD_AND_DRINK"  # 🍔 Restaurants
    SHOPPING = "SHOPPING"  # 🛍 Shopping
    TRANSPORT = "TRANSPORT"  # 🚕 Transport
    OTHER = "OTHER"  # ✋ Other

    @property
    def emoji(self) -> str:
        emojis = {
            "TRAVEL": "🛏",
            "ENTERTAINMENT": "🎤",
            "GROCERIES": "🛒",
            "HEALTHCARE": "🦷",
            "INSURANCE": "🧯",
            "RENT_AND_UTILITIES": "🏠",
            "FOOD_AND_DRINK": "🍔",
            "SHOPPING": "🛍",
            "TRANSPORT": "🚕",
            "OTHER": "✋",
        }
        return emojis.get(self.value, "")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class Amount:
    """Monetary amount"""

    value: str
    currency: str

    def to_dict(self) -> dict:
        return {"value": self.value, "currency": self.currency}

    @classmethod
    def from_dict(cls, data: dict) -> Amount:
        return cls(value=data.get("value", "0"), currency=data.get("currency", ""))

    def __str__(self) -> str:
        return f"{self.value} {self.currency}"


@dataclass
class Member:
    """Tricount member"""

    id: int
    uuid: str
    display_name: str
    status: str = "ACTIVE"

    @classmethod
    def from_dict(cls, data: dict) -> Member:
        alias = data.get("alias", {})
        return cls(
            id=data.get("id", 0),
            uuid=data.get("uuid", ""),
            display_name=alias.get("display_name", data.get("uuid", "")),
            status=data.get("status", "ACTIVE"),
        )


@dataclass
class Allocation:
    """Expense allocation to a member"""

    membership_uuid: str
    amount: Amount
    allocation_type: AllocationType = AllocationType.AMOUNT
    share_ratio: Optional[int] = None

    def to_dict(self) -> dict:
        result = {
            "membership_uuid": self.membership_uuid,
            "amount": self.amount.to_dict(),
            "type": self.allocation_type.value,
        }
        if self.share_ratio is not None:
            result["share_ratio"] = self.share_ratio
        return result

    @classmethod
    def from_dict(cls, data: dict) -> Allocation:
        return cls(
            membership_uuid=data.get("membership_uuid", ""),
            amount=Amount.from_dict(data.get("amount", {})),
            allocation_type=AllocationType(data.get("type", "AMOUNT")),
            share_ratio=data.get("share_ratio"),
        )


@dataclass
class Transaction:
    """Tricount transaction (expense)"""

    id: Optional[int]
    uuid: str
    description: str
    amount: Amount
    membership_uuid_owner: str
    allocations: list[Allocation]
    date: str
    status: TransactionStatus = TransactionStatus.ACTIVE
    transaction_type: TransactionType = TransactionType.NORMAL
    category: Optional[str] = None
    category_custom: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to API request format"""
        result = {
            "uuid": self.uuid,
            "description": self.description,
            "amount": self.amount.to_dict(),
            "membership_uuid_owner": self.membership_uuid_owner,
            "allocations": [a.to_dict() for a in self.allocations],
            "date": self.date,
            "status": self.status.value,
            "type_transaction": self.transaction_type.value,
        }
        if self.category:
            result["category"] = self.category
        if self.category_custom:
            result["category_custom"] = self.category_custom
        return result

    @classmethod
    def from_dict(cls, data: dict) -> Transaction:
        # Extract owner UUID from membership_owned (response) or membership_uuid_owner (request)
        owner_uuid = data.get("membership_uuid_owner", "")
        if not owner_uuid:
            membership_owned = data.get("membership_owned", {})
            for key, mdata in membership_owned.items():
                owner_uuid = mdata.get("uuid", "")
                break

        # Parse allocations - handle both response format (with membership obj) and request format
        allocations = []
        for a in data.get("allocations", []):
            # Extract membership_uuid from nested membership object if present
            membership_uuid = a.get("membership_uuid", "")
            if not membership_uuid:
                membership = a.get("membership", {})
                for key, mdata in membership.items():
                    membership_uuid = mdata.get("uuid", "")
                    break

            allocations.append(
                Allocation(
                    membership_uuid=membership_uuid,
                    amount=Amount.from_dict(a.get("amount", {})),
                    allocation_type=AllocationType(a.get("type", "AMOUNT")),
                    share_ratio=a.get("share_ratio"),
                )
            )

        return cls(
            id=data.get("id"),
            uuid=data.get("uuid", ""),
            description=data.get("description", ""),
            amount=Amount.from_dict(data.get("amount", {})),
            membership_uuid_owner=owner_uuid,
            allocations=allocations,
            date=data.get("date", ""),
            status=TransactionStatus(data.get("status", "ACTIVE")),
            transaction_type=TransactionType(data.get("type_transaction", "NORMAL")),
            category=data.get("category"),
            category_custom=data.get("category_custom"),
        )


@dataclass
class SettlementItem:
    """Individual settlement payment between two members"""

    amount: Amount
    payer_uuid: str  # Member who owes money
    receiver_uuid: str  # Member who should receive money
    payment_status: PaymentStatus = PaymentStatus.PENDING

    @classmethod
    def from_dict(cls, data: dict) -> SettlementItem:
        # Extract payer UUID from nested membership object
        payer_uuid = ""
        membership_paying = data.get("membership_paying", {})
        for key, mdata in membership_paying.items():
            payer_uuid = mdata.get("uuid", "")
            break

        # Extract receiver UUID from nested membership object
        receiver_uuid = ""
        membership_receiving = data.get("membership_receiving", {})
        for key, mdata in membership_receiving.items():
            receiver_uuid = mdata.get("uuid", "")
            break

        return cls(
            amount=Amount.from_dict(data.get("amount", {})),
            payer_uuid=payer_uuid,
            receiver_uuid=receiver_uuid,
            payment_status=PaymentStatus(data.get("payment_status", "PENDING")),
        )


@dataclass
class Settlement:
    """Settlement record showing who owes whom"""

    id: int
    items: list[SettlementItem]
    total_amount_spent: Amount
    number_of_entries: int
    settlement_time: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> Settlement:
        items = []
        for item in data.get("items", []):
            for key, item_data in item.items():
                if key == "RegistrySettlementItem":
                    items.append(SettlementItem.from_dict(item_data))

        return cls(
            id=data.get("id", 0),
            items=items,
            total_amount_spent=Amount.from_dict(data.get("total_amount_spent", {})),
            number_of_entries=data.get("number_of_entries", 0),
            settlement_time=data.get("settlement_time"),
        )


@dataclass
class AttachmentUrl:
    """URL for an attachment at a specific resolution"""

    url_type: str  # e.g., "ORIGINAL", "THUMBNAIL"
    url: str

    @classmethod
    def from_dict(cls, data: dict) -> AttachmentUrl:
        return cls(
            url_type=data.get("type", ""),
            url=data.get("url", ""),
        )


@dataclass
class GalleryAttachment:
    """Attachment in the tricount gallery"""

    id: int
    uuid: str  # Gallery attachment UUID (top level)
    attachment_uuid: str  # Inner attachment UUID
    content_type: str
    urls: list[AttachmentUrl]
    membership_uuid: str  # Who uploaded it

    @classmethod
    def from_dict(cls, data: dict) -> GalleryAttachment:
        attachment = data.get("attachment", {})
        return cls(
            id=attachment.get("id", 0),
            uuid=data.get("uuid", ""),  # Top-level UUID
            attachment_uuid=attachment.get("uuid", ""),  # Inner attachment UUID
            content_type=attachment.get("content_type", ""),
            urls=[AttachmentUrl.from_dict(u) for u in attachment.get("urls", [])],
            membership_uuid=data.get("membership_uuid", ""),
        )

    @property
    def original_url(self) -> Optional[str]:
        """Get the original (full-size) URL"""
        for u in self.urls:
            if u.url_type == "ORIGINAL":
                return u.url
        return self.urls[0].url if self.urls else None


@dataclass
class Tricount:
    """Tricount (expense group)"""

    id: int
    uuid: str
    title: str
    description: str
    currency: str
    public_identifier_token: str
    members: list[Member] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)
    emoji: Optional[str] = None
    category: Optional[str] = None
    status: str = "READ_WRITE"
    membership_uuid_active: Optional[str] = None  # UUID of member linked to current user

    @classmethod
    def from_dict(cls, data: dict) -> Tricount:
        members = []
        for m in data.get("memberships", []):
            for key, mdata in m.items():
                members.append(Member.from_dict(mdata))

        transactions = []
        for entry in data.get("all_registry_entry", []):
            for key, edata in entry.items():
                if key == "RegistryEntry":
                    transactions.append(Transaction.from_dict(edata))

        return cls(
            id=data.get("id", 0),
            uuid=data.get("uuid", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            currency=data.get("currency", ""),
            public_identifier_token=data.get("public_identifier_token", ""),
            members=members,
            transactions=transactions,
            emoji=data.get("emoji"),
            category=data.get("category"),
            status=data.get("status", "READ_WRITE"),
            membership_uuid_active=data.get("membership_uuid_active"),
        )

    def get_member_by_name(self, name: str) -> Optional[Member]:
        """Find a member by display name"""
        for m in self.members:
            if m.display_name.lower() == name.lower():
                return m
        return None

    def get_member_by_uuid(self, uuid: str) -> Optional[Member]:
        """Find a member by UUID"""
        for m in self.members:
            if m.uuid == uuid:
                return m
        return None

    @property
    def is_archived(self) -> bool:
        """Check if tricount is archived (read-only)"""
        return self.status == TricountStatus.READ_ONLY.value

    @property
    def linked_member(self) -> Optional[Member]:
        """Get the member linked to the current user's account, if any"""
        if self.membership_uuid_active:
            return self.get_member_by_uuid(self.membership_uuid_active)
        return None


# =============================================================================
# Credentials Management
# =============================================================================


@dataclass
class Credentials:
    """API credentials"""

    app_id: str
    public_key_pem: str

    def save(self, path: Path) -> None:
        """Save credentials to file"""
        with open(path, "w") as f:
            json.dump(
                {"app_id": self.app_id, "public_key_pem": self.public_key_pem},
                f,
                indent=2,
            )

    @classmethod
    def load(cls, path: Path) -> Credentials:
        """Load credentials from file"""
        with open(path) as f:
            data = json.load(f)
        return cls(app_id=data["app_id"], public_key_pem=data["public_key_pem"])

    @classmethod
    def generate(cls) -> Credentials:
        """Generate new credentials"""
        app_id = str(uuid.uuid4())
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        public_key_pem = (
            private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.PKCS1,
            )
            .decode("utf-8")
        )
        return cls(app_id=app_id, public_key_pem=public_key_pem)


# =============================================================================
# API Client
# =============================================================================


class TricountAPI:
    """Tricount API client"""

    def __init__(self, credentials: Credentials):
        self.credentials = credentials
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "app-id": credentials.app_id,
                "X-Bunq-Client-Request-Id": REQUEST_ID,
            }
        )
        self.user_id: Optional[int] = None
        self._authenticated = False

    def authenticate(self) -> int:
        """Authenticate with the API and return user ID"""
        resp = self.session.post(
            f"{BASE_URL}/v1/session-registry-installation",
            json={
                "app_installation_uuid": self.credentials.app_id,
                "client_public_key": self.credentials.public_key_pem,
                "device_description": "Android",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        token = None
        user_id = None
        for item in data["Response"]:
            if "Token" in item:
                token = item["Token"]["token"]
            if "UserPerson" in item:
                user_id = item["UserPerson"]["id"]

        if not token or not user_id:
            raise RuntimeError(f"Failed to authenticate: {data}")

        self.session.headers["X-Bunq-Client-Authentication"] = token
        self.user_id = user_id
        self._authenticated = True
        return user_id

    def _ensure_authenticated(self) -> None:
        if not self._authenticated:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

    # -------------------------------------------------------------------------
    # Tricount Operations
    # -------------------------------------------------------------------------

    def get_tricount(self, public_token: str) -> Tricount:
        """
        Fetch a tricount by its public sharing token.

        Note: This returns read-only data. Use join_tricount() first if you
        need to modify the tricount. The membership_uuid_active field will
        only be populated for tricounts you've joined.
        """
        self._ensure_authenticated()
        resp = self.session.get(
            f"{BASE_URL}/v1/user/{self.user_id}/registry",
            params={"public_identifier_token": public_token},
        )
        resp.raise_for_status()
        data = resp.json()

        for item in data["Response"]:
            if "Registry" in item:
                return Tricount.from_dict(item["Registry"])

        raise RuntimeError("No tricount found")

    def get_tricount_by_id(self, tricount_id: int) -> Tricount:
        """
        Fetch a tricount by its ID.

        This only works for tricounts that have been synced to your account
        (via join_tricount or create_tricount). Returns full data including
        membership_uuid_active.
        """
        self._ensure_authenticated()
        resp = self.session.get(f"{BASE_URL}/v1/user/{self.user_id}/registry")
        resp.raise_for_status()
        data = resp.json()

        for item in data["Response"]:
            if "Registry" in item and item["Registry"].get("id") == tricount_id:
                return Tricount.from_dict(item["Registry"])

        raise RuntimeError(f"No tricount found with ID {tricount_id}")

    def join_tricount(self, public_token: str) -> Tricount:
        """
        Join a tricount by its public sharing token.

        This syncs the tricount to your account, allowing you to create/edit
        transactions even if you weren't originally a member. Anyone with the
        sharing link can join.

        Args:
            public_token: The public sharing token (e.g., 'tZiTBpQSBjagpRmjrO')

        Returns:
            The joined Tricount object (now accessible via list_tricounts)
        """
        self._ensure_authenticated()

        # Sync the tricount to our account using registry-synchronization
        payload = {
            "all_registry_active": [{"public_identifier_token": public_token}],
            "all_registry_archived": [],
            "all_registry_deleted": [],
        }

        resp = self.session.post(
            f"{BASE_URL}/v1/user/{self.user_id}/registry-synchronization",
            json=payload,
        )
        resp.raise_for_status()

        # Get the tricount ID from sync response and return full data
        sync_data = resp.json()
        for item in sync_data.get("Response", []):
            if "RegistrySynchronization" in item:
                for registry in item["RegistrySynchronization"].get("all_registry_active", []):
                    if registry.get("public_identifier_token") == public_token:
                        return Tricount.from_dict(registry)

        # Fallback to get_tricount if we can't find it in sync response
        return self.get_tricount(public_token)

    def leave_tricount(self, tricount: Tricount) -> None:
        """
        Leave a tricount (remove it from your account).

        This doesn't delete the tricount or affect other users - it just
        removes it from your synced list. You can re-join anytime using
        join_tricount() with the sharing token.

        Args:
            tricount: The tricount to leave
        """
        self._ensure_authenticated()

        payload = {
            "all_registry_active": [],
            "all_registry_archived": [],
            "all_registry_deleted": [{"public_identifier_token": tricount.public_identifier_token}],
        }

        resp = self.session.post(
            f"{BASE_URL}/v1/user/{self.user_id}/registry-synchronization",
            json=payload,
        )
        resp.raise_for_status()

    def create_tricount(self, title: str, currency: str, description: str = "") -> int:
        """Create a new tricount and return its ID"""
        self._ensure_authenticated()
        resp = self.session.post(
            f"{BASE_URL}/v1/user/{self.user_id}/registry",
            json={"title": title, "currency": currency, "description": description},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["Response"][0]["Id"]["id"]

    def list_tricounts(self) -> list[Tricount]:
        """
        List all tricounts accessible to the authenticated user.

        Returns:
            List of Tricount objects (both active and archived)
        """
        self._ensure_authenticated()
        resp = self.session.get(f"{BASE_URL}/v1/user/{self.user_id}/registry")
        resp.raise_for_status()
        data = resp.json()

        tricounts = []
        for item in data.get("Response", []):
            if "Registry" in item:
                tricounts.append(Tricount.from_dict(item["Registry"]))
        return tricounts

    def update_tricount(
        self,
        tricount: Tricount,
        title: Optional[str] = None,
        emoji: Optional[str] = None,
        category: Optional[str] = None,
    ) -> None:
        """Update tricount metadata (title, emoji, category)"""
        self._ensure_authenticated()
        payload = {}
        if title is not None:
            payload["title"] = title
        if emoji is not None:
            payload["emoji"] = emoji
        if category is not None:
            payload["category"] = category

        if payload:
            resp = self.session.put(
                f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}",
                json=payload,
            )
            resp.raise_for_status()

    def update_tricount_description(self, tricount: Tricount, description: str) -> None:
        """
        Update tricount description.

        Note: Description must be updated separately from other fields.

        Args:
            tricount: The tricount to update
            description: New description text
        """
        self._ensure_authenticated()
        resp = self.session.put(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}",
            json={"description": description},
        )
        resp.raise_for_status()

    def archive_tricount(self, tricount: Tricount) -> None:
        """
        Archive a tricount (make it read-only).

        Args:
            tricount: The tricount to archive
        """
        self._ensure_authenticated()
        resp = self.session.put(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}",
            json={"status": TricountStatus.READ_ONLY.value},
        )
        resp.raise_for_status()

    def unarchive_tricount(self, tricount: Tricount) -> None:
        """
        Unarchive a tricount (make it read-write again).

        Args:
            tricount: The tricount to unarchive
        """
        self._ensure_authenticated()
        resp = self.session.put(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}",
            json={"status": TricountStatus.READ_WRITE.value},
        )
        resp.raise_for_status()

    def delete_tricount(self, tricount: Tricount) -> None:
        """
        Delete a tricount permanently.

        Args:
            tricount: The tricount to delete
        """
        self._ensure_authenticated()
        resp = self.session.delete(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}",
        )
        resp.raise_for_status()

    # -------------------------------------------------------------------------
    # Member Operations
    # -------------------------------------------------------------------------

    def add_members(self, tricount: Tricount, names: list[str]) -> None:
        """Add new members to a tricount"""
        self._ensure_authenticated()

        # Build full membership list with existing + new members
        memberships = []

        # Existing members
        for m in tricount.members:
            memberships.append(
                {
                    "uuid": m.uuid,
                    "status": "ACTIVE",
                    "auto_add_card_transaction": "",
                    "setting": None,
                    "alias": {
                        "type": "UUID",
                        "value": m.uuid,
                        "name": m.display_name,
                    },
                }
            )

        # New members
        for name in names:
            new_uuid = str(uuid.uuid4())
            memberships.append(
                {
                    "uuid": new_uuid,
                    "status": "ACTIVE",
                    "auto_add_card_transaction": "",
                    "setting": None,
                    "alias": {
                        "type": "UUID",
                        "value": new_uuid,
                        "name": name,
                    },
                }
            )

        resp = self.session.put(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}",
            json={"memberships": memberships},
        )
        resp.raise_for_status()

    def rename_member(self, tricount: Tricount, member: Member, new_name: str) -> None:
        """Rename a member"""
        self._ensure_authenticated()

        # Build full membership list with updated name
        memberships = []
        for m in tricount.members:
            name = new_name if m.uuid == member.uuid else m.display_name
            memberships.append(
                {
                    "uuid": m.uuid,
                    "status": "ACTIVE",
                    "auto_add_card_transaction": "",
                    "setting": None,
                    "alias": {
                        "type": "UUID",
                        "value": m.uuid,
                        "name": name,
                    },
                }
            )

        resp = self.session.put(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}",
            json={"memberships": memberships},
        )
        resp.raise_for_status()

    def delete_member(self, tricount: Tricount, member: Member) -> None:
        """
        Delete a member from a tricount.

        Note: Members with existing transactions cannot be fully deleted;
        they will be marked as DELETED but remain in the data.

        Args:
            tricount: The tricount containing the member
            member: The member to delete
        """
        self._ensure_authenticated()

        # Build membership list excluding the deleted member, and include deleted_membership_ids
        memberships = []
        for m in tricount.members:
            if m.uuid != member.uuid:
                memberships.append(
                    {
                        "uuid": m.uuid,
                        "status": m.status,
                        "auto_add_card_transaction": "",
                        "setting": None,
                        "alias": {
                            "type": "UUID",
                            "value": m.uuid,
                            "name": m.display_name,
                        },
                    }
                )

        resp = self.session.put(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}",
            json={
                "memberships": memberships,
                "deleted_membership_ids": [member.id],
            },
        )
        resp.raise_for_status()

    def link_to_member(self, tricount: Tricount, member: Member) -> None:
        """
        Link your account to a member in the tricount.

        This makes you "become" that member in the tricount. The Tricount app
        uses this to identify which member you are when you open a shared tricount.

        Args:
            tricount: The tricount to update
            member: The member to link your account to
        """
        self._ensure_authenticated()
        resp = self.session.put(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}",
            json={"membership_uuid_active": member.uuid},
        )
        resp.raise_for_status()

    # -------------------------------------------------------------------------
    # Transaction Operations
    # -------------------------------------------------------------------------

    def create_transaction(
        self,
        tricount: Tricount,
        description: str,
        amount: float,
        payer: Member,
        split_among: list[Member],
        category: Optional[Category] = None,
        category_custom: Optional[str] = None,
        date: Optional[datetime] = None,
        transaction_type: TransactionType = TransactionType.NORMAL,
        attachment_ids: Optional[list[int]] = None,
        currency: Optional[str] = None,
        exchange_rate: Optional[float] = None,
    ) -> int:
        """
        Create a new transaction.

        Args:
            tricount: The tricount to add the transaction to
            description: What was purchased
            amount: Total amount spent (as positive number)
            payer: Who paid
            split_among: Members to split the cost among
            category: Standard category from Category enum (optional)
            category_custom: Custom category as "label emoji" string (e.g., "Coffee ☕️").
                           If provided, category is automatically set to OTHER.
            date: Transaction date (defaults to now)
            transaction_type: NORMAL, INCOME, or BALANCE
            attachment_ids: List of attachment IDs from upload_transaction_attachment()
            currency: Original currency if different from tricount currency (e.g., "USD")
            exchange_rate: Exchange rate to tricount currency (e.g., 150 for 1 USD = 150 JPY)

        Returns:
            The ID of the created transaction
        """
        self._ensure_authenticated()

        if date is None:
            date = datetime.now()

        # Determine currencies and exchange rate
        local_currency = currency if currency else tricount.currency
        if currency and currency != tricount.currency:
            # Foreign currency - get or fetch exchange rate
            if exchange_rate:
                rate = exchange_rate
            else:
                rate = self.get_exchange_rate(currency, tricount.currency)
        else:
            rate = 1.0

        # Calculate amounts in both currencies
        amount_in_tricount_currency = amount * rate if currency else amount
        amount_per_person_local = round(amount / len(split_among), 2)
        amount_per_person_tricount = round(amount_in_tricount_currency / len(split_among), 2)

        allocations = []
        for member in split_among:
            alloc = {
                "membership_uuid": member.uuid,
                "amount": {
                    "value": str(-amount_per_person_tricount),
                    "currency": tricount.currency,
                },
                "type": "AMOUNT",
            }
            if currency:
                alloc["amount_local"] = {
                    "value": str(-amount_per_person_local),
                    "currency": local_currency,
                }
            allocations.append(alloc)

        payload = {
            "uuid": str(uuid.uuid4()),
            "description": description,
            "amount": {
                "value": str(-amount_in_tricount_currency),
                "currency": tricount.currency,
            },
            "membership_uuid_owner": payer.uuid,
            "allocations": allocations,
            "type_transaction": transaction_type.value,
            "status": "ACTIVE",
            "date": date.strftime("%Y-%m-%d %H:%M:%S.%f"),
        }

        if currency:
            payload["amount_local"] = {
                "value": str(-amount),
                "currency": local_currency,
            }
            payload["exchange_rate"] = str(rate)

        if category_custom:
            # Custom category: set category to OTHER and category_custom to "label emoji"
            payload["category"] = "OTHER"
            payload["category_custom"] = category_custom
        elif category:
            payload["category"] = category.value
        if attachment_ids:
            payload["attachment"] = [{"id": aid} for aid in attachment_ids]

        resp = self.session.post(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/registry-entry",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["Response"][0]["Id"]["id"]

    def create_transaction_custom_split(
        self,
        tricount: Tricount,
        description: str,
        amount: float,
        payer: Member,
        allocations: list[tuple[Member, float]],
        category: Optional[Category] = None,
        category_custom: Optional[str] = None,
        date: Optional[datetime] = None,
        attachment_ids: Optional[list[int]] = None,
    ) -> int:
        """
        Create a transaction with custom split amounts.

        Args:
            tricount: The tricount
            description: What was purchased
            amount: Total amount (as positive number)
            payer: Who paid
            allocations: List of (member, amount) tuples with positive amounts
            category: Standard category from Category enum (optional)
            category_custom: Custom category as "label emoji" string (e.g., "Coffee ☕️")
            date: Transaction date
            attachment_ids: List of attachment IDs from upload_transaction_attachment()

        Returns:
            The ID of the created transaction
        """
        self._ensure_authenticated()

        if date is None:
            date = datetime.now()

        alloc_list = []
        for member, alloc_amount in allocations:
            alloc_list.append(
                {
                    "membership_uuid": member.uuid,
                    "amount": {
                        "value": str(-alloc_amount),  # Negative for expenses
                        "currency": tricount.currency,
                    },
                    "type": "AMOUNT",
                }
            )

        payload = {
            "uuid": str(uuid.uuid4()),
            "description": description,
            "amount": {
                "value": str(-amount),
                "currency": tricount.currency,
            },  # Negative for expenses
            "membership_uuid_owner": payer.uuid,
            "allocations": alloc_list,
            "type_transaction": "NORMAL",
            "status": "ACTIVE",
            "date": date.strftime("%Y-%m-%d %H:%M:%S.%f"),
        }

        if category_custom:
            payload["category"] = "OTHER"
            payload["category_custom"] = category_custom
        elif category:
            payload["category"] = category.value
        if attachment_ids:
            payload["attachment"] = [{"id": aid} for aid in attachment_ids]

        resp = self.session.post(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/registry-entry",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["Response"][0]["Id"]["id"]

    def delete_transaction(self, tricount: Tricount, transaction_id: int) -> None:
        """Delete a transaction"""
        self._ensure_authenticated()
        resp = self.session.delete(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/registry-entry/{transaction_id}",
        )
        resp.raise_for_status()

    def create_income(
        self,
        tricount: Tricount,
        description: str,
        amount: float,
        receiver: Member,
        split_among: list[Member],
        category: Optional[Category] = None,
        category_custom: Optional[str] = None,
        date: Optional[datetime] = None,
        attachment_ids: Optional[list[int]] = None,
    ) -> int:
        """
        Create an income transaction.

        Income transactions represent money received by the group (e.g., refunds,
        lottery winnings, sold items). The receiver gets the income, and it's
        split among members as credit.

        Args:
            tricount: The tricount to add the transaction to
            description: What the income is for
            amount: Total amount received (as positive number)
            receiver: Who received the money
            split_among: Members to split the income among
            category: Standard category from Category enum (optional)
            category_custom: Custom category as "label emoji" string (e.g., "Coffee ☕️")
            date: Transaction date (defaults to now)
            attachment_ids: List of attachment IDs

        Returns:
            The ID of the created transaction
        """
        self._ensure_authenticated()

        if date is None:
            date = datetime.now()

        # Calculate split - income uses positive amounts
        split_count = len(split_among)
        amount_per_person = round(amount / split_count, 2)

        allocations = []
        for member in split_among:
            allocations.append(
                {
                    "membership_uuid": member.uuid,
                    "amount": {
                        "value": str(amount_per_person),  # Positive for income
                        "currency": tricount.currency,
                    },
                    "type": "AMOUNT",
                }
            )

        payload = {
            "uuid": str(uuid.uuid4()),
            "description": description,
            "amount": {
                "value": str(amount),
                "currency": tricount.currency,
            },  # Positive for income
            "membership_uuid_owner": receiver.uuid,
            "allocations": allocations,
            "type_transaction": TransactionType.INCOME.value,
            "status": "ACTIVE",
            "date": date.strftime("%Y-%m-%d %H:%M:%S.%f"),
        }

        if category_custom:
            payload["category"] = "OTHER"
            payload["category_custom"] = category_custom
        elif category:
            payload["category"] = category.value
        if attachment_ids:
            payload["attachment"] = [{"id": aid} for aid in attachment_ids]

        resp = self.session.post(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/registry-entry",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["Response"][0]["Id"]["id"]

    def create_transaction_ratio_split(
        self,
        tricount: Tricount,
        description: str,
        amount: float,
        payer: Member,
        split_ratios: list[tuple[Member, int]],
        category: Optional[Category] = None,
        category_custom: Optional[str] = None,
        date: Optional[datetime] = None,
        attachment_ids: Optional[list[int]] = None,
        currency: Optional[str] = None,
        exchange_rate: Optional[float] = None,
    ) -> int:
        """
        Create a transaction with ratio-based split.

        Instead of fixed amounts, each member's share is determined by their
        ratio relative to the total. E.g., ratios [1, 2, 1] means the second
        person pays twice as much as the others.

        Args:
            tricount: The tricount to add the transaction to
            description: What was purchased
            amount: Total amount spent (as positive number)
            payer: Who paid
            split_ratios: List of (member, ratio) tuples. Ratios are relative.
            category: Standard category from Category enum (optional)
            category_custom: Custom category as "label emoji" string (e.g., "Coffee ☕️")
            date: Transaction date (defaults to now)
            attachment_ids: List of attachment IDs
            currency: Original currency if different from tricount currency
            exchange_rate: Exchange rate to tricount currency

        Returns:
            The ID of the created transaction

        Example:
            # Split 1000 JPY: Alex pays 250, Kondo pays 500, Bot pays 250
            create_transaction_ratio_split(
                tricount, "Dinner", 1000, alex,
                [(alex, 1), (kondo, 2), (bot, 1)]
            )
        """
        self._ensure_authenticated()

        if date is None:
            date = datetime.now()

        # Determine currencies and exchange rate
        local_currency = currency if currency else tricount.currency
        if currency and currency != tricount.currency:
            if exchange_rate:
                rate = exchange_rate
            else:
                rate = self.get_exchange_rate(currency, tricount.currency)
        else:
            rate = 1.0

        amount_in_tricount_currency = amount * rate if currency else amount

        # Calculate total ratio
        total_ratio = sum(ratio for _, ratio in split_ratios)

        allocations = []
        for member, ratio in split_ratios:
            member_amount = round(amount_in_tricount_currency * ratio / total_ratio, 2)
            alloc = {
                "membership_uuid": member.uuid,
                "amount": {
                    "value": str(-member_amount),  # Negative for expenses
                    "currency": tricount.currency,
                },
                "type": "RATIO",
                "share_ratio": ratio,
            }
            if currency:
                member_amount_local = round(amount * ratio / total_ratio, 2)
                alloc["amount_local"] = {
                    "value": str(-member_amount_local),
                    "currency": local_currency,
                }
            allocations.append(alloc)

        payload = {
            "uuid": str(uuid.uuid4()),
            "description": description,
            "amount": {
                "value": str(-amount_in_tricount_currency),
                "currency": tricount.currency,
            },
            "membership_uuid_owner": payer.uuid,
            "allocations": allocations,
            "type_transaction": TransactionType.NORMAL.value,
            "status": "ACTIVE",
            "date": date.strftime("%Y-%m-%d %H:%M:%S.%f"),
        }

        if currency:
            payload["amount_local"] = {
                "value": str(-amount),
                "currency": local_currency,
            }
            payload["exchange_rate"] = str(rate)

        if category_custom:
            payload["category"] = "OTHER"
            payload["category_custom"] = category_custom
        elif category:
            payload["category"] = category.value
        if attachment_ids:
            payload["attachment"] = [{"id": aid} for aid in attachment_ids]

        resp = self.session.post(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/registry-entry",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["Response"][0]["Id"]["id"]

    def create_reimbursement(
        self,
        tricount: Tricount,
        payer: Member,
        receiver: Member,
        amount: float,
        description: str = "Reimbursement",
        date: Optional[datetime] = None,
    ) -> int:
        """
        Create a reimbursement (transfer between members).

        This records that one member paid back another member directly.

        Args:
            tricount: The tricount
            payer: Member who is paying (the borrower paying back)
            receiver: Member who receives the money (the creditor)
            amount: Amount being transferred
            description: Description (default: "Reimbursement")
            date: Transaction date (defaults to now)

        Returns:
            The ID of the created transaction
        """
        self._ensure_authenticated()

        if date is None:
            date = datetime.now()

        payload = {
            "uuid": str(uuid.uuid4()),
            "description": description,
            "amount": {"value": str(amount), "currency": tricount.currency},
            "membership_uuid_owner": payer.uuid,
            "allocations": [
                {
                    "membership_uuid": receiver.uuid,
                    "amount": {"value": str(amount), "currency": tricount.currency},
                    "type": "AMOUNT",
                },
                {
                    "membership_uuid": payer.uuid,
                    "amount": {"value": "0", "currency": tricount.currency},
                    "type": "AMOUNT",
                },
            ],
            "type_transaction": TransactionType.BALANCE.value,
            "status": "ACTIVE",
            "date": date.strftime("%Y-%m-%d %H:%M:%S.%f"),
        }

        resp = self.session.post(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/registry-entry",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["Response"][0]["Id"]["id"]

    def edit_transaction(
        self,
        tricount: Tricount,
        transaction_id: int,
        description: Optional[str] = None,
        amount: Optional[float] = None,
        payer: Optional[Member] = None,
        split_among: Optional[list[Member]] = None,
        category: Optional[Category] = None,
        category_custom: Optional[str] = None,
        date: Optional[datetime] = None,
    ) -> None:
        """
        Edit an existing transaction.

        Args:
            tricount: The tricount containing the transaction
            transaction_id: ID of the transaction to edit
            description: New description (optional)
            amount: New total amount (optional)
            payer: New payer (optional)
            split_among: New list of members to split among (optional)
            category: Standard category from Category enum (optional)
            category_custom: Custom category as "label emoji" string (e.g., "Coffee ☕️")
            date: New transaction date (optional)

        Note: If amount or split_among is changed, both should be provided together.
        """
        self._ensure_authenticated()

        # Find the existing transaction
        tx = None
        for t in tricount.transactions:
            if t.id == transaction_id:
                tx = t
                break
        if not tx:
            raise ValueError(f"Transaction {transaction_id} not found in tricount")

        # Build the payload, using existing values as defaults
        new_description = description if description is not None else tx.description
        new_amount = amount if amount is not None else float(tx.amount.value)
        new_payer = (
            payer if payer is not None else tricount.get_member_by_uuid(tx.membership_uuid_owner)
        )
        new_date = (
            date
            if date is not None
            else datetime.strptime(tx.date.split(".")[0], "%Y-%m-%d %H:%M:%S")
        )

        if not new_payer:
            raise ValueError("Could not determine payer")

        # Build allocations
        if split_among is not None:
            amount_per_person = round(new_amount / len(split_among), 2)
            allocations = [
                {
                    "membership_uuid": m.uuid,
                    "amount": {
                        "value": str(amount_per_person),
                        "currency": tricount.currency,
                    },
                    "type": "AMOUNT",
                }
                for m in split_among
            ]
        elif amount is not None:
            # Amount changed but split_among not specified - reuse existing allocation members
            existing_members = [
                tricount.get_member_by_uuid(a.membership_uuid)
                for a in tx.allocations
                if tricount.get_member_by_uuid(a.membership_uuid)
            ]
            if existing_members:
                amount_per_person = round(new_amount / len(existing_members), 2)
                allocations = [
                    {
                        "membership_uuid": m.uuid,
                        "amount": {
                            "value": str(amount_per_person),
                            "currency": tricount.currency,
                        },
                        "type": "AMOUNT",
                    }
                    for m in existing_members
                ]
            else:
                allocations = [a.to_dict() for a in tx.allocations]
        else:
            # Keep existing allocations
            allocations = [a.to_dict() for a in tx.allocations]

        payload = {
            "description": new_description,
            "amount": {"value": str(new_amount), "currency": tricount.currency},
            "membership_uuid_owner": new_payer.uuid,
            "allocations": allocations,
            "type_transaction": tx.transaction_type.value,
            "status": tx.status.value,
            "date": new_date.strftime("%Y-%m-%d %H:%M:%S.%f"),
        }

        # Add category fields
        if category_custom is not None:
            # Custom category: set category to OTHER
            payload["category"] = "OTHER"
            payload["category_custom"] = category_custom
        elif category is not None:
            payload["category"] = category.value
            payload["category_custom"] = ""  # Clear custom category
        else:
            # Keep existing
            if tx.category:
                payload["category"] = tx.category
            if tx.category_custom:
                payload["category_custom"] = tx.category_custom

        resp = self.session.put(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/registry-entry/{transaction_id}",
            json=payload,
        )
        resp.raise_for_status()

    def add_transaction_attachment(
        self,
        tricount: Tricount,
        transaction_id: int,
        attachment_id: int,
    ) -> None:
        """
        Add an attachment to an existing transaction.

        Args:
            tricount: The tricount containing the transaction
            transaction_id: ID of the transaction
            attachment_id: ID of the attachment (from upload_transaction_attachment)
        """
        self._ensure_authenticated()

        # Find the transaction to get current state
        tx = None
        for t in tricount.transactions:
            if t.id == transaction_id:
                tx = t
                break
        if not tx:
            raise ValueError(f"Transaction {transaction_id} not found")

        # Get current attachments from raw data
        resp = self.session.get(
            f"{BASE_URL}/v1/user/{self.user_id}/registry",
            params={"public_identifier_token": tricount.public_identifier_token},
        )
        resp.raise_for_status()
        data = resp.json()

        current_attachments = []
        for entry in data["Response"][0]["Registry"].get("all_registry_entry", []):
            if entry.get("RegistryEntry", {}).get("id") == transaction_id:
                current_attachments = [
                    {"id": a["id"]} for a in entry["RegistryEntry"].get("attachment", [])
                ]
                break

        # Add new attachment
        current_attachments.append({"id": attachment_id})

        # Build update payload
        payer = tricount.get_member_by_uuid(tx.membership_uuid_owner)
        payload = {
            "description": tx.description,
            "amount": tx.amount.to_dict(),
            "membership_uuid_owner": tx.membership_uuid_owner,
            "allocations": [a.to_dict() for a in tx.allocations],
            "type_transaction": tx.transaction_type.value,
            "status": tx.status.value,
            "date": tx.date,
            "attachment": current_attachments,
        }

        if tx.category:
            payload["category"] = tx.category
        if tx.category_custom:
            payload["category_custom"] = tx.category_custom

        resp = self.session.put(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/registry-entry/{transaction_id}",
            json=payload,
        )
        resp.raise_for_status()

    def remove_transaction_attachment(
        self,
        tricount: Tricount,
        transaction_id: int,
        attachment_id: int,
    ) -> None:
        """
        Remove an attachment from a transaction.

        Args:
            tricount: The tricount containing the transaction
            transaction_id: ID of the transaction
            attachment_id: ID of the attachment to remove
        """
        self._ensure_authenticated()

        # Find the transaction
        tx = None
        for t in tricount.transactions:
            if t.id == transaction_id:
                tx = t
                break
        if not tx:
            raise ValueError(f"Transaction {transaction_id} not found")

        # Get current attachments
        resp = self.session.get(
            f"{BASE_URL}/v1/user/{self.user_id}/registry",
            params={"public_identifier_token": tricount.public_identifier_token},
        )
        resp.raise_for_status()
        data = resp.json()

        current_attachments = []
        for entry in data["Response"][0]["Registry"].get("all_registry_entry", []):
            if entry.get("RegistryEntry", {}).get("id") == transaction_id:
                current_attachments = [
                    {"id": a["id"]}
                    for a in entry["RegistryEntry"].get("attachment", [])
                    if a["id"] != attachment_id  # Exclude the one to remove
                ]
                break

        # Build update payload
        payload = {
            "description": tx.description,
            "amount": tx.amount.to_dict(),
            "membership_uuid_owner": tx.membership_uuid_owner,
            "allocations": [a.to_dict() for a in tx.allocations],
            "type_transaction": tx.transaction_type.value,
            "status": tx.status.value,
            "date": tx.date,
            "attachment": current_attachments,
        }

        if tx.category:
            payload["category"] = tx.category
        if tx.category_custom:
            payload["category_custom"] = tx.category_custom

        resp = self.session.put(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/registry-entry/{transaction_id}",
            json=payload,
        )
        resp.raise_for_status()

    # -------------------------------------------------------------------------
    # Settlement Operations
    # -------------------------------------------------------------------------
    # Exchange Rate Operations
    # -------------------------------------------------------------------------

    def get_exchange_rates(self, from_currency: str) -> dict[str, float]:
        """
        Get exchange rates from a source currency to all other currencies.

        Args:
            from_currency: Source currency code (e.g., "USD", "EUR")

        Returns:
            Dictionary mapping target currency codes to exchange rates
        """
        self._ensure_authenticated()
        resp = self.session.get(
            f"{BASE_URL}/v1/user/{self.user_id}/exchange-rate",
            params={"currency": from_currency},
        )
        resp.raise_for_status()
        data = resp.json()

        rates = {}
        for item in data.get("Response", []):
            if "ExchangeRate" in item:
                rate_data = item["ExchangeRate"]
                target = rate_data.get("currency_target", "")
                rate = float(rate_data.get("rate", 0))
                rates[target] = rate

        return rates

    def get_exchange_rate(self, from_currency: str, to_currency: str) -> float:
        """
        Get exchange rate between two currencies.

        Args:
            from_currency: Source currency code (e.g., "USD")
            to_currency: Target currency code (e.g., "JPY")

        Returns:
            Exchange rate (multiply from_currency amount by this to get to_currency amount)
        """
        rates = self.get_exchange_rates(from_currency)
        if to_currency not in rates:
            raise ValueError(f"Exchange rate not found for {from_currency} -> {to_currency}")
        return rates[to_currency]

    # -------------------------------------------------------------------------
    # Convenience Methods
    # -------------------------------------------------------------------------

    def get_custom_categories(self, tricount: Tricount) -> list[str]:
        """
        Get all unique custom categories used in a tricount's transactions.

        Custom categories are stored as "Label Emoji" strings in the
        category_custom field (e.g., "Coffee ☕️", "Game Night 🎲").

        Args:
            tricount: The tricount to get custom categories from

        Returns:
            List of unique custom category strings, sorted alphabetically
        """
        custom_cats = set()
        for tx in tricount.transactions:
            if tx.category_custom:
                custom_cats.add(tx.category_custom)
        return sorted(custom_cats)

    def get_balances(self, tricount: Tricount) -> dict[str, float]:
        """
        Calculate current balances for all members.

        Returns dict of member_name -> balance (positive = owed money, negative = owes money)

        Note: The API stores expenses as negative amounts and income as positive.
        This method uses absolute values for consistent calculation.
        """
        balances: dict[str, float] = {m.display_name: 0.0 for m in tricount.members}

        for tx in tricount.transactions:
            if tx.status != TransactionStatus.ACTIVE:
                continue

            payer = tricount.get_member_by_uuid(tx.membership_uuid_owner)
            if not payer:
                continue

            # Use absolute value since expenses are stored as negative
            total = abs(float(tx.amount.value))

            if tx.transaction_type == TransactionType.BALANCE:
                # Reimbursement/transfer: payer paid money to receiver
                balances[payer.display_name] += total  # Payer paid out

                # Find the receiver (the one with non-zero allocation)
                for alloc in tx.allocations:
                    alloc_amount = abs(float(alloc.amount.value))
                    if alloc_amount > 0:
                        member = tricount.get_member_by_uuid(alloc.membership_uuid)
                        if member:
                            balances[member.display_name] -= alloc_amount
            else:
                # Normal expense or income
                balances[payer.display_name] += total

                # Subtract each person's share (use absolute value)
                for alloc in tx.allocations:
                    member = tricount.get_member_by_uuid(alloc.membership_uuid)
                    if member:
                        balances[member.display_name] -= abs(float(alloc.amount.value))

        return balances

    # -------------------------------------------------------------------------
    # Settlement Operations
    # -------------------------------------------------------------------------

    def create_settlement(self, tricount: Tricount) -> int:
        """
        Create a settlement for a tricount.

        This calculates who owes whom based on all transactions and creates
        a settlement record. The settlement shows the optimal payment flow
        to settle all debts.

        Args:
            tricount: The tricount to settle

        Returns:
            The ID of the created settlement
        """
        self._ensure_authenticated()
        resp = self.session.post(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/registry-settlement",
            json={},
        )
        resp.raise_for_status()
        return resp.json()["Response"][0]["Id"]["id"]

    def get_settlement(self, tricount: Tricount, settlement_id: int) -> Settlement:
        """
        Get a settlement by ID.

        Args:
            tricount: The tricount containing the settlement
            settlement_id: The settlement ID

        Returns:
            Settlement object with payment items
        """
        self._ensure_authenticated()
        resp = self.session.get(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/registry-settlement/{settlement_id}",
        )
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("Response", []):
            if "RegistrySettlement" in item:
                settlement = Settlement.from_dict(item["RegistrySettlement"])
                settlement.id = settlement_id
                return settlement

        raise RuntimeError(f"Settlement {settlement_id} not found")

    # -------------------------------------------------------------------------
    # Gallery Attachment Operations
    # -------------------------------------------------------------------------

    def list_gallery_attachments(self, tricount: Tricount) -> list[GalleryAttachment]:
        """
        List all gallery attachments for a tricount.

        Args:
            tricount: The tricount

        Returns:
            List of GalleryAttachment objects
        """
        self._ensure_authenticated()
        resp = self.session.get(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/gallery-attachment",
        )
        resp.raise_for_status()
        data = resp.json()

        attachments = []
        for item in data.get("Response", []):
            if "RegistryGalleryAttachment" in item:
                attachments.append(GalleryAttachment.from_dict(item["RegistryGalleryAttachment"]))
        return attachments

    def upload_gallery_attachment(
        self,
        tricount: Tricount,
        file_path: Path,
        content_type: Optional[str] = None,
    ) -> str:
        """
        Upload an image to the tricount gallery.

        Args:
            tricount: The tricount
            file_path: Path to the image file
            content_type: MIME type (auto-detected if not provided)

        Returns:
            UUID of the uploaded attachment
        """
        self._ensure_authenticated()

        # Auto-detect content type from extension
        if content_type is None:
            ext = file_path.suffix.lower()
            content_types = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            content_type = content_types.get(ext, "application/octet-stream")

        attachment_uuid = str(uuid.uuid4())

        with open(file_path, "rb") as f:
            file_data = f.read()

        resp = self.session.post(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/gallery-attachment/{attachment_uuid}",
            data=file_data,
            headers={
                "Content-Type": content_type,
                "X-Bunq-Attachment-Description": "",
            },
        )
        resp.raise_for_status()

        # Response contains UUID confirmation
        data = resp.json()
        for item in data.get("Response", []):
            if "UUID" in item:
                return item["UUID"]["uuid"]

        return attachment_uuid

    def delete_gallery_attachment(self, tricount: Tricount, attachment_uuid: str) -> None:
        """
        Delete a gallery attachment.

        Args:
            tricount: The tricount
            attachment_uuid: UUID of the attachment to delete
        """
        self._ensure_authenticated()
        resp = self.session.delete(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/gallery-attachment/{attachment_uuid}",
        )
        resp.raise_for_status()

    # -------------------------------------------------------------------------
    # Transaction Attachment Operations
    # -------------------------------------------------------------------------

    def upload_transaction_attachment(
        self,
        tricount: Tricount,
        file_path: Path,
        content_type: Optional[str] = None,
    ) -> int:
        """
        Upload an attachment for use with transactions (e.g., receipt photo).

        After uploading, include the returned ID in the transaction's attachment field.

        Args:
            tricount: The tricount
            file_path: Path to the image file
            content_type: MIME type (auto-detected if not provided)

        Returns:
            ID of the uploaded attachment
        """
        self._ensure_authenticated()

        # Auto-detect content type
        if content_type is None:
            ext = file_path.suffix.lower()
            content_types = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            content_type = content_types.get(ext, "application/octet-stream")

        with open(file_path, "rb") as f:
            file_data = f.read()

        resp = self.session.post(
            f"{BASE_URL}/v1/user/{self.user_id}/registry/{tricount.id}/attachment",
            data=file_data,
            headers={
                "Content-Type": content_type,
                "X-Bunq-Attachment-Description": "",
            },
        )
        resp.raise_for_status()
        return resp.json()["Response"][0]["Id"]["id"]

    # -------------------------------------------------------------------------
    # Synchronization Operations
    # -------------------------------------------------------------------------

    def sync_tricounts(
        self,
        active_tokens: Optional[list[str]] = None,
        archived_tokens: Optional[list[str]] = None,
    ) -> dict[str, list[Tricount]]:
        """
        Synchronize tricounts with the server.

        This is useful for efficiently fetching multiple tricounts at once.

        Args:
            active_tokens: List of public tokens for active tricounts
            archived_tokens: List of public tokens for archived tricounts

        Returns:
            Dictionary with keys 'active', 'archived', 'deleted', each containing
            a list of Tricount objects
        """
        self._ensure_authenticated()

        # Build request body
        all_registry_active = []
        if active_tokens:
            for token in active_tokens:
                all_registry_active.append({"public_identifier_token": token})

        all_registry_archived = []
        if archived_tokens:
            for token in archived_tokens:
                all_registry_archived.append({"public_identifier_token": token})

        resp = self.session.post(
            f"{BASE_URL}/v1/user/{self.user_id}/registry-synchronization",
            json={
                "all_registry_active": all_registry_active,
                "all_registry_archived": all_registry_archived,
                "all_registry_deleted": [],
            },
        )
        resp.raise_for_status()
        data = resp.json()

        result: dict[str, list[Tricount]] = {
            "active": [],
            "archived": [],
            "deleted": [],
        }

        for item in data.get("Response", []):
            if "RegistrySynchronization" in item:
                sync_data = item["RegistrySynchronization"]

                # Registries are directly in the lists (not wrapped)
                for reg in sync_data.get("all_registry_active", []):
                    result["active"].append(Tricount.from_dict(reg))

                for reg in sync_data.get("all_registry_archived", []):
                    result["archived"].append(Tricount.from_dict(reg))

                for reg in sync_data.get("all_registry_deleted", []):
                    result["deleted"].append(Tricount.from_dict(reg))

        return result


# =============================================================================
# Convenience Functions
# =============================================================================


def load_client(
    credentials_path: str | Path = "tricount_credentials.json",
) -> TricountAPI:
    """Load credentials and create an authenticated client"""
    credentials_path = Path(credentials_path)
    if credentials_path.exists():
        creds = Credentials.load(credentials_path)
    else:
        creds = Credentials.generate()
        creds.save(credentials_path)

    client = TricountAPI(creds)
    client.authenticate()
    return client
