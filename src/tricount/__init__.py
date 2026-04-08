"""
Tricount API Client

An unofficial Python client for the Tricount (bunq) API.
Based on reverse engineering of the bunq Tricount Android app.

Basic usage:
    from tricount import load_client

    # Create authenticated client (auto-generates credentials on first use)
    client = load_client()

    # Join a tricount using its sharing link
    tricount = client.join_tricount("tABC123xyz")

    # Access transactions
    for tx in tricount.transactions:
        print(f"{tx.description}: {tx.amount.as_abs} {tx.amount.currency}")
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
