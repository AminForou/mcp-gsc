"""Command-line interface (spec 4.1: auth via CLI, not MCP tool).

Subcommands:
  gsc-mcp auth login    — run the OAuth browser flow and store a read-only token
  gsc-mcp auth status    — report auth state without exposing secrets
  gsc-mcp auth logout    — delete the stored token

No `reauthenticate` MCP tool is exposed; account switching happens here.
"""
from __future__ import annotations

import argparse
import sys

from . import auth, config


def _cmd_auth_login(_args: argparse.Namespace) -> int:
    try:
        msg = auth.run_oauth_login_flow()
        print(msg)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_auth_status(_args: argparse.Namespace) -> int:
    print(auth.auth_status())
    return 0


def _cmd_auth_logout(_args: argparse.Namespace) -> int:
    print(auth.logout())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gsc-mcp",
        description="Secure read-only Google Search Console MCP server (CLI).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    auth_parser = sub.add_parser("auth", help="Authentication actions.")
    auth_sub = auth_parser.add_subparsers(dest="auth_action", required=True)
    auth_sub.add_parser("login", help="Run the OAuth browser flow and store a read-only token.")
    auth_sub.add_parser("status", help="Report current auth state without exposing secrets.")
    auth_sub.add_parser("logout", help="Delete the stored OAuth token.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config.configure_logging()

    if args.command == "auth":
        if args.auth_action == "login":
            return _cmd_auth_login(args)
        if args.auth_action == "status":
            return _cmd_auth_status(args)
        if args.auth_action == "logout":
            return _cmd_auth_logout(args)
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
