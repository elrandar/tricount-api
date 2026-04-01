#!/usr/bin/env python3
"""
Tricount API Client - Show full tricount stats
"""

import sys
import uuid
from pathlib import Path

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


BASE_URL = "https://api.tricount.bunq.com"
USER_AGENT = "com.bunq.tricount.android:RELEASE:7.0.7:3174:ANDROID:13:C"
REQUEST_ID = "049bfcdf-6ae4-4cee-af7b-45da31ea85d0"


def generate_rsa_key():
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
    return public_key_pem


def authenticate(app_id, public_key_pem):
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "app-id": app_id,
            "X-Bunq-Client-Request-Id": REQUEST_ID,
        }
    )

    payload = {
        "app_installation_uuid": app_id,
        "client_public_key": public_key_pem,
        "device_description": "Android",
    }

    resp = session.post(
        f"{BASE_URL}/v1/session-registry-installation",
        json=payload,
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
        raise RuntimeError(f"Failed to extract token/user_id from response: {data}")

    session.headers["X-Bunq-Client-Authentication"] = token
    return session, user_id


def fetch_tricount(session, user_id, tricount_key):
    resp = session.get(
        f"{BASE_URL}/v1/user/{user_id}/registry",
        params={"public_identifier_token": tricount_key},
    )
    resp.raise_for_status()
    data = resp.json()

    for item in data["Response"]:
        if "Registry" in item:
            return item["Registry"]

    raise RuntimeError(f"No Registry found in response")


def get_member_name(membership_obj):
    for key, mdata in membership_obj.items():
        return mdata.get("alias", {}).get("display_name", "Unknown")
    return "Unknown"


def show_stats(registry):
    title = registry.get("title", "Unknown")
    currency = registry.get("currency", "UNKNOWN")
    status = registry.get("status", "UNKNOWN")
    created = registry.get("created", "")

    members = []
    for m in registry.get("memberships", []):
        for key, mdata in m.items():
            members.append(
                {
                    "id": mdata.get("id"),
                    "uuid": mdata.get("uuid"),
                    "name": mdata.get("alias", {}).get("display_name", "Unknown"),
                }
            )

    entries = []
    for entry in registry.get("all_registry_entry", []):
        for key, t in entry.items():
            if key != "RegistryEntry":
                continue
            ttype = t.get("type_transaction", "")
            if ttype == "BALANCE":
                continue
            payer_obj = t.get("membership_owned", {})
            payer_name = get_member_name(payer_obj)
            amount_str = t.get("amount", {}).get("value", "0")
            amount = int(round(float(amount_str)))
            entries.append(
                {
                    "id": t.get("id"),
                    "date": t.get("date", ""),
                    "description": t.get("description", ""),
                    "type": t.get("type", ""),
                    "type_transaction": ttype,
                    "amount": amount,
                    "payer": payer_name,
                    "allocations": t.get("allocations", []),
                }
            )

    print(f"=== {title} ===")
    print(f"Currency: {currency}")
    print(f"Status: {status}")
    print(f"Created: {created}")
    print(f"Members: {len(members)}")
    for m in members:
        print(f"  - {m['name']}")
    print(f"Transactions: {len(entries)}")
    print()

    total_spent = sum(abs(e["amount"]) for e in entries)
    print(f"Total spent: {total_spent:,.0f} {currency}")
    print()

    paid_by = {}
    for e in entries:
        paid_by[e["payer"]] = paid_by.get(e["payer"], 0) + abs(e["amount"])

    print("Paid by:")
    for name, amount in sorted(paid_by.items(), key=lambda x: -x[1]):
        print(f"  {name}: {amount:,.0f} {currency}")
    print()

    owes = {m["name"]: 0 for m in members}
    for e in entries:
        for alloc in e["allocations"]:
            alloc_name = get_member_name(alloc.get("membership", {}))
            alloc_amount = int(round(float(alloc.get("amount", {}).get("value", "0"))))
            owes[alloc_name] += abs(alloc_amount)

    print("Total share (what each person owes):")
    for name, amount in sorted(owes.items(), key=lambda x: -x[1]):
        print(f"  {name}: {amount:,.0f} {currency}")
    print()

    print("Net balance (positive = owed money, negative = owes money):")
    for m in members:
        paid = paid_by.get(m["name"], 0)
        share = owes.get(m["name"], 0)
        net = paid - share
        sign = "+" if net >= 0 else ""
        print(f"  {m['name']}: {sign}{net:,.0f} {currency}")
    print()

    print("Latest 10 transactions:")
    print(f"{'Date':<22} {'Description':<30} {'Amount':>10} {'Payer':<10}")
    print("-" * 76)
    for e in entries[:10]:
        date = e["date"][:16] if e["date"] else ""
        amount = abs(e["amount"])
        print(f"{date:<22} {e['description']:<30} {amount:>10,.0f} {e['payer']:<10}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tricount_stats.py <tricount_key>")
        sys.exit(1)

    tricount_key = sys.argv[1]
    app_id = str(uuid.uuid4())
    public_key_pem = generate_rsa_key()

    print("Authenticating...", file=sys.stderr)
    session, user_id = authenticate(app_id, public_key_pem)

    print(f"Fetching tricount {tricount_key}...", file=sys.stderr)
    registry = fetch_tricount(session, user_id, tricount_key)

    show_stats(registry)
