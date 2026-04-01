# Tricount API Documentation

Reverse-engineered from the bunq Tricount Android app (v13.1.2, decompiled with jadx).

## Key Discovery

**Tricounts are fully open by design.** Anyone with a sharing link (`tricount.com/tXXXXX`) can:
- Read all transactions and members
- Create, edit, and delete transactions as any member
- The API client doesn't need to be added as a member

This is achieved by syncing the tricount to your session via `POST /v1/user/{userId}/registry-synchronization`.

## Base URL

```
https://api.tricount.bunq.com
```

## Authentication

Tricounts are public (no password), but apps must identify themselves before using the API.

### Required Headers (all requests)

| Header | Value | Notes |
|--------|-------|-------|
| `User-Agent` | `com.bunq.tricount.android:RELEASE:7.0.7:3174:ANDROID:13:C` | Mimics the official Android app |
| `app-id` | UUID | Unique per app installation, persist across requests |
| `X-Bunq-Client-Request-Id` | `049bfcdf-6ae4-4cee-af7b-45da31ea85d0` | Hardcoded constant from the app |
| `X-Bunq-Client-Authentication` | Token string | Added after authentication (see below) |

### Step 1: Generate Credentials

Generate once per "installation" and persist:

- **`app_id`**: A UUID (e.g. `uuid.uuid4()`)
- **RSA 2048-bit public key**: PEM format (PKCS1). The server requires it to be unique.

### Step 2: Register Session

```
POST /v1/session-registry-installation
Content-Type: application/json
```

**Request Body:**
```json
{
  "app_installation_uuid": "<your-uuid>",
  "client_public_key": "<rsa-public-key-pem>",
  "device_description": "Android"
}
```

**Response:**
```json
{
  "Response": [
    { "Token": { "token": "<auth-token-string>", ... } },
    { "UserPerson": { "id": <user-id-int>, "display_name": "tricount participant", "public_uuid": "...", ... } }
  ]
}
```

Extract:
- `Token.token` → use as `X-Bunq-Client-Authentication` header
- `UserPerson.id` → your user ID for subsequent requests

---

## Endpoints

### GET /v1/user/{userId}/registry

Fetch tricounts accessible to the authenticated user.

**Query Parameters (all optional):**

| Param | Description |
|-------|-------------|
| `public_identifier_token` | The tricount key from URL (e.g. `tABC123xyz`) |
| `registry_id` | Internal registry ID |
| *(none)* | Returns all tricounts for the user |

**Response:**
```json
{
  "Response": [
    {
      "Registry": {
        "id": 102257091,
        "uuid": "034d1734-...",
        "title": "Taiwan",
        "description": "...",
        "currency": "JPY",
        "emoji": null,
        "category": "GENERAL",
        "status": "READ_WRITE",
        "created": "2026-03-01 10:57:38.087586",
        "public_identifier_token": "tABC123xyz",
        "memberships": [...],
        "all_registry_entry": [...],
        ...
      }
    }
  ]
}
```

### POST /v1/user/{userId}/registry-synchronization

Sync tricounts to your account. This is the key endpoint that allows you to **join any tricount** 
using just its sharing token - no membership required. Once synced, you can create/edit/delete 
transactions as any member.

**Request Body:**
```json
{
  "all_registry_active": [
    { "public_identifier_token": "tABC123xyz" }
  ],
  "all_registry_archived": [],
  "all_registry_deleted": []
}
```

**Response:** Returns all synced tricounts with full data (same format as GET /registry).

**Notes:**
- Anyone with a sharing link can sync and modify the tricount
- The bot/client doesn't need to be added as a member
- You can sync multiple tricounts at once by adding multiple tokens to `all_registry_active`
- When joining, you're **auto-linked to the first member** (lowest ID) via `membership_uuid_active`
- Use `all_registry_deleted` to leave a tricount (remove from your synced list)

---

### POST /v1/user/{userId}/registry

Create a new tricount.

**Request Body:**
```json
{
  "currency": "JPY",
  "title": "My Tricount",
  "description": "Trip to Japan"
}
```

**Response:**
```json
{
  "Response": [{ "Id": { "id": 104488759 } }]
}
```

### DELETE /v1/user/{userId}/registry/{registryId}

Delete a tricount permanently.

**Request:** No body required.

**Response:**
```json
{
  "Response": [{ "Id": { "id": 104488759 } }]
}
```

### PUT /v1/user/{userId}/registry/{registryId}

Update tricount fields or manage memberships.

**Update tricount metadata:**
```json
{
  "title": "New Title",
  "emoji": "🍜",
  "category": "OTHER"
}
```

**Add new members:**
```json
{
  "memberships": [
    { "uuid": "<new-member-uuid-1>", "status": "ACTIVE" },
    { "uuid": "<new-member-uuid-2>", "status": "ACTIVE" }
  ]
}
```

**Rename members (update with full membership list):**
```json
{
  "memberships": [
    {
      "uuid": "<member-uuid>",
      "status": "ACTIVE",
      "auto_add_card_transaction": "",
      "setting": null,
      "alias": {
        "type": "UUID",
        "value": "<member-uuid>",
        "name": "Alice"
      }
    },
    {
      "uuid": "<another-member-uuid>",
      "status": "ACTIVE",
      "auto_add_card_transaction": "",
      "setting": null,
      "alias": {
        "type": "UUID",
        "value": "<another-member-uuid>",
        "name": "Bob"
      }
    }
  ]
}
```

**Archive/Unarchive tricount:**
```json
{
  "status": "READ_ONLY"
}
```
Use `READ_ONLY` to archive, `READ_WRITE` to unarchive.

**Delete members:**
```json
{
  "memberships": [
    { "uuid": "<remaining-member-uuid>", "status": "ACTIVE", ... }
  ],
  "deleted_membership_ids": [438275026]
}
```

**Link your account to a member:**
```json
{
  "membership_uuid_active": "<member-uuid>"
}
```
This sets which member "you are" in the tricount. The Tricount app uses this to show your balance.

**Notes:**
- Returns 200 with `{"Response": [{"Id": {"id": ...}}]}` on success
- `title` + `emoji` can be updated together
- `description` returns 200 but does NOT persist (set at creation only, like `currency`)
- `currency` is rejected as "superfluous" on PUT (set at creation only)
- **To rename members**: Send the full `memberships` array with `alias.name` set for each member
- **To delete members**: Include their IDs in `deleted_membership_ids` and omit them from `memberships`
- **To archive**: Set `status` to `READ_ONLY`
- **To link to a member**: Set `membership_uuid_active` to the member's UUID
- **Unlinking is not supported**: Once linked, you can only switch to another member

**Categories observed:** `GENERAL`, `OTHER`, `TRAVEL`, `FOOD_AND_DRINK`, `TRANSPORT`, `SHOPPING`, `ENTERTAINMENT`, `GROCERIES`

### GET /v1/user/{userId}/registry/{registryId}/registry-membership

List all memberships for a tricount.

**Response:**
```json
{
  "Response": [
    {
      "RegistryMembershipNonUser": {
        "id": 438275026,
        "uuid": "356493be-...",
        "alias": {
          "display_name": "tricount participant",
          "pointer": { "type": "UUID", "value": "...", "name": "tricount participant" }
        },
        "status": "ACTIVE",
        "setting": { "auto_add_card_transaction": "INACTIVE", ... }
      }
    }
  ]
}
```

### PUT /v1/user/{userId}/registry/{registryId}/registry-membership/{membershipId}

Update membership settings (card auto-add, etc).

**Request Body:**
```json
{
  "alias": {
    "name": "Alice",
    "type": "UUID",
    "value": "<member-uuid>"
  }
}
```

**Important:** The request uses `name`/`type`/`value` (flat), NOT `display_name`/`pointer` (nested) like the response.

**Alias types supported:**
- `UUID` — standard member (value = member's UUID)
- `EMAIL` — email-based member (value = email address)
- `PHONE_NUMBER` — phone-based member (value = phone number)

**Response:**
```json
{
  "Response": [{ "Id": { "id": 438275026 } }]
}
```

**Warning:** This endpoint returns 200 success but **does not persist member name changes**. To rename members, use `PUT /registry/{registryId}` with the full `memberships` array instead (see above).

### POST /v1/user/{userId}/registry/{registryId}/registry-entry

Create a new transaction (expense, income, or reimbursement).

**Expense (NORMAL) - amounts are negative:**
```json
{
  "uuid": "a1b2c3d4-...",
  "description": "Lunch",
  "amount": {"value": "-25.50", "currency": "EUR"},
  "membership_uuid_owner": "<payer-member-uuid>",
  "allocations": [
    {
      "membership_uuid": "<member-uuid-1>",
      "amount": {"value": "-12.75", "currency": "EUR"},
      "type": "AMOUNT"
    },
    {
      "membership_uuid": "<member-uuid-2>",
      "amount": {"value": "-12.75", "currency": "EUR"},
      "type": "AMOUNT"
    }
  ],
  "type_transaction": "NORMAL",
  "status": "ACTIVE",
  "date": "2026-03-30 14:30:00.000000"
}
```

**Income (INCOME) - amounts are positive:**
```json
{
  "uuid": "a1b2c3d4-...",
  "description": "Refund",
  "amount": {"value": "100.00", "currency": "EUR"},
  "membership_uuid_owner": "<receiver-member-uuid>",
  "allocations": [
    {
      "membership_uuid": "<member-uuid-1>",
      "amount": {"value": "50.00", "currency": "EUR"},
      "type": "AMOUNT"
    },
    {
      "membership_uuid": "<member-uuid-2>",
      "amount": {"value": "50.00", "currency": "EUR"},
      "type": "AMOUNT"
    }
  ],
  "type_transaction": "INCOME",
  "status": "ACTIVE",
  "date": "2026-03-30 14:30:00.000000"
}
```

**Reimbursement (BALANCE) - transfer between members:**
```json
{
  "uuid": "a1b2c3d4-...",
  "description": "Settling up",
  "amount": {"value": "50.00", "currency": "EUR"},
  "membership_uuid_owner": "<payer-uuid>",
  "allocations": [
    {
      "membership_uuid": "<receiver-uuid>",
      "amount": {"value": "50.00", "currency": "EUR"},
      "type": "AMOUNT"
    },
    {
      "membership_uuid": "<payer-uuid>",
      "amount": {"value": "0", "currency": "EUR"},
      "type": "AMOUNT"
    }
  ],
  "type_transaction": "BALANCE",
  "status": "ACTIVE",
  "date": "2026-03-30 14:30:00.000000"
}
```

**Ratio-based split:**
```json
{
  "allocations": [
    {
      "membership_uuid": "<member-1>",
      "amount": {"value": "-25.00", "currency": "EUR"},
      "type": "RATIO",
      "share_ratio": 1
    },
    {
      "membership_uuid": "<member-2>",
      "amount": {"value": "-50.00", "currency": "EUR"},
      "type": "RATIO",
      "share_ratio": 2
    },
    {
      "membership_uuid": "<member-3>",
      "amount": {"value": "-25.00", "currency": "EUR"},
      "type": "RATIO",
      "share_ratio": 1
    }
  ]
}
```
Ratios are relative: 1:2:1 means member-2 pays twice as much.

**Foreign currency transaction:**
```json
{
  "amount": {"value": "-15000", "currency": "JPY"},
  "amount_local": {"value": "-100.00", "currency": "USD"},
  "exchange_rate": "150",
  "allocations": [
    {
      "membership_uuid": "<member-uuid>",
      "amount": {"value": "-15000", "currency": "JPY"},
      "amount_local": {"value": "-100.00", "currency": "USD"},
      "type": "AMOUNT"
    }
  ]
}
```

**Transaction with attachment:**
```json
{
  "attachment": [{"id": 12345}]
}
```
Upload attachment first via `POST /registry/{id}/attachment`, then include the returned ID.

**Optional fields:**
- `category`: Standard category (e.g. `FOOD_AND_DRINK`, `TRANSPORT`, `OTHER`)
- `category_custom`: Custom category label with emoji (e.g. `"Coffee ☕️"`, `"Game Night 🎲"`)
- `amount_local`: Original currency amount (when different from tricount currency)
- `exchange_rate`: Conversion rate to tricount currency
- `attachment`: Array of attachment IDs

**Categories:**

Standard categories: `TRAVEL`, `ENTERTAINMENT`, `GROCERIES`, `HEALTHCARE`, `INSURANCE`, `RENT_AND_UTILITIES`, `FOOD_AND_DRINK`, `SHOPPING`, `TRANSPORT`, `OTHER`, `UNCATEGORIZED`

For custom categories, set `category` to `"OTHER"` and `category_custom` to a label+emoji string:
```json
{
  "category": "OTHER",
  "category_custom": "Coffee ☕️"
}
```

**Response:**
```json
{
  "Response": [{ "Id": { "id": 123456789 } }]
}
```

**Notes:**
- Do NOT include `type` field — it's rejected as "superfluous"
- `type_transaction` values: `NORMAL` (expense), `INCOME`, `BALANCE` (reimbursement)
- `date` format: `YYYY-MM-DD HH:MM:SS.ffffff`
- Allocation `type`: `AMOUNT` (fixed amounts) or `RATIO` (with `share_ratio`)
- **Expenses use negative amounts**, income and reimbursements use positive

### PUT /v1/user/{userId}/registry/{registryId}/registry-entry/{entryId}

Edit an existing transaction.

**Request Body:**
```json
{
  "description": "Updated lunch",
  "amount": {"value": "35.00", "currency": "EUR"},
  "membership_uuid_owner": "<new-payer-uuid>",
  "allocations": [
    {
      "membership_uuid": "<member-uuid-1>",
      "amount": {"value": "17.50", "currency": "EUR"},
      "type": "AMOUNT"
    },
    {
      "membership_uuid": "<member-uuid-2>",
      "amount": {"value": "17.50", "currency": "EUR"},
      "type": "AMOUNT"
    }
  ],
  "type_transaction": "NORMAL",
  "status": "ACTIVE",
  "date": "2026-03-30 14:30:00.000000",
  "category": "FOOD_AND_DRINK"
}
```

**Response:**
```json
{
  "Response": [{ "Id": { "id": 123456789 } }]
}
```

**Notes:**
- All fields in the request body are required (not a partial update)
- The transaction ID in the URL must match an existing transaction
- Category and category_custom are optional

### DELETE /v1/user/{userId}/registry/{registryId}/registry-entry/{entryId}

Delete a transaction.

**Request:** No body required.

**Response:**
```json
{
  "Response": [{ "Id": { "id": 123456789 } }]
}
```

### GET /v1/user/{userId}

Get authenticated user profile.

**Response:**
```json
{
  "Response": [{
    "UserPerson": {
      "id": 79290957,
      "display_name": "tricount participant",
      "public_uuid": "7e2c9c33-...",
      "status": "SIGNUP",
      "sub_status": "NONE",
      "language": "en_US",
      ...
    }
  }]
}
```

### GET /v1/user/{userId}/registry/{registryId}/gallery-attachment

List all gallery attachments for a tricount.

**Response:**
```json
{
  "Response": [
    {
      "RegistryGalleryAttachment": {
        "attachment": {
          "id": 12345,
          "uuid": "abc123-...",
          "content_type": "image/jpeg",
          "urls": [
            { "type": "ORIGINAL", "url": "https://..." }
          ]
        },
        "membership_uuid": "<uploader-member-uuid>"
      }
    }
  ]
}
```

### POST /v1/user/{userId}/registry/{registryId}/gallery-attachment/{uuid}

Upload an image to the tricount gallery.

**Request:**
- Method: POST
- Content-Type: `image/jpeg`, `image/png`, etc.
- Header: `X-Bunq-Attachment-Description: ""` (can be empty)
- Body: Binary image data

**Response:**
```json
{
  "Response": [{ "UUID": { "uuid": "abc123-..." } }]
}
```

### DELETE /v1/user/{userId}/registry/{registryId}/gallery-attachment/{uuid}

Delete a gallery attachment.

**Request:** No body required.

**Response:**
```json
{
  "Response": [{ "Id": { "id": 12345 } }]
}
```

### POST /v1/user/{userId}/registry/{registryId}/attachment

Upload an attachment for transactions (e.g., receipt photo).

**Request:**
- Method: POST
- Content-Type: `image/jpeg`, `image/png`, etc.
- Header: `X-Bunq-Attachment-Description: ""`
- Body: Binary image data

**Response:**
```json
{
  "Response": [{ "Id": { "id": 12345 } }]
}
```

The returned ID can be used when creating/editing transactions.

### GET /v1/user/{userId}/exchange-rate

Get exchange rates from a source currency.

**Query Parameters:**

| Param | Description |
|-------|-------------|
| `currency` | Source currency code (e.g. `USD`, `EUR`) |

**Response:**
```json
{
  "Response": [
    {
      "ExchangeRate": {
        "currency_source": "USD",
        "currency_target": "JPY",
        "rate": "150.25",
        "description": "Japanese Yen",
        "number_of_decimal": 0,
        "symbol": "¥"
      }
    },
    {
      "ExchangeRate": {
        "currency_source": "USD",
        "currency_target": "EUR",
        "rate": "0.92",
        "description": "Euro",
        "number_of_decimal": 2,
        "symbol": "€"
      }
    }
  ]
}
```

**Notes:**
- Returns rates for converting from the source currency to all supported currencies
- Rate is: 1 source_currency = rate × target_currency

### POST /v1/user/{userId}/registry-synchronization

Synchronize multiple tricounts in a single request.

**Request Body:**
```json
{
  "all_registry_active": [
    { "public_identifier_token": "tABC123..." }
  ],
  "all_registry_archived": [
    { "public_identifier_token": "tXYZ789..." }
  ],
  "all_registry_deleted": []
}
```

**Response:**
```json
{
  "Response": [
    {
      "RegistrySynchronization": {
        "all_registry_active": [
          { "id": 123, "title": "...", "memberships": [...], ... }
        ],
        "all_registry_archived": []
      }
    }
  ]
}
```

**Notes:**
- Returns full registry data (not wrapped in `{"Registry": ...}`)
- Efficiently fetches multiple tricounts in one request
- If called with empty arrays, returns all user's tricounts

---

## Data Structures

### Registry (Tricount)

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Internal ID |
| `uuid` | string | UUID |
| `title` | string | Display name |
| `description` | string | Description text |
| `currency` | string | ISO 4217 code (e.g. `JPY`) |
| `emoji` | string/null | Emoji for the tricount |
| `category` | string | Category enum |
| `status` | string | `READ_WRITE` (active) or `READ_ONLY` (archived) |
| `created` | string | Datetime `YYYY-MM-DD HH:MM:SS.ffffff` |
| `public_identifier_token` | string | The shareable key (from URL) |
| `memberships` | array | List of members |
| `all_registry_entry` | array | List of transactions |
| `all_registry_gallery_attachment` | array | Gallery images |

### Membership (`RegistryMembershipNonUser`)

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Membership ID |
| `uuid` | string | Membership UUID |
| `alias.display_name` | string | Member's name |
| `alias.pointer.value` | string | Member's UUID |
| `status` | string | `ACTIVE` |

### RegistryEntry (Transaction)

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Entry ID |
| `uuid` | string | Entry UUID |
| `date` | string | Transaction datetime |
| `description` | string | What was purchased |
| `type` | string | `MANUAL` |
| `type_transaction` | string | `NORMAL`, `INCOME`, or `BALANCE` |
| `status` | string | `ACTIVE` |
| `amount` | object | `{currency: "JPY", value: "-507"}` |
| `amount_local` | object | Original currency if different |
| `exchange_rate` | string | Conversion rate |
| `membership_owned` | object | Who paid (membership object) |
| `allocations` | array | How the expense is split |
| `category` | string | Expense category |
| `attachment` | array | Receipts/attachments |

### Allocation

| Field | Type | Description |
|-------|------|-------------|
| `amount` | object | `{currency: "JPY", value: "-253"}` |
| `amount_local` | object | Same in local currency |
| `membership` | object | Member this allocation applies to |
| `type` | string | `RATIO` or `AMOUNT` |
| `share_ratio` | int/null | Proportional share (for RATIO type) |

---

## Known Behaviors

### Amount Storage
- Amounts stored as **decimal strings** (e.g. `"-507"`, `"-395.00"`)
- `amount` = tricount's currency
- `amount_local` = original currency (e.g. TWD when in Taiwan)
- Negative values = expenses

### Odd Amount Splitting
- For 50/50 splits with odd amounts, the API stores exact allocations (e.g. 253 + 254 = 507)
- The extra 1 JPY consistently goes to the **same person** across all transactions
- The app displays floored amounts (253 + 253) but balances correctly

### Alias Model: Request vs Response
The `Alias` model uses different field names in requests vs responses:

| Request field | Response field | Notes |
|--------------|----------------|-------|
| `alias.name` | `alias.display_name` | Member's display name |
| `alias.type` | `alias.pointer.type` | Type: `UUID`, `EMAIL`, `PHONE_NUMBER`, `IBAN`, etc. |
| `alias.value` | `alias.pointer.value` | The actual value (UUID, email, phone) |
| — | `alias.pointer.name` | Mirror of display_name in responses |

### Response Envelope
All responses use this structure:
```json
{
  "Response": [
    { "SingleKeyObject": { ...actual data... } }
  ],
  "Pagination": { ... }
}
```

---

## What's NOT Documented Yet

- **Settlement creation** — `POST /registry/{id}/registry-settlement` returns 404 (may require bunq account)
- **No user ID resolution for members** — `RegistryMembershipNonUser` members don't have bunq user IDs
- **Registry sync via PUT** — The `all_registry_entry` field returns 200 but doesn't persist (use individual PUT endpoints)

## Immutable Fields

These fields can only be set at creation time and cannot be updated:
- `currency` — rejected as "superfluous" on PUT
- `description` — returns 200 but doesn't persist changes

---

## Python Example

```python
import requests, uuid
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Generate credentials
app_id = str(uuid.uuid4())
key = rsa.generate_private_key(65537, 2048)
pub_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.PKCS1).decode()

# Authenticate
session = requests.Session()
session.headers = {
    "User-Agent": "com.bunq.tricount.android:RELEASE:7.0.7:3174:ANDROID:13:C",
    "app-id": app_id,
    "X-Bunq-Client-Request-Id": "049bfcdf-6ae4-4cee-af7b-45da31ea85d0",
}
resp = session.post("https://api.tricount.bunq.com/v1/session-registry-installation", json={
    "app_installation_uuid": app_id,
    "client_public_key": pub_pem,
    "device_description": "Android",
})
token = resp.json()["Response"][0]["Token"]["token"]
user_id = resp.json()["Response"][1]["UserPerson"]["id"]
session.headers["X-Bunq-Client-Authentication"] = token

# Fetch tricount
resp = session.get(f"https://api.tricount.bunq.com/v1/user/{user_id}/registry",
                   params={"public_identifier_token": "tABC123xyz"})
registry = resp.json()["Response"][0]["Registry"]
print(f"{registry['title']}: {len(registry['all_registry_entry'])} entries")

# Add members
session.put(f"https://api.tricount.bunq.com/v1/user/{user_id}/registry/{registry['id']}", json={
    "memberships": [
        {"uuid": str(uuid.uuid4()), "status": "ACTIVE"},
        {"uuid": str(uuid.uuid4()), "status": "ACTIVE"},
    ]
})

# Rename members (must update via registry endpoint with full membership list)
memberships = []
for m in registry["memberships"]:
    for key, mdata in m.items():
        memberships.append({
            "uuid": mdata["uuid"],
            "status": "ACTIVE",
            "auto_add_card_transaction": "",
            "setting": None,
            "alias": {
                "type": "UUID",
                "value": mdata["uuid"],
                "name": "Alice" if mdata["uuid"] == "<target-uuid>" else mdata["alias"]["display_name"]
            }
        })

session.put(f"https://api.tricount.bunq.com/v1/user/{user_id}/registry/{registry['id']}", json={
    "memberships": memberships
})
```
