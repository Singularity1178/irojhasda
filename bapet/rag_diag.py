"""Lazy hook for the optional ragdiag module (--rag-diag)."""
from __future__ import annotations



_RAGDIAG = None


def _ragdiag():
    """The ragdiag module, imported on first use.

    Imported lazily so an ordinary run never pays for it, and cached so the hot
    path is one global load rather than an import statement per frame.
    """
    global _RAGDIAG
    if _RAGDIAG is None:
        import ragdiag
        _RAGDIAG = ragdiag
    return _RAGDIAG


def _ragdiag_on():
    """Is --rag-diag active? False on every run without it."""
    return _RAGDIAG is not None and bool(_RAGDIAG.on())
