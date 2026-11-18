"""`python3 -m arp ...` for machines where the `arp` script is not on PATH (e.g. a Jupyter user install)."""

from arp.cli import app

app()
