#!/usr/bin/env python3
"""
Test script for Tricount transaction (RegistryEntry) CRUD operations.
Based on decompiled code analysis.

Endpoints:
- POST /user/{userId}/registry/{registryId}/registry-entry - Create
- DELETE /user/{userId}/registry/{registryId}/registry-entry/{entryId} - Delete
- PUT /user/{userId}/registry/{registryId} with all_registry_entry - Update (via registry)
"""

import json
import sys
import uuid
import requests
from datetime import datetime

BASE_URL = "https://api.tricount.bunq.com"
USER_AGENT = "com.bunq.tricount.android:RELEASE:7.0.7:3174:ANDROID:13:C"
REQUEST_ID = "049bfcdf-6ae4-4cee-af7b-45da31ea85d0"


def authenticate(app_id, public_key_pem):
    """Authenticate and return session + user_id"""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "app-id": app_id,
            "X-Bunq-Client-Request-Id": REQUEST_ID,
        }
    )

    resp = session.post(
        f"{BASE_URL}/v1/session-registry-installation",
        json={
            "app_installation_uuid": app_id,
            "client_public_key": public_key_pem,
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

    session.headers["X-Bunq-Client-Authentication"] = token
    return session, user_id


def fetch_tricount(session, user_id, tricount_key):
    """Fetch a tricount by its public key"""
    resp = session.get(
        f"{BASE_URL}/v1/user/{user_id}/registry",
        params={"public_identifier_token": tricount_key},
    )
    resp.raise_for_status()
    data = resp.json()

    for item in data["Response"]:
        if "Registry" in item:
            return item["Registry"]
    raise RuntimeError("No Registry found")


def get_members(registry):
    """Extract member info from registry"""
    members = []
    for m in registry.get("memberships", []):
        for key, mdata in m.items():
            members.append(
                {
                    "id": mdata["id"],
                    "uuid": mdata["uuid"],
                    "display_name": mdata.get("alias", {}).get(
                        "display_name", mdata["uuid"]
                    ),
                }
            )
    return members


def create_transaction(
    session,
    user_id,
    registry_id,
    description,
    amount,
    currency,
    payer_uuid,
    split_among_uuids,
):
    """
    Create a new transaction (RegistryEntry).

    Based on RegistryEntry class from decompiled code:
    - amount: {value: string, currency: string}
    - allocations: list of AllocationItem
    - membership_uuid_owner: payer's UUID
    - type: MANUAL
    - type_transaction: NORMAL
    - status: ACTIVE
    - date: datetime string
    """
    url = f"{BASE_URL}/v1/user/{user_id}/registry/{registry_id}/registry-entry"

    # Calculate split amount
    split_count = len(split_among_uuids)
    amount_per_person = str(round(float(amount) / split_count, 2))

    # Build allocations
    allocations = []
    for member_uuid in split_among_uuids:
        allocations.append(
            {
                "membership_uuid": member_uuid,
                "amount": {
                    "value": amount_per_person,
                    "currency": currency,
                },
                "type": "AMOUNT",
            }
        )

    # Build the entry
    # Note: "type" field is rejected as superfluous by API
    entry_uuid = str(uuid.uuid4())
    payload = {
        "uuid": entry_uuid,
        "description": description,
        "amount": {
            "value": amount,
            "currency": currency,
        },
        "membership_uuid_owner": payer_uuid,
        "allocations": allocations,
        "type_transaction": "NORMAL",
        "status": "ACTIVE",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
    }

    print(f"POST {url}")
    print(f"Payload: {json.dumps(payload, indent=2)}")

    resp = session.post(url, json=payload)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}")

    return resp


def delete_transaction(session, user_id, registry_id, entry_id):
    """Delete a transaction by ID"""
    url = (
        f"{BASE_URL}/v1/user/{user_id}/registry/{registry_id}/registry-entry/{entry_id}"
    )

    print(f"DELETE {url}")

    resp = session.delete(url)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}")

    return resp


def list_transactions(registry):
    """List transactions from registry data"""
    entries = []
    for entry in registry.get("all_registry_entry", []):
        for key, edata in entry.items():
            if key == "RegistryEntry":
                entries.append(
                    {
                        "id": edata.get("id"),
                        "uuid": edata.get("uuid"),
                        "description": edata.get("description"),
                        "amount": edata.get("amount", {}).get("value"),
                        "currency": edata.get("amount", {}).get("currency"),
                        "status": edata.get("status"),
                        "type_transaction": edata.get("type_transaction"),
                        "membership_uuid_owner": edata.get("membership_uuid_owner"),
                        "allocations": edata.get("allocations", []),
                        "date": edata.get("date"),
                        "updated": edata.get("updated"),
                    }
                )
    return entries


def edit_transaction(
    session, user_id, registry, entry_id, new_description=None, new_amount=None
):
    """
    Edit a transaction via TricountRegistryUpdateRequest.

    Based on decompiled code, edits go through PUT /registry/{id} with all_registry_entry array.
    """
    registry_id = registry["id"]
    url = f"{BASE_URL}/v1/user/{user_id}/registry/{registry_id}"

    # Build the all_registry_entry from existing entries
    all_entries = []
    for entry in registry.get("all_registry_entry", []):
        for key, edata in entry.items():
            if key == "RegistryEntry":
                # Build entry request object matching RegistryEntryRequest structure
                entry_obj = {
                    "id": edata.get("id"),
                    "uuid": edata.get("uuid"),
                    "description": edata.get("description"),
                    "amount": edata.get("amount"),
                    "amount_local": edata.get("amount_local"),
                    "membership_uuid_owner": edata.get("membership_uuid_owner"),
                    "allocations": edata.get("allocations", []),
                    "status": edata.get("status"),
                    "type_transaction": edata.get("type_transaction"),
                    "date": edata.get("date"),
                    "category": edata.get("category"),
                    "category_custom": edata.get("category_custom"),
                }

                # Apply edits if this is the entry being modified
                if edata.get("id") == entry_id:
                    if new_description:
                        entry_obj["description"] = new_description
                    if new_amount:
                        entry_obj["amount"] = {
                            "value": new_amount,
                            "currency": edata.get("amount", {}).get("currency"),
                        }

                all_entries.append(entry_obj)

    payload = {
        "all_registry_entry": all_entries,
    }

    print(f"PUT {url}")
    print(f"Payload: {json.dumps(payload, indent=2)}")

    resp = session.put(url, json=payload)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text}")

    return resp


def main():
    # Load credentials
    with open("tricount_credentials.json") as f:
        creds = json.load(f)

    with open("tricount_test.json") as f:
        test_data = json.load(f)

    app_id = creds["app_id"]
    public_key_pem = creds["public_key_pem"]
    tricount_key = test_data["public_identifier_token"]
    registry_id = test_data["registry_id"]

    print(f"Authenticating with app_id: {app_id[:8]}...")
    session, user_id = authenticate(app_id, public_key_pem)
    print(f"User ID: {user_id}")

    print(f"\nFetching tricount: {tricount_key}")
    registry = fetch_tricount(session, user_id, tricount_key)

    print(f"\nTricount: {registry['title']}")
    print(f"Currency: {registry['currency']}")

    members = get_members(registry)
    print(f"\nMembers:")
    for i, m in enumerate(members):
        print(f"  {i}: {m['display_name']} ({m['uuid'][:8]}...)")

    entries = list_transactions(registry)
    print(f"\nTransactions ({len(entries)}):")
    for e in entries:
        print(
            f"  - [{e['id']}] {e['description']}: {e['amount']} {e['currency']} ({e['status']})"
        )

    if len(sys.argv) < 2:
        print("\nUsage:")
        print(
            "  python test_transactions.py create <description> <amount> <payer_idx> [split_idx1,split_idx2,...]"
        )
        print(
            "  python test_transactions.py edit <entry_id> <new_description> [new_amount]"
        )
        print("  python test_transactions.py delete <entry_id>")
        print("\nExamples:")
        print("  python test_transactions.py create 'Lunch' 1000 0 0,1")
        print("  python test_transactions.py edit 123456 'Updated description'")
        print("  python test_transactions.py edit 123456 'Updated description' 2000")
        print("  python test_transactions.py delete 123456")
        return

    action = sys.argv[1]

    if action == "create":
        if len(sys.argv) < 5:
            print(
                "Usage: create <description> <amount> <payer_idx> [split_idx1,split_idx2,...]"
            )
            return

        description = sys.argv[2]
        amount = sys.argv[3]
        payer_idx = int(sys.argv[4])

        if len(sys.argv) > 5:
            split_indices = [int(x) for x in sys.argv[5].split(",")]
        else:
            split_indices = list(range(len(members)))  # Split among all

        payer_uuid = members[payer_idx]["uuid"]
        split_uuids = [members[i]["uuid"] for i in split_indices]

        print(f"\nCreating transaction:")
        print(f"  Description: {description}")
        print(f"  Amount: {amount} {registry['currency']}")
        print(f"  Payer: {members[payer_idx]['display_name']}")
        print(f"  Split among: {[members[i]['display_name'] for i in split_indices]}")

        resp = create_transaction(
            session,
            user_id,
            registry_id,
            description,
            amount,
            registry["currency"],
            payer_uuid,
            split_uuids,
        )

        if resp.status_code == 200:
            print("\nSUCCESS! Verifying...")
            registry = fetch_tricount(session, user_id, tricount_key)
            entries = list_transactions(registry)
            print(f"Transactions ({len(entries)}):")
            for e in entries[-3:]:  # Show last 3
                print(
                    f"  - [{e['id']}] {e['description']}: {e['amount']} {e['currency']} ({e['status']})"
                )

    elif action == "delete":
        if len(sys.argv) < 3:
            print("Usage: delete <entry_id>")
            return

        entry_id = sys.argv[2]
        print(f"\nDeleting transaction {entry_id}...")

        resp = delete_transaction(session, user_id, registry_id, entry_id)

        if resp.status_code == 200:
            print("\nSUCCESS! Verifying...")
            registry = fetch_tricount(session, user_id, tricount_key)
            entries = list_transactions(registry)
            print(f"Transactions ({len(entries)}):")
            for e in entries[-3:]:
                print(
                    f"  - [{e['id']}] {e['description']}: {e['amount']} {e['currency']} ({e['status']})"
                )


if __name__ == "__main__":
    main()
