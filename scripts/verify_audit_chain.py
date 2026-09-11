from __future__ import annotations

import argparse
import os

from app.config import Settings
from app.database import Repository


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify one tenant's tamper-evident audit chain")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--database-path", default="")
    args = parser.parse_args()

    settings = Settings.from_env()
    database = args.database_url or args.database_path or settings.database_dsn
    repository = Repository(
        database,
        pool_size=settings.database_pool_size,
        audit_hmac_key=os.getenv("AUDIT_HMAC_KEY", ""),
    )
    repository.initialize()
    try:
        result = repository.verify_audit_chain(args.tenant)
    finally:
        repository.close()
    print(
        f"tenant={args.tenant} valid={result['valid']} "
        f"events={result['event_count']} "
        f"first_invalid_sequence={result['first_invalid_sequence']}"
    )
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
