"""Verify the fixture corpus documents contain expected ground-truth content."""
import pytest
from pathlib import Path

CORPUS_DIR = Path(__file__).parent / "fixtures" / "sample_corpus"

# Map question IDs to (filename, required_keywords)
QUESTION_GROUND_TRUTH = {
    "h01": ("physics_textbook_ch3_thermodynamics.md", ["entropy", "isolated system", "never decreases"]),
    "h04": ("chemistry_textbook_ch4_reactions.md", ["activation energy", "not consumed", "reaction rate"]),
    "h10": ("biology_textbook_ch5_cells.md", ["light energy", "chemical energy", "chlorophyll", "carbon dioxide", "glucose"]),
    "h12": ("economics_textbook_ch2_markets.md", ["general increase", "prices", "purchasing power"]),
    "h13": ("chemistry_textbook_ch4_reactions.md", ["shared", "electrons", "atoms"]),
    "h16": ("physics_textbook_ch3_thermodynamics.md", ["6.674"]),
    "h19": ("physics_textbook_ch3_thermodynamics.md", ["gravitational", "electromagnetic", "strong nuclear", "weak nuclear"]),
    "h25": ("psychology_textbook_ch8_grief.md", ["denial", "anger", "bargaining", "depression", "acceptance"]),
    "h29": ("physics_textbook_ch3_thermodynamics.md", ["PV = nRT", "pressure", "volume", "gas constant"]),
    "h31": ("physics_textbook_ch3_thermodynamics.md", ["V = IR", "voltage", "current", "resistance"]),
    "n03": ("geography_demographics_table.md", ["Liechtenstein", "39,584"]),
    "n06": ("physics_textbook_ch3_thermodynamics.md", ["1883", "-0.21"]),
    "n12": ("mineralogy_textbook_appendix.md", ["grossular", "8-fold", "symmetry"]),
    "n15": ("history_textbook_ch12_treaties.md", ["Treaty of Lausanne", "never ratified"]),
    "n19": ("history_textbook_ch12_treaties.md", ["Zeno", "Achilles"]),
}

@pytest.mark.parametrize("question_id,doc_name,keywords", [
    (qid, doc, kws) for qid, (doc, kws) in QUESTION_GROUND_TRUTH.items()
])
def test_corpus_document_contains_ground_truth(question_id, doc_name, keywords):
    doc_path = CORPUS_DIR / doc_name
    assert doc_path.exists(), f"Corpus document {doc_name} not found"
    content = doc_path.read_text().casefold()
    for kw in keywords:
        assert kw.casefold() in content, f"Question {question_id}: keyword '{kw}' not found in {doc_name}"

def test_all_corpus_documents_exist():
    expected_docs = {
        "physics_textbook_ch3_thermodynamics.md",
        "chemistry_textbook_ch4_reactions.md",
        "biology_textbook_ch5_cells.md",
        "economics_textbook_ch2_markets.md",
        "psychology_textbook_ch8_grief.md",
        "geography_demographics_table.md",
        "mineralogy_textbook_appendix.md",
        "history_textbook_ch12_treaties.md",
    }
    actual_docs = {f.name for f in CORPUS_DIR.glob("*.md")}
    assert expected_docs.issubset(actual_docs), f"Missing docs: {expected_docs - actual_docs}"
