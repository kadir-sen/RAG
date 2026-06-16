"""Timeline→document fallback signal — _timeline_graph_miss (no network/LLM).

The light_graph only holds docs whose notice metadata extracted successfully — a
strict subset of the vector store. When a timeline question targets a doc the
graph lacks, the executor must fall back to document RAG instead of returning an
empty/"not found" answer. These tests pin the deterministic miss detector.
"""
from src.query_planner import PlanExecutor


class _FakeGraph:
    def __init__(self, nodes):
        self._nodes = nodes

    def timeline(self):
        return self._nodes


def _executor(nodes):
    ex = PlanExecutor()
    ex._light_graph = _FakeGraph(nodes)  # bypass lazy property / real graph
    return ex


# A graph that has OTHER correspondence, but NOT the CCTV notification.
_OTHER_NODES = [
    {"subject": "Concrete pour schedule", "sender": "Turner", "recipient": "Remco",
     "file_name": "concrete_letter.pdf", "doc_type": "letter", "ref_numbers": ["L-101"]},
    {"subject": "Manpower mobilization", "sender": "Multiplex", "recipient": "MVP",
     "file_name": "manpower_memo.pdf", "doc_type": "memo", "ref_numbers": []},
]

_CCTV_NODE = {
    "subject": "CCTV delay notification", "sender": "Turner", "recipient": "Multiplex",
    "file_name": "cctv_delay_notice.pdf", "doc_type": "notification",
    "ref_numbers": ["N-CCTV-01"],
}

_INSTRUCTION = "Identify the sender and date of the CCTV delay notification"


def test_keyword_miss_when_no_node_mentions_target():
    # Graph has other notices but nothing about CCTV → miss → fall back.
    ex = _executor(_OTHER_NODES)
    result = {"answer": "The notification was issued by Turner.", "sources": [{"doc_id": "x"}]}
    assert ex._timeline_graph_miss(_INSTRUCTION, result) is True


def test_hit_when_a_node_matches_target():
    # Graph contains the CCTV node and a real answer → NOT a miss.
    ex = _executor(_OTHER_NODES + [_CCTV_NODE])
    result = {
        "answer": "The CCTV delay notification was sent by Turner on 2024-03-26.",
        "sources": [{"doc_id": "cctv", "file_name": "cctv_delay_notice.pdf"}],
    }
    assert ex._timeline_graph_miss(_INSTRUCTION, result) is False


def test_empty_sources_is_miss():
    ex = _executor(_OTHER_NODES + [_CCTV_NODE])
    result = {"answer": "Something", "sources": []}
    assert ex._timeline_graph_miss(_INSTRUCTION, result) is True


def test_empty_graph_sentinel_is_miss():
    ex = _executor([])
    result = {"answer": "No documents in the timeline graph.", "sources": []}
    assert ex._timeline_graph_miss(_INSTRUCTION, result) is True


def test_not_found_answer_is_miss_even_with_matching_node():
    # Node matches keywords, but the synthesized answer is a negative → still a miss.
    ex = _executor([_CCTV_NODE])
    result = {
        "answer": "I could not find the CCTV delay notification in the timeline data.",
        "sources": [{"doc_id": "cctv"}],
    }
    assert ex._timeline_graph_miss(_INSTRUCTION, result) is True


def test_salient_terms_extracts_acronyms_and_doctypes():
    ex = _executor([])
    terms = ex._salient_terms('Who sent the "Final Notice" RFI letter?')
    assert "final notice" in terms   # quoted
    assert "rfi" in terms            # acronym
    assert "letter" in terms         # doc-type keyword
