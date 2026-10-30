"""Copilot docs RAG (CP-5): a safe, deterministic set of project documents and a Markdown chunker.

Pure Python on purpose: no network, no database, no model, no third-party packages. This package only decides
*which* documents may be retrieved from (``corpus.py``) and *how* they are cut into citable pieces (``chunker.py``).
Indexing and search arrive in CP-6; answering from the passages arrives in CP-7.

Retrieved text is data, never instructions. Nothing here interprets the text of a document.
"""
