"""Read concept terms (FSN + synonyms) from a SNOMED CT RF2 release.

The back-translation confidence method (research-planning layer) needs a
*semantic index over the SNOMED terminology itself* — English FSN + synonyms
keyed by concept id — so a back-translated English term can be linked to the
concept it came from. This module is the reusable reader that feeds that index;
the embedding/Qdrant step (``build_snomed_index``) consumes what it yields.

It reads the **International-edition RF2** Snapshot directly from disk (fast,
local), mirroring the existing data-prep scripts' approach (tab-delimited RF2,
``active == "1"``, grouped by concept). The release id (e.g. ``INT_20260101``)
is derived from the file name so the built index can record exactly which
release it came from — making a rebuild with a different embedding model fully
reproducible.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# Description typeIds (RF2 metadata concepts).
FSN_TYPE = "900000000000003001"      # Fully specified name
SYNONYM_TYPE = "900000000000013009"  # Synonym


@dataclass
class ConceptTerms:
    """A concept's English terms: its FSN plus any synonyms."""
    sctid: str
    fsn: str = ""
    synonyms: list[str] = field(default_factory=list)

    @property
    def texts(self) -> list[str]:
        """All distinct terms to embed/index (FSN first, then synonyms)."""
        out: list[str] = []
        for t in ([self.fsn] if self.fsn else []) + self.synonyms:
            if t and t not in out:
                out.append(t)
        return out


def _find_one(release_root: Path | str, glob: str) -> Path:
    """The single Snapshot/Terminology file matching ``glob`` (errors if 0 or >1)."""
    base = Path(release_root) / "Snapshot" / "Terminology"
    matches = sorted(base.glob(glob))
    if not matches:
        raise FileNotFoundError(
            f"no file matching {glob!r} under {base} — is this an RF2 release root?")
    if len(matches) > 1:
        raise ValueError(f"ambiguous {glob!r} under {base}: {[m.name for m in matches]}")
    return matches[0]


def release_id(release_root: Path | str) -> str:
    """A short id for the release, e.g. ``INT_20260101`` — parsed from the
    description file name, falling back to the release directory name. Recorded
    in the index's provenance so a rebuild is reproducible."""
    release_root = Path(release_root)
    name = _find_one(release_root, "sct2_Description_Snapshot-en*.txt").name
    m = re.search(r"sct2_Description_Snapshot-en_(.+?)\.txt$", name)
    return m.group(1) if m else Path(release_root).name


# RF2 is plain tab-delimited and NOT quoted — terms legitimately contain ``"``
# (e.g. measurement units), so quote handling must be disabled or csv reads a
# field across line boundaries until it finds a "closing" quote.
def _rf2_reader(f) -> csv.DictReader:
    return csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)


def _active_concept_ids(release_root: Path) -> set[str]:
    path = _find_one(release_root, "sct2_Concept_Snapshot*.txt")
    active: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for r in _rf2_reader(f):
            if r.get("active") == "1":
                active.add(r["id"])
    return active


def read_concept_terms(
    release_root: Path | str,
    scope: set[str] | None = None,
) -> Iterator[ConceptTerms]:
    """Yield :class:`ConceptTerms` for every **active** concept with at least one
    active English FSN/synonym. ``scope`` (a set of sctids) restricts the output;
    None = the whole terminology.

    Only active descriptions of active concepts are included; acceptability
    (preferred vs acceptable per the language refset) is intentionally ignored —
    for retrieval we want *all* the surface forms a concept can be referred to by.
    """
    release_root = Path(release_root)
    active = _active_concept_ids(release_root)
    if scope is not None:
        active &= scope

    by_concept: dict[str, ConceptTerms] = {}
    desc = _find_one(release_root, "sct2_Description_Snapshot-en*.txt")
    with desc.open(encoding="utf-8") as f:
        for r in _rf2_reader(f):
            if r.get("active") != "1" or r.get("languageCode") != "en":
                continue
            cid = r.get("conceptId", "")
            if cid not in active:
                continue
            typ, term = r.get("typeId"), (r.get("term") or "").strip()
            if not term:
                continue
            ct = by_concept.get(cid)
            if ct is None:
                ct = by_concept[cid] = ConceptTerms(sctid=cid)
            if typ == FSN_TYPE and not ct.fsn:
                ct.fsn = term
            elif typ == SYNONYM_TYPE and term not in ct.synonyms:
                ct.synonyms.append(term)

    for ct in by_concept.values():
        if ct.texts:
            yield ct
