from __future__ import annotations

import argparse
import json
import sys

from source.client.tcp_client import TCPClient


def main() -> None:
    # Redirected Windows stdout may otherwise use cp1252 and reject Vietnamese titles.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="GoiYMonAnTCP raw TCP client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--persistent", action="store_true")
    parser.add_argument("--op", choices=["PING", "LIST_INGREDIENTS", "GET_RECIPE", "RECOMMEND", "SEARCH_RECIPES", "GENERATE_MEAL_PLAN", "GENERATE_MEAL_PLAN_V2", "CALCULATE_MEAL_PLAN"], default="PING")
    parser.add_argument("--payload", default="{}")
    args = parser.parse_args()
    client = TCPClient(args.host, args.port, args.persistent)
    try:
        print(json.dumps(client.request(args.op, json.loads(args.payload)), ensure_ascii=False, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    main()
