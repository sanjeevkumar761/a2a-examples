"""
Load Test Script — Flood Azure Service Bus queues to demonstrate KEDA scaling.

Usage:
    python scripts/demo-load.py --count 50 --queue invoice-requests
    python scripts/demo-load.py --count 20 --queue po-requests

Requires:
    - SERVICEBUS_FQDN env var (or --fqdn flag)
    - az login (uses DefaultAzureCredential)

What it does:
    1. Sends N fake invoice/PO messages to the specified Service Bus queue
    2. KEDA detects the growing queue and scales agent pods from 0 → N
    3. Watch with: kubectl get pods -n a2a-agents -w
"""

import argparse
import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime

from azure.identity import AzureCliCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage


def generate_invoice(index: int) -> dict:
    """Generate a realistic-looking fake invoice."""
    vendors = [
        ("Acme Corp", "V001"),
        ("Contoso Ltd", "V002"),
        ("Northwind Traders", "V003"),
        ("Fabrikam Inc", "V001"),
        ("Adventure Works", "V002"),
    ]
    vendor_name, vendor_id = random.choice(vendors)
    amount1 = random.randint(500, 10000)
    amount2 = random.randint(200, 5000)
    total = amount1 + amount2

    return {
        "invoice_number": f"INV-{datetime.now().strftime('%Y%m%d')}-{index:04d}",
        "vendor": vendor_name,
        "vendor_id": vendor_id,
        "amount": total,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "line_items": [
            {"description": "Professional Services", "amount": amount1},
            {"description": "Software Licenses", "amount": amount2},
        ],
    }


def generate_po_request(index: int) -> dict:
    """Generate a realistic-looking fake PO request."""
    vendors = ["V001", "V002", "V003"]
    return {
        "vendor_id": random.choice(vendors),
        "requester": f"user-{random.randint(1, 20)}",
        "items": [
            {
                "description": f"Item-{index}-A",
                "quantity": random.randint(1, 50),
                "unit_price": random.randint(10, 500),
            },
            {
                "description": f"Item-{index}-B",
                "quantity": random.randint(1, 20),
                "unit_price": random.randint(50, 1000),
            },
        ],
    }


def flood_queue(fqdn: str, queue_name: str, count: int, delay: float):
    """Send N messages to the specified queue as fast as possible."""
    credential = AzureCliCredential()
    client = ServiceBusClient(
        fully_qualified_namespace=fqdn, credential=credential
    )

    is_invoice = "invoice" in queue_name
    generator = generate_invoice if is_invoice else generate_po_request

    print(f"\n{'='*60}")
    print(f"  KEDA Scaling Demo — Load Test")
    print(f"{'='*60}")
    print(f"  Target queue : {queue_name}")
    print(f"  Service Bus  : {fqdn}")
    print(f"  Messages     : {count}")
    print(f"  Delay        : {delay}s between messages")
    print(f"{'='*60}\n")
    print("  Tip: In another terminal, run:")
    print("  kubectl get pods -n a2a-agents -w")
    print("  kubectl get scaledobjects -n a2a-agents\n")

    with client:
        sender = client.get_queue_sender(queue_name)
        with sender:
            start = time.time()
            for i in range(1, count + 1):
                payload = generator(i)
                msg = ServiceBusMessage(
                    body=json.dumps(payload),
                    correlation_id=f"load-test-{i:04d}",
                    content_type="application/json",
                )
                sender.send_messages(msg)
                elapsed = time.time() - start
                print(
                    f"  [{i:>4}/{count}] Sent {payload.get('invoice_number', payload.get('vendor_id', '?'))} "
                    f"({elapsed:.1f}s elapsed)"
                )
                if delay > 0:
                    time.sleep(delay)

            elapsed = time.time() - start
            print(f"\n  Done! Sent {count} messages in {elapsed:.1f}s")
            print(f"  Queue '{queue_name}' now has messages waiting.")
            print(f"  Watch KEDA scale pods: kubectl get pods -n a2a-agents -w\n")

    credential.close()


def main():
    parser = argparse.ArgumentParser(
        description="Flood Service Bus queues to demonstrate KEDA scaling"
    )
    parser.add_argument(
        "--count", "-n", type=int, default=50,
        help="Number of messages to send (default: 50)"
    )
    parser.add_argument(
        "--queue", "-q", type=str, default="invoice-requests",
        choices=["invoice-requests", "po-requests"],
        help="Queue to target (default: invoice-requests)"
    )
    parser.add_argument(
        "--fqdn", type=str,
        default=os.getenv("SERVICEBUS_FQDN", ""),
        help="Service Bus FQDN (or set SERVICEBUS_FQDN env var)"
    )
    parser.add_argument(
        "--delay", "-d", type=float, default=0.1,
        help="Delay between messages in seconds (default: 0.1)"
    )
    args = parser.parse_args()

    if not args.fqdn:
        print("ERROR: Set SERVICEBUS_FQDN env var or pass --fqdn")
        sys.exit(1)

    flood_queue(args.fqdn, args.queue, args.count, args.delay)


if __name__ == "__main__":
    main()
