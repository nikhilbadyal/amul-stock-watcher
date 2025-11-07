#!/usr/bin/env python3
"""Health check script for Amul Stock Watcher container."""

import os
import sys
import time
import redis
from dotenv import load_dotenv

def check_redis_connection() -> bool:
    """Check if Redis connection is working."""
    try:
        load_dotenv()

        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', 6379))
        redis_db = int(os.getenv('REDIS_DB', 0))
        redis_ssl = os.getenv('REDIS_SSL', 'false').lower() in ('true', '1', 'yes')
        redis_password = os.getenv('REDIS_PASSWORD')

        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            ssl=redis_ssl,
            password=redis_password,
            socket_connect_timeout=5,
            socket_timeout=5
        )

        # Test connection
        r.ping()
        return True
    except Exception as e:
        print(f"Redis health check failed: {e}", file=sys.stderr)
        return False


def check_last_fetch_time() -> bool:
    """Check if products were fetched within the last hour."""
    timestamp_file = '/app/.last_fetch_timestamp'

    try:
        # If file doesn't exist (first run), consider it healthy
        # The application will create it on first successful run
        if not os.path.exists(timestamp_file):
            print("No previous fetch timestamp found (first run), considering healthy", file=sys.stderr)
            return True

        # Read the timestamp
        with open(timestamp_file, 'r') as f:
            timestamp_str = f.read().strip()

        last_fetch_time = float(timestamp_str)
        current_time = time.time()

        # Check if last fetch was within the last hour (3600 seconds)
        time_diff = current_time - last_fetch_time
        max_age = int(os.getenv("HEALTHCHECK_INTERVAL","900"))  # 1 hour

        if time_diff > max_age:
            print(f"❌ Last product fetch was {time_diff:.0f} seconds ago (> {max_age} seconds)", file=sys.stderr)
            return False

        print(f"✅ Last product fetch was {time_diff:.0f} seconds ago", file=sys.stderr)
        return True

    except Exception as e:
        print(f"Error checking last fetch time: {e}", file=sys.stderr)
        return False

def main() -> None:
    """Run health checks."""
    checks = []

    # Check Redis connection
    redis_ok = check_redis_connection()
    checks.append(("redis", redis_ok))

    # Check last fetch time (products fetched within last hour)
    fetch_time_ok = check_last_fetch_time()
    checks.append(("last_fetch_time", fetch_time_ok))

    # All checks must pass
    all_passed = all(result for _, result in checks)

    if all_passed:
        print("✅ Health check passed")
        sys.exit(0)
    else:
        failed_checks = [name for name, result in checks if not result]
        print(f"❌ Health check failed: {', '.join(failed_checks)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
