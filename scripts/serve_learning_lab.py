"""Serve the static LocalCode learning UI on localhost."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEARNING_ROOT = PROJECT_ROOT / "learning"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4173)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.port <= 65_535:
        raise SystemExit("--port must be between 1 and 65535")
    handler = partial(SimpleHTTPRequestHandler, directory=str(LEARNING_ROOT))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"LocalCode learning UI: http://{args.host}:{args.port}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
