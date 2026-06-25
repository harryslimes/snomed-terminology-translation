"""The RF2 concept-terms reader (feeds the SNOMED semantic index)."""
from __future__ import annotations

from pathlib import Path

import pytest

from snomed_translation.snomed_rf2 import (
    FSN_TYPE,
    SYNONYM_TYPE,
    read_concept_terms,
    release_id,
)

_CONCEPT_COLS = "id\teffectiveTime\tactive\tmoduleId\tdefinitionStatusId"
_DESC_COLS = ("id\teffectiveTime\tactive\tmoduleId\tconceptId\tlanguageCode"
              "\ttypeId\tterm\tcaseSignificanceId")


def _fake_release(tmp: Path, *, concepts: list[tuple[str, str]],
                  descriptions: list[tuple]) -> Path:
    """Write a minimal RF2 Snapshot. concepts=[(id, active)],
    descriptions=[(id, active, conceptId, lang, typeId, term)]."""
    term = tmp / "Snapshot" / "Terminology"
    term.mkdir(parents=True)
    (term / "sct2_Concept_Snapshot_INT_20260101.txt").write_text(
        _CONCEPT_COLS + "\n"
        + "".join(f"{cid}\t20260101\t{act}\t900\t900000000000074008\n"
                  for cid, act in concepts), encoding="utf-8")
    (term / "sct2_Description_Snapshot-en_INT_20260101.txt").write_text(
        _DESC_COLS + "\n"
        + "".join(f"{i}\t20260101\t{act}\t900\t{cid}\t{lang}\t{typ}\t{txt}\t900000000000448009\n"
                  for i, (act, cid, lang, typ, txt) in enumerate(descriptions, 1)),
        encoding="utf-8")
    return tmp


def test_reads_fsn_and_synonyms(tmp_path):
    root = _fake_release(
        tmp_path,
        concepts=[("22298006", "1"), ("999", "0")],   # one active, one inactive
        descriptions=[
            ("1", "22298006", "en", FSN_TYPE, "Myocardial infarction (disorder)"),
            ("1", "22298006", "en", SYNONYM_TYPE, "Heart attack"),
            ("1", "22298006", "en", SYNONYM_TYPE, "Cardiac infarction"),
            ("0", "22298006", "en", SYNONYM_TYPE, "retired synonym"),   # inactive desc
            ("1", "22298006", "sv", SYNONYM_TYPE, "hjärtinfarkt"),       # non-English
            ("1", "999", "en", FSN_TYPE, "Inactive concept (disorder)"),  # inactive concept
        ],
    )
    out = {c.sctid: c for c in read_concept_terms(root)}
    assert set(out) == {"22298006"}                  # inactive concept excluded
    c = out["22298006"]
    assert c.fsn == "Myocardial infarction (disorder)"
    assert c.synonyms == ["Heart attack", "Cardiac infarction"]   # active EN only
    assert c.texts[0] == c.fsn and "Heart attack" in c.texts


def test_term_with_embedded_quote(tmp_path):
    # RF2 is unquoted; a term containing a double-quote must not break parsing
    # (regression: default csv dialect runs the field across lines).
    root = _fake_release(
        tmp_path, concepts=[("1", "1"), ("2", "1")],
        descriptions=[('1', "1", "en", FSN_TYPE, 'Diameter 5 " catheter (object)'),
                      ('1', "2", "en", FSN_TYPE, "Plain (finding)")],
    )
    out = {c.sctid: c for c in read_concept_terms(root)}
    assert out["1"].fsn == 'Diameter 5 " catheter (object)'
    assert out["2"].fsn == "Plain (finding)"


def test_scope_restricts_output(tmp_path):
    root = _fake_release(
        tmp_path,
        concepts=[("1", "1"), ("2", "1")],
        descriptions=[("1", "1", "en", FSN_TYPE, "One (x)"),
                      ("1", "2", "en", FSN_TYPE, "Two (x)")],
    )
    assert {c.sctid for c in read_concept_terms(root, scope={"2"})} == {"2"}


def test_release_id_parsed_from_filename(tmp_path):
    root = _fake_release(tmp_path, concepts=[("1", "1")],
                         descriptions=[("1", "1", "en", FSN_TYPE, "X (y)")])
    assert release_id(root) == "INT_20260101"
    assert release_id(str(root)) == "INT_20260101"   # accepts a str path too


def test_missing_release_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        list(read_concept_terms(tmp_path))
