from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.streaming_verifier import SentenceAssembler


def test_assembler_yields_sentence_at_boundary_across_tokens():
    assembler = SentenceAssembler()
    assert assembler.feed("The second ") == []
    assert assembler.feed("law holds") == []
    out = assembler.feed(". Entropy")
    assert out == ["The second law holds. "]


def test_assembler_preserves_text_fidelity():
    """Concatenating every emitted sentence plus the remainder must reproduce
    the fed text byte-for-byte (token events must reconstruct the answer)."""
    fragments = ["First fact. ", "Second", " fact!  ", "Third one? ", "Tail without end"]
    assembler = SentenceAssembler()
    emitted: list[str] = []
    for fragment in fragments:
        emitted.extend(assembler.feed(fragment))
    tail = assembler.flush()
    reconstructed = "".join(emitted) + (tail or "")
    assert reconstructed == "".join(fragments)


def test_assembler_multiple_boundaries_in_one_feed():
    assembler = SentenceAssembler()
    out = assembler.feed("One. Two! Three? Rest")
    assert out == ["One. ", "Two! ", "Three? "]
    assert assembler.flush() == "Rest"


def test_assembler_does_not_split_decimals():
    assembler = SentenceAssembler()
    assert assembler.feed("It weighs 3.5 kg total") == []
    assert assembler.flush() == "It weighs 3.5 kg total"


def test_assembler_splits_abbreviations_like_the_verifier():
    """Deliberate: 'Dr. Smith' splits, exactly as the verifiers'
    re.split(r'(?<=[.!?])\\s+', ...) does — consistency over perfection."""
    assembler = SentenceAssembler()
    out = assembler.feed("Dr. Smith agrees")
    assert out == ["Dr. "]
    assert assembler.flush() == "Smith agrees"


def test_assembler_waits_for_whitespace_after_punctuation():
    """A buffer ending exactly at '.' is not yet a boundary — the next token
    may continue the same construct (e.g. '3.' + '5')."""
    assembler = SentenceAssembler()
    assert assembler.feed("Done.") == []
    out = assembler.feed(" Next")
    assert out == ["Done. "]


def test_assembler_flush_returns_none_for_whitespace_only_remainder():
    assembler = SentenceAssembler()
    assembler.feed("Complete sentence. ")
    assert assembler.flush() is None


def test_assembler_flush_returns_none_when_empty():
    assert SentenceAssembler().flush() is None


def test_assembler_flush_clears_buffer():
    assembler = SentenceAssembler()
    assembler.feed("Trailing words")
    assert assembler.flush() == "Trailing words"
    assert assembler.flush() is None
