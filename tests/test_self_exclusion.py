"""Leakage-free exemplars: sctid self-exclusion in retrieval + provenance in
the rendered exemplar table. `lookup_pairs` needs an embedder + Qdrant store, so
we drive it with fakes that return a fixed candidate set (independent of the
query) and assert the filtering/reporting contract."""
from __future__ import annotations

from scripts.translation.translate_korean_with_lookup import (
    format_pairs_table,
    lookup_pairs,
)


class _Pt:
    def __init__(self, pid, score, payload):
        self.id, self.score, self.payload = pid, score, payload


class _Res:
    def __init__(self, points):
        self.points = points


class _Store:
    def __init__(self, points):
        self._points = points

    def hybrid_query(self, **_):
        return _Res(self._points)


class _Emb:
    def encode_query(self, _text):
        return ([0.0], None)


def _points():
    # Two descriptions of the QUERY concept (719169005) at the top — the leak —
    # then unrelated concepts and a non-SNOMED (EDI, no sctid) row.
    return [
        _Pt(1, 0.99, {"text": "Ultrasonography of oral cavity (procedure)",
                      "translation": "구강 초음파 검사", "row_source": "SNOMED",
                      "sctid": "719169005"}),
        _Pt(2, 0.98, {"text": "Ultrasonography of oral cavity",
                      "translation": "구강 초음파 촬영",
                      "row_source": "SNOMED_synonyms", "sctid": "719169005"}),
        _Pt(3, 0.80, {"text": "Ultrasonography (procedure)",
                      "translation": "초음파 촬영", "row_source": "SNOMED",
                      "sctid": "16310003"}),
        _Pt(4, 0.75, {"text": "oral cavity", "translation": "구강",
                      "row_source": "EDI", "sctid": ""}),
    ]


def test_self_exclusion_drops_query_concept_and_reports():
    kept, excluded = lookup_pairs(
        _Emb(), _Store(_points()), "c", "Ultrasonography of oral cavity",
        topn=3, exclude_sctid="719169005")
    # The query concept's own canonical entries are gone from the shown set...
    assert "719169005" not in {r[3] for r in kept}
    # ...and both were reported as excluded, with rank + provenance preserved.
    assert len(excluded) == 2
    assert all(e[3] == "719169005" for e in excluded)
    assert excluded[0][4] == 1 and excluded[1][4] == 2       # ranks recorded
    # Unrelated concepts survive, carrying [en, ko, source, sctid].
    assert {r[3] for r in kept} == {"16310003", ""}
    assert all(len(r) == 4 for r in kept)


def test_no_exclude_sctid_keeps_everything():
    kept, excluded = lookup_pairs(
        _Emb(), _Store(_points()), "c", "x", topn=3)
    assert excluded == []
    assert len(kept) == 3


def test_format_pairs_table_renders_provenance():
    table = format_pairs_table([["Ultrasonography", "초음파", "SNOMED", "1"]])
    assert "|Source|" in table and "|SNOMED|" in table
    # Legacy 2-element rows still render without a Source column.
    legacy = format_pairs_table([["Ultrasonography", "초음파"]])
    assert "Source" not in legacy
