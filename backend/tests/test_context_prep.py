from app.services.context_prep import drop_duplicates, merge_adjacent, tidy_chunks
from app.services.retrieval_service import RetrievedChunk


def chunk(text, index=0, score=0.8, doc="d1"):
    return RetrievedChunk(document_id=doc, filename=f"{doc}.md", page_number=1, chunk_index=index, text=text, score=score)


def test_contained_and_near_identical_chunks_keep_only_the_best_score():
    full = "The primary model is llama with temperature 0.1 for grounded answers across all queries."
    out = drop_duplicates([chunk(full[:40], 0, 0.7), chunk(full, 1, 0.9, "d2"), chunk(full.upper(), 2, 0.6, "d3")])
    assert [c.score for c in out] == [0.9]


def test_distinct_chunks_are_all_kept_in_order():
    out = drop_duplicates([chunk("alpha beta gamma", 0, 0.9), chunk("delta epsilon zeta", 5, 0.8)])
    assert [c.chunk_index for c in out] == [0, 5]


def test_consecutive_chunks_join_without_repeating_the_overlap():
    a = "First part of the section. " + "x" * 30 + " shared overlap text here"
    b = "shared overlap text here and then the rest of the section."
    (merged,) = merge_adjacent([chunk(b, 4, 0.7), chunk(a, 3, 0.9)])
    assert merged.text == a + b[len("shared overlap text here"):]
    assert merged.score == 0.9 and merged.chunk_index == 3


def test_neighbours_without_overlap_are_separated_by_a_blank_line():
    (merged,) = merge_adjacent([chunk("one", 1), chunk("two", 2)])
    assert merged.text == "one\n\ntwo"


def test_gaps_and_other_documents_stay_separate_and_sorted_by_score():
    out = merge_adjacent([chunk("a", 1, 0.5), chunk("b", 4, 0.9), chunk("c", 2, 0.7, "d2")])
    assert [c.text for c in out] == ["b", "c", "a"]


def test_tidy_handles_empty_and_single():
    assert tidy_chunks([]) == []
    only = chunk("hello")
    assert tidy_chunks([only]) == [only]
