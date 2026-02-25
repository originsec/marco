"""Command-line interface for marco."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """
    Build the argument parser for marco CLI.

    Running `marco` starts the web UI server. All analysis configuration,
    execution, and querying happens through the browser.

    Returns:
        Configured ArgumentParser instance
    """
    parser = argparse.ArgumentParser(
        prog="marco",
        description="Multi-binary control flow graphing — web UI",
    )

    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the server to (default: 127.0.0.1)")
    parser.add_argument("-p", "--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser on startup")
    parser.add_argument("-o", "--output", default="output", help="Output directory for analysis runs (default: output)")
    parser.add_argument("--config", default=None, help="Path to configuration file")
    parser.add_argument("-l", "--log-level", default="INFO", help="Log level (DEBUG, INFO, WARNING, ERROR)")

    return parser
