"""Server entry point: `python3 -m app --port 8000 --db tasks.db`."""

import argparse
import logging
import sys

from app.repository import TaskRepository
from app.server import make_server

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8000
DEFAULT_DB = "tasks.db"
DEFAULT_CORS_ORIGIN = "http://localhost:5500"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="app", description="Task CRUD API (Python 3.14, stdlib only)."
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="listening interface (use 0.0.0.0 in a container)",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="listening port"
    )
    parser.add_argument(
        "--db", default=DEFAULT_DB, help="sqlite file path"
    )
    parser.add_argument(
        "--cors-origin",
        default=DEFAULT_CORS_ORIGIN,
        help="allowed CORS origin",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    log = logging.getLogger("app")
    log.info("GIL enabled: %s | Python %s", sys._is_gil_enabled(), sys.version.split()[0])

    repo = TaskRepository(args.db)
    server = make_server(args.host, args.port, cors_origin=args.cors_origin, repo=repo)
    log.info(
        "Serving on http://%s:%d (db: %s, CORS: %s)",
        args.host,
        args.port,
        args.db,
        args.cors_origin,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Stopping…")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
