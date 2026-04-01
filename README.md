# Tricount API Client

An unofficial Python client for the Tricount (bunq) API, reverse-engineered from the Android app.

## Features

- Full read/write access to Tricount data
- Create, edit, and delete transactions
- Manage members and splits
- Support for custom categories, foreign currencies, and attachments
- **No account linking required** - just needs the sharing link to modify any tricount

## Installation

```bash
pip install tricount-api
```

## Quick Start

```python
from tricount import load_client

# Create an authenticated client (auto-generates credentials on first use)
client = load_client()

# Join any tricount using its sharing link - no need to be a member!
tricount = client.join_tricount("tABC123xyz")

print(f"Tricount: {tricount.title}")
print(f"Members: {[m.display_name for m in tricount.members]}")

# Create a transaction (as any member)
client.create_transaction(
    tricount=tricount,
    description="Dinner",
    amount=5000,
    payer=tricount.members[0],
    split_among=tricount.members
)
```

## Authentication

The API uses device-based authentication. On first use, credentials are automatically generated and saved to `tricount_credentials.json`. These credentials are reused for subsequent sessions.

```python
from pathlib import Path
from tricount import Credentials, TricountAPI

# Manual credential management
creds = Credentials.generate()
creds.save(Path("my_credentials.json"))

# Or load existing credentials
creds = Credentials.load(Path("my_credentials.json"))

# Create and authenticate client
client = TricountAPI(creds)
user_id = client.authenticate()
```

## Core Concepts

### Tricount Structure

- **Tricount**: An expense group with members and transactions
- **Member**: A participant in the tricount (identified by UUID)
- **Transaction**: An expense, income, or reimbursement
- **Allocation**: How a transaction is split among members

### Amount Convention

- **Expenses**: Stored as **negative** amounts (e.g., `-1000` for a ¥1000 expense)
- **Income**: Stored as **positive** amounts
- **The client handles this automatically** - you always pass positive amounts

### Transaction Types

| Type | Description | Amount Sign |
|------|-------------|-------------|
| `NORMAL` | Regular expense (someone paid for something) | Negative |
| `INCOME` | Money received by the group (refunds, etc.) | Positive |
| `BALANCE` | Reimbursement between members | Positive |

## Usage Examples

### Joining a Tricount

The API allows you to join and modify **any tricount** using just its sharing link.
You don't need to be an existing member - anyone with the link can make changes.

```python
# Join a tricount by its sharing token (from the URL: tricount.com/tXXXXX)
tricount = client.join_tricount("tABC123xyz")

# Now you can create/edit/delete transactions as any member
# The bot doesn't need to be added as a member
client.create_transaction(
    tricount=tricount,
    description="Coffee",
    amount=500,
    payer=tricount.members[0],  # Pay as any existing member
    split_among=tricount.members
)
```

### Managing Tricounts

```python
# Create a new tricount
tricount_id = client.create_tricount(
    title="Trip to Tokyo",
    currency="JPY",
    description="Summer vacation expenses"
)

# List all tricounts synced to your account
tricounts = client.list_tricounts()

# Read-only access (without joining)
tricount = client.get_tricount("tXXXXX")

# Update tricount metadata
client.update_tricount(tricount, title="Tokyo 2024", emoji="🗼")

# Archive/unarchive
client.archive_tricount(tricount)
client.unarchive_tricount(tricount)

# Leave a tricount (remove from your synced list, doesn't delete it)
client.leave_tricount(tricount)

# Delete permanently (only for tricounts you created)
client.delete_tricount(tricount)
```

### Managing Members

```python
# Add members
client.add_members(tricount, ["Alice", "Bob", "Charlie"])

# Rename a member
alice = tricount.get_member_by_name("Alice")
client.rename_member(tricount, alice, "Alice Smith")

# Delete a member (only works if they have no transactions)
client.delete_member(tricount, alice)

# When you join a tricount, you're auto-linked to the first member
tricount = client.join_tricount("tXXXXX")
print(f"Auto-linked to: {tricount.linked_member.display_name}")

# Switch to a different member
client.link_to_member(tricount, bob)

# Check who you're linked to
tricount = client.get_tricount_by_id(tricount.id)  # Refresh to get membership
if tricount.linked_member:
    print(f"I am: {tricount.linked_member.display_name}")

# Note: You can create transactions as any member, regardless of who you're linked to
# The link is just used by the Tricount app to show "your" balance
# Once linked, you can only switch members, not unlink completely
```

### Creating Expenses

```python
from tricount import Category

# Simple expense split equally
alice = tricount.get_member_by_name("Alice")
bob = tricount.get_member_by_name("Bob")

tx_id = client.create_transaction(
    tricount=tricount,
    description="Dinner at restaurant",
    amount=5000,  # Always positive
    payer=alice,
    split_among=[alice, bob],
    category=Category.FOOD_AND_DRINK,
)

# Custom split (unequal amounts)
tx_id = client.create_transaction_custom_split(
    tricount=tricount,
    description="Hotel room",
    amount=10000,
    payer=alice,
    allocations=[
        (alice, 3000),  # Alice pays 3000
        (bob, 7000),    # Bob pays 7000
    ],
)

# Ratio-based split
tx_id = client.create_transaction_ratio_split(
    tricount=tricount,
    description="Group activity",
    amount=9000,
    payer=alice,
    split_ratios=[
        (alice, 1),  # Alice: 1/4 = 2250
        (bob, 2),    # Bob: 2/4 = 4500
        (charlie, 1), # Charlie: 1/4 = 2250
    ],
)
```

### Income Transactions

```python
# Record income (e.g., refund, lottery, sold items)
tx_id = client.create_income(
    tricount=tricount,
    description="Tax refund",
    amount=3000,
    receiver=alice,  # Who received the money
    split_among=[alice, bob],  # Credit split among
)
```

### Reimbursements

```python
# Record a payment between members
tx_id = client.create_reimbursement(
    tricount=tricount,
    payer=bob,      # Bob pays back...
    receiver=alice, # ...to Alice
    amount=2500,
    description="Settling up",
)
```

### Foreign Currency

```python
# Auto-fetch exchange rate
tx_id = client.create_transaction(
    tricount=tricount,  # JPY tricount
    description="Coffee in NYC",
    amount=15,  # 15 USD
    payer=alice,
    split_among=[alice, bob],
    currency="USD",  # Original currency
)

# Manual exchange rate
tx_id = client.create_transaction(
    tricount=tricount,
    description="Souvenir",
    amount=100,  # 100 USD
    payer=alice,
    split_among=[alice, bob],
    currency="USD",
    exchange_rate=150,  # 1 USD = 150 JPY
)

# Get exchange rates
rates = client.get_exchange_rates("USD")
print(rates["JPY"])  # e.g., 149.5
```

### Editing & Deleting Transactions

```python
# Edit a transaction
client.edit_transaction(
    tricount=tricount,
    transaction_id=123,
    description="Updated description",
    amount=6000,
    category=Category.SHOPPING,
)

# Delete a transaction
client.delete_transaction(tricount, transaction_id=123)
```

### Attachments

#### Gallery Attachments (standalone images)

```python
from pathlib import Path

# Upload to gallery
attachment_uuid = client.upload_gallery_attachment(
    tricount,
    Path("receipt.jpg"),
)

# List gallery
attachments = client.list_gallery_attachments(tricount)
for att in attachments:
    print(f"{att.uuid}: {att.original_url}")

# Delete from gallery
client.delete_gallery_attachment(tricount, attachment_uuid)
```

#### Transaction Attachments (receipts linked to expenses)

```python
# Upload attachment
attachment_id = client.upload_transaction_attachment(
    tricount,
    Path("receipt.jpg"),
)

# Create transaction with attachment
tx_id = client.create_transaction(
    tricount=tricount,
    description="Groceries",
    amount=3500,
    payer=alice,
    split_among=[alice, bob],
    attachment_ids=[attachment_id],
)

# Add attachment to existing transaction
client.add_transaction_attachment(tricount, tx_id, attachment_id)

# Remove attachment from transaction
client.remove_transaction_attachment(tricount, tx_id, attachment_id)
```

### Calculating Balances

```python
# Get current balances
balances = client.get_balances(tricount)
for name, balance in balances.items():
    if balance > 0:
        print(f"{name} is owed {balance:.0f} {tricount.currency}")
    elif balance < 0:
        print(f"{name} owes {-balance:.0f} {tricount.currency}")
    else:
        print(f"{name} is settled up")
```

### Syncing Multiple Tricounts

```python
# Efficiently fetch multiple tricounts at once
result = client.sync_tricounts(
    active_tokens=["token1", "token2"],
    archived_tokens=["token3"],
)

for tc in result["active"]:
    print(f"Active: {tc.title}")
for tc in result["archived"]:
    print(f"Archived: {tc.title}")
```

## Categories

### Standard Categories

Available built-in expense categories (use with `Category` enum):

| Category | Emoji | Description |
|----------|-------|-------------|
| `TRAVEL` | 🛏 | Accommodation |
| `ENTERTAINMENT` | 🎤 | Entertainment |
| `GROCERIES` | 🛒 | Groceries |
| `HEALTHCARE` | 🦷 | Healthcare |
| `INSURANCE` | 🧯 | Insurance |
| `RENT_AND_UTILITIES` | 🏠 | Rent & Utilities |
| `FOOD_AND_DRINK` | 🍔 | Restaurants |
| `SHOPPING` | 🛍 | Shopping |
| `TRANSPORT` | 🚕 | Transport |
| `OTHER` | ✋ | Other |

```python
# Use a standard category
client.create_transaction(
    tricount=tricount,
    description="Taxi ride",
    amount=25.00,
    payer=alice,
    split_among=[alice, bob],
    category=Category.TRANSPORT,
)
```

### Custom Categories

You can create custom categories with a label and emoji. These are stored per-transaction using the `category_custom` parameter:

```python
# Use a custom category with label and emoji
client.create_transaction(
    tricount=tricount,
    description="Morning latte",
    amount=5.50,
    payer=alice,
    split_among=[alice, bob],
    category_custom="Coffee ☕️",  # Format: "Label Emoji"
)

# Another example
client.create_transaction(
    tricount=tricount,
    description="Board game night supplies",
    amount=30.00,
    payer=bob,
    split_among=[alice, bob],
    category_custom="Game Night 🎲",
)
```

When `category_custom` is provided, the category is automatically set to `OTHER` and the custom label+emoji is displayed in the app.

You can list all custom categories used in a tricount:

```python
# Get all unique custom categories from transactions
custom_cats = client.get_custom_categories(tricount)
for cat in custom_cats:
    print(cat)  # e.g., "Coffee ☕️", "Game Night 🎲"
```

## Data Classes

### Tricount

```python
@dataclass
class Tricount:
    id: int
    uuid: str
    title: str
    description: str
    currency: str
    public_identifier_token: str  # Sharing token
    members: list[Member]
    transactions: list[Transaction]
    emoji: Optional[str]
    category: Optional[str]
    status: str  # "READ_WRITE" or "READ_ONLY"
```

### Member

```python
@dataclass
class Member:
    id: int
    uuid: str
    display_name: str
    status: str  # "ACTIVE", "INACTIVE", "DELETED"
```

### Transaction

```python
@dataclass
class Transaction:
    id: Optional[int]
    uuid: str
    description: str
    amount: Amount
    membership_uuid_owner: str  # Who paid
    allocations: list[Allocation]
    date: str
    status: TransactionStatus
    transaction_type: TransactionType  # NORMAL, INCOME, BALANCE
    category: Optional[str]
    category_custom: Optional[str]
```

## API Limitations

Based on reverse engineering, some limitations were discovered:

1. **Immutable fields**: `description` and `currency` on tricounts can only be set at creation time
2. **Member deletion**: Members with transactions cannot be fully deleted; they become `DELETED` status but remain in data
3. **Settlement endpoints**: May require a bunq banking account (returns 404 for regular users)

## Error Handling

The client raises `requests.HTTPError` for API errors:

```python
try:
    tricount = client.get_tricount("invalid_token")
except requests.HTTPError as e:
    if e.response.status_code == 404:
        print("Tricount not found")
    else:
        print(f"API error: {e}")
```

## License

This is an unofficial client created through reverse engineering for educational purposes. Use responsibly and in accordance with Tricount's terms of service.
