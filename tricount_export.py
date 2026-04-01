#!/usr/bin/env python3
"""
Tricount API Client - Export transactions to CSV/JSON

Based on reverse engineering of the bunq Tricount Android app.
Reference: https://github.com/mlaily/TricountApi
"""

import argparse
import csv
import io
import json
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


def extract_transactions(registry):
    transactions = []
    currency = registry.get("currency", "UNKNOWN")

    memberships = {}
    for m in registry.get("memberships", []):
        for key, mdata in m.items():
            memberships[mdata["id"]] = mdata.get("alias", {}).get(
                "display_name", "Unknown"
            )

    for entry in registry.get("all_registry_entry", []):
        for key, t in entry.items():
            if key != "RegistryEntry":
                continue

            ttype = t.get("type_transaction", "")
            if ttype == "BALANCE":
                continue

            payer_id = t.get("membership_owned", {})
            payer_name = "Unknown"
            for mk, mv in payer_id.items():
                payer_name = mv.get("alias", {}).get("display_name", "Unknown")

            allocations = []
            for alloc in t.get("allocations", []):
                alloc_name = "Unknown"
                for amk, amv in alloc.get("membership", {}).items():
                    alloc_name = amv.get("alias", {}).get("display_name", "Unknown")
                alloc_amount = alloc.get("amount", {}).get("value", "0")
                allocations.append({"member": alloc_name, "amount": alloc_amount})

            transactions.append(
                {
                    "id": t.get("id"),
                    "uuid": t.get("uuid"),
                    "date": t.get("date", ""),
                    "description": t.get("description", ""),
                    "type": t.get("type", ""),
                    "type_transaction": ttype,
                    "category": t.get("category", ""),
                    "amount": t.get("amount", {}).get("value", "0"),
                    "currency": t.get("amount", {}).get("currency", currency),
                    "payer": payer_name,
                    "allocations": allocations,
                    "status": t.get("status", ""),
                }
            )

    return transactions


def to_csv(transactions):
    if not transactions:
        return ""

    flat_rows = []
    for t in transactions:
        if not t["allocations"]:
            flat_rows.append(
                {
                    "id": t["id"],
                    "date": t["date"],
                    "description": t["description"],
                    "type": t["type"],
                    "type_transaction": t["type_transaction"],
                    "category": t["category"],
                    "amount": t["amount"],
                    "currency": t["currency"],
                    "payer": t["payer"],
                    "allocation_member": "",
                    "allocation_amount": "",
                    "status": t["status"],
                }
            )
        else:
            for alloc in t["allocations"]:
                flat_rows.append(
                    {
                        "id": t["id"],
                        "date": t["date"],
                        "description": t["description"],
                        "type": t["type"],
                        "type_transaction": t["type_transaction"],
                        "category": t["category"],
                        "amount": t["amount"],
                        "currency": t["currency"],
                        "payer": t["payer"],
                        "allocation_member": alloc["member"],
                        "allocation_amount": alloc["amount"],
                        "status": t["status"],
                    }
                )

    output = io.StringIO()
    fieldnames = [
        "id",
        "date",
        "description",
        "type",
        "type_transaction",
        "category",
        "amount",
        "currency",
        "payer",
        "allocation_member",
        "allocation_amount",
        "status",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(flat_rows)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description="Export Tricount transactions")
    parser.add_argument(
        "tricount_key", help="Tricount key from URL (e.g. tMjbqgwJxaikhUbkNz)"
    )
    parser.add_argument(
        "-f", "--format", choices=["csv", "json"], default="csv", help="Output format"
    )
    parser.add_argument("-o", "--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "--app-id",
        help="Persistent app installation UUID (auto-generated if not provided)",
    )
    parser.add_argument(
        "--key-file", help="Path to store/load RSA key (auto-generated if not provided)"
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        help="Limit number of transactions shown",
    )
    args = parser.parse_args()

    app_id = args.app_id or str(uuid.uuid4())

    key_path = Path(args.key_file) if args.key_file else None
    if key_path and key_path.exists():
        public_key_pem = key_path.read_text()
    else:
        public_key_pem = generate_rsa_key()
        if key_path:
            key_path.write_text(public_key_pem)

    print(f"Authenticating (app-id: {app_id})...", file=sys.stderr)
    session, user_id = authenticate(app_id, public_key_pem)

    print(
        f"Fetching tricount {args.tricount_key} (user-id: {user_id})...",
        file=sys.stderr,
    )
    registry = fetch_tricount(session, user_id, args.tricount_key)

    print(
        f"Found {registry.get('title', 'Unknown')} - {len(registry.get('all_registry_entry', []))} entries",
        file=sys.stderr,
    )

    transactions = extract_transactions(registry)

    if args.limit:
        transactions = transactions[: args.limit]

    print(f"Exported {len(transactions)} transactions", file=sys.stderr)

    if args.format == "json":
        output = json.dumps(transactions, indent=2)
    else:
        output = to_csv(transactions)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
