#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from script.prove_settlement_period_v6 import (  # noqa: E402
    build_fixes,
    fetch_receiver_json,
    receiver_url_context,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load the deterministic V6 fixture through the trusted acquisition API."
    )
    parser.add_argument("--receiver-url", required=True)
    parser.add_argument("--acquisition-token", required=True)
    parser.add_argument("--receiver-ca-file", default="")
    parser.add_argument("--allow-insecure-receiver-http", action="store_true")
    args = parser.parse_args()
    ssl_context = receiver_url_context(
        args.receiver_url,
        ca_file=args.receiver_ca_file,
        allow_insecure_http=args.allow_insecure_receiver_http,
    )
    period_id = "2026-05-v6-k6"
    fixes = build_fixes(period_id)
    unsigned_fixes: list[dict[str, object]] = []
    for fix in fixes:
        item = fix.to_dict()
        item.pop("receiver_sig", None)
        unsigned_fixes.append(item)
    body = json.dumps({"fixes": unsigned_fixes}).encode("utf-8")
    request = urllib.request.Request(
        f"{args.receiver_url.rstrip('/')}/v2/receiver/logs",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {args.acquisition_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        period_payload = fetch_receiver_json(request, ssl_context=ssl_context)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"receiver rejected fixture: HTTP {exc.code}: {detail}") from exc

    month_body = json.dumps(
        {
            "device_id": "dev-v6",
            "month_id": "202605",
            "odometer_start_m": fixes[0].odometer_reading_m,
            "odometer_end_m": fixes[-1].odometer_reading_m + 600,
        }
    ).encode("utf-8")
    month_request = urllib.request.Request(
        f"{args.receiver_url.rstrip('/')}/v2/receiver/months",
        data=month_body,
        method="POST",
        headers={
            "Authorization": f"Bearer {args.acquisition_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        month_payload = fetch_receiver_json(month_request, ssl_context=ssl_context)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"receiver rejected month fixture: HTTP {exc.code}: {detail}") from exc
    print(
        json.dumps(
            {"period": period_payload, "month": month_payload},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
