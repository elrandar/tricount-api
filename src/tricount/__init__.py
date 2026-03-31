"""
Tricount API Client

An unofficial Python client for the Tricount (bunq) API.
Based on reverse engineering of the bunq Tricount Android app.

Basic usage:
    from tricount import TricountAPI, load_client

    # First time - authenticate with device confirmation
    api = TricountAPI()
    api.register("your_email@example.com")
    # Check email for confirmation code
    api.confirm_device("123456")
    api.save_credentials("credentials.json")

    # Later - load saved credentials
    api = load_client("credentials.json")

    # Get your tricounts
    tricounts = api.list_tricounts()
"""

from tricount.client import (
    # Enums
    AllocationType,
    Category,
    MemberStatus,
    PaymentStatus,
    TransactionStatus,
    TransactionType,
    TricountStatus,
    # Data classes
    Allocation,
    Amount,
    AttachmentUrl,
    Credentials,
    GalleryAttachment,
    Member,
    Settlement,
    SettlementItem,
    Transaction,
    Tricount,
    # Main client
    TricountAPI,
    # Convenience function
    load_client,
)

__version__ = "0.1.0"

__all__ = [
    # Version
    "__version__",
    # Enums
    "TricountStatus",
    "MemberStatus",
    "PaymentStatus",
    "TransactionType",
    "TransactionStatus",
    "AllocationType",
    "Category",
    # Data classes
    "Amount",
    "Member",
    "Allocation",
    "Transaction",
    "SettlementItem",
    "Settlement",
    "AttachmentUrl",
    "GalleryAttachment",
    "Tricount",
    "Credentials",
    # Main client
    "TricountAPI",
    # Convenience function
    "load_client",
]
