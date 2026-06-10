"""Sentence assembly for incremental verified streaming (ADR-0018).

The assembler accumulates streamed token text and yields completed sentences
using the same boundary pattern as the answer verifiers
(``re.split(r"(?<=[.!?])\\s+", ...)``), so assembly and verification agree on
what a sentence is. Emitted slices preserve the original text exactly —
trailing whitespace attaches to the completed sentence — which guarantees that
the concatenation of every emitted sentence plus the remainder reproduces the
generated text byte-for-byte.
"""
from __future__ import annotations

import re

# Identical boundary semantics to the verifiers' splitter: a sentence ends at
# [.!?] only once whitespace follows it. A buffer ending exactly at "." is not
# yet a boundary — the next token may continue the construct (e.g. "3." + "5").
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


class SentenceAssembler:
    """Incrementally split streamed text into verifier-consistent sentences."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        """Append streamed text; return any newly completed sentences.

        Each returned slice includes its trailing whitespace, preserving
        fidelity for token-event reconstruction.
        """
        self._buffer += text
        completed: list[str] = []
        last_end = 0
        for match in _SENTENCE_BOUNDARY.finditer(self._buffer):
            completed.append(self._buffer[last_end:match.end()])
            last_end = match.end()
        if last_end:
            self._buffer = self._buffer[last_end:]
        return completed

    def flush(self) -> str | None:
        """Return the trailing remainder as the final sentence, or ``None``
        when nothing meaningful remains. Clears the buffer."""
        remainder = self._buffer
        self._buffer = ""
        if not remainder.strip():
            return None
        return remainder
