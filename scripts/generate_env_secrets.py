#!/usr/bin/env python3
"""Print fresh .env credentials without changing any files."""

import secrets


def main() -> None:
    database_password = secrets.token_hex(24)
    print("# Generated passwords and secrets; paste into .env")
    print(f"MYSQL_PASSWORD={database_password}")
    print(f"MYSQL_ROOT_PASSWORD={secrets.token_hex(24)}")
    print(
        "DATABASE_URL=mysql+pymysql://network_monitoring:"
        f"{database_password}@localhost:3306/network_monitoring"
    )
    for name in ("INTERNAL_API_KEY", "AUTH_PASSWORD_SECRET", "AUTH_JWT_SECRET"):
        print(f"{name}={secrets.token_hex(32)}")
    print(f"BOOTSTRAP_ADMIN_PASSWORD={secrets.token_hex(24)}")
    print("# Optional additional API keys; leave empty unless configured")
    print("INTERNAL_API_KEYS=")
    print()
    print("# Obtain these from the actual service/device; uncomment after filling")
    for name in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "MIKROTIK_PASSWORD",
        "RO_MIKROTIK_PASSWORD",
        "MIKROTIK_TARGETS",
        "PRINTER_SNMP_COMMUNITIES",
        "NAS_SNMP_COMMUNITIES",
    ):
        print(f"# {name}=<fill-with-real-value>")
    print("# Adjust DATABASE_URL host, username, and database for your deployment.")


if __name__ == "__main__":
    main()
