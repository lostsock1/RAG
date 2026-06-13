"""Authoring tool for the F2.4 page-anchor e2e fixture (``textbook_excerpt.pdf``).

This is a ONE-TIME fixture generator, not a test dependency: it produces a
small, digital-born, two-page textbook PDF with a real chapter -> section
heading hierarchy and body prose laid out across **two pages**, so the
real-Docling -> book-chunker e2e can prove that per-item page anchors
(``prov[0].page_no``) flow through into chunk ``page_start``/``page_end`` —
the thing the pageless Markdown fixtures cannot exercise.

Subject is **music theory**, deliberately disjoint from the eval heldout
subjects (physics/chemistry/economics/law/mathematics/biology), so committing
this fixture cannot violate the corpus span-isolation invariant.

Regenerate with::

    python apps/api/app/tests/fixtures/generate_textbook_pdf.py

Requires PyMuPDF (``fitz``), which ships transitively in the local Docling
environment. The committed ``textbook_excerpt.pdf`` is what the test reads, so
the test itself only needs Docling installed, never PyMuPDF.
"""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

OUTPUT = Path(__file__).with_name("textbook_excerpt.pdf")

PAGE_W, PAGE_H = 612.0, 792.0  # US Letter, points
LEFT, RIGHT, TOP = 72.0, 540.0, 72.0
BODY_FONT = "helv"  # Helvetica
BOLD_FONT = "hebo"  # Helvetica-Bold


# (kind, text). One page break is forced between the two chapters so the two
# chapters land on different physical pages -> distinct page anchors.
PAGE_1 = [
    ("title", "Foundations of Music Theory"),
    ("chapter", "Chapter 1: Pitch and Notation"),
    ("section", "1.1 The Staff and Clefs"),
    (
        "body",
        "The staff consists of five horizontal lines and four spaces. Each line "
        "and space represents a different pitch. A clef placed at the beginning "
        "of the staff assigns specific pitch names to those lines and spaces, so "
        "that the same symbol can stand for a high or a low register.",
    ),
    ("section", "1.2 Accidentals"),
    (
        "body",
        "An accidental is a symbol that raises or lowers the pitch of a note. A "
        "sharp raises a note by one semitone, a flat lowers a note by one "
        "semitone, and a natural cancels a previously applied sharp or flat for "
        "the remainder of the measure.",
    ),
]

PAGE_2 = [
    ("chapter", "Chapter 2: Rhythm and Meter"),
    ("section", "2.1 Note Durations"),
    (
        "body",
        "In common time a whole note lasts four beats. A half note lasts two "
        "beats, a quarter note lasts one beat, and an eighth note lasts half of "
        "one beat. Each smaller value divides the beat above it exactly in two.",
    ),
    ("section", "2.2 Time Signatures"),
    (
        "body",
        "A time signature is written as two stacked numbers. The upper number "
        "states how many beats occur in each measure, and the lower number "
        "states which note value is counted as a single beat. Together they fix "
        "the metrical pulse of the music.",
    ),
]

_STYLE = {
    "title": (BOLD_FONT, 22.0, 34.0),
    "chapter": (BOLD_FONT, 16.0, 26.0),
    "section": (BOLD_FONT, 13.0, 22.0),
    "body": (BODY_FONT, 11.0, 16.0),
}


def _render(page: fitz.Page, blocks: list[tuple[str, str]]) -> None:
    y = TOP
    for kind, text in blocks:
        font, size, leading = _STYLE[kind]
        y += leading * 0.6  # space above the block
        rect = fitz.Rect(LEFT, y, RIGHT, PAGE_H - TOP)
        spare = page.insert_textbox(
            rect, text, fontsize=size, fontname=font, lineheight=leading / size, align=0
        )
        # insert_textbox returns the remaining vertical space; consumed height is
        # rect height minus what's left.
        consumed = (PAGE_H - TOP - y) - spare
        y += consumed + leading * 0.4


def main() -> None:
    doc = fitz.open()
    _render(doc.new_page(width=PAGE_W, height=PAGE_H), PAGE_1)
    _render(doc.new_page(width=PAGE_W, height=PAGE_H), PAGE_2)
    doc.set_metadata({"title": "Foundations of Music Theory", "author": "Uber-RAG eval fixtures"})
    doc.save(str(OUTPUT), garbage=4, deflate=True)
    doc.close()
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
