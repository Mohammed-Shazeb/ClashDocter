"""Standalone Qloo coverage & taste-signal validation probe.

This package is an offline/CLI tool, not part of the API or the optimizer. It
reuses the production Qloo client (`app.qloo`), the run-scoped TTL cache and the
production similarity engine so the numbers it reports are the numbers
ClashDoctor would actually compute.
"""
