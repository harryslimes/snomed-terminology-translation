"""New-language-project provisioning core (detect / scaffold / pool sniff).

Uses a tiny synthetic RF2 fixture so the refset auto-detection is exercised
without the multi-GB real archive.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from snomed_translation import provision as P


def _make_rf2(root: Path, code: str, refset_id: str, *, double_nest: bool = False,
              extra_refset: str | None = None) -> Path:
    """Write a minimal RF2 release (Description + Language refset snapshots)."""
    edition = root / "EDITION" / "EDITION" if double_nest else root / "EDITION"
    term = edition / "Snapshot" / "Terminology"
    lang = edition / "Snapshot" / "Refset" / "Language"
    term.mkdir(parents=True)
    lang.mkdir(parents=True)
    (term / f"xsct2_Description_Snapshot-{code}_X_2025.txt").write_text(
        "id\teffectiveTime\tactive\tmoduleId\tconceptId\tlanguageCode\ttypeId\tterm\tcaseSignificanceId\n"
        f"1\t2025\t1\tm\t100\t{code}\tt\tsüda\tc\n"
        f"2\t2025\t1\tm\t101\t{code}\tt\tmaks\tc\n",
        encoding="utf-8")
    rows = ["id\teffectiveTime\tactive\tmoduleId\trefsetId\treferencedComponentId\tacceptabilityId"]
    rows += [f"a{i}\t2025\t1\tm\t{refset_id}\t{i}\t900000000000548007" for i in range(5)]
    if extra_refset:  # a few rows of a second refset to trigger the multi-id warning
        rows += [f"b{i}\t2025\t1\tm\t{extra_refset}\t{i}\t900000000000548007" for i in range(2)]
    (lang / f"xder2_cRefset_LanguageSnapshot-{code}_X_2025.txt").write_text(
        "\n".join(rows) + "\n", encoding="utf-8")
    return root / "EDITION"


def test_detect_refset_and_description(tmp_path):
    _make_rf2(tmp_path, "et", "71000181105")
    info = P.detect_snomed_archive(tmp_path / "EDITION", "et")
    assert info.language_refset_id == "71000181105"
    assert info.description_file.endswith("Description_Snapshot-et_X_2025.txt")
    assert info.term_count == 2
    assert info.warnings == []


def test_detect_handles_double_nesting(tmp_path):
    _make_rf2(tmp_path, "et", "71000181105", double_nest=True)
    info = P.detect_snomed_archive(tmp_path / "EDITION", "et")
    assert info.language_refset_id == "71000181105"
    assert (Path(info.edition_dir) / "Snapshot").is_dir()


def test_detect_warns_on_multiple_refsets(tmp_path):
    _make_rf2(tmp_path, "et", "71000181105", extra_refset="99999999999")
    info = P.detect_snomed_archive(tmp_path / "EDITION", "et")
    assert info.language_refset_id == "71000181105"  # modal wins
    assert info.warnings and "multiple language refset" in info.warnings[0]


def test_detect_missing_language_errors(tmp_path):
    _make_rf2(tmp_path, "et", "71000181105")
    with pytest.raises(ValueError, match="Description snapshot for language 'zz'"):
        P.detect_snomed_archive(tmp_path / "EDITION", "zz")


def test_scaffold_produces_repo_relative_bundle(tmp_path):
    _make_rf2(tmp_path, "et", "71000181105")
    info = P.detect_snomed_archive(tmp_path / "EDITION", "et")
    repo = tmp_path / "repo"
    res = P.scaffold_language_project(
        code="et", name="Estonian",
        configs_root=repo / "configs", data_root=repo / "data" / "languages",
        style_guide_root=repo / "style_guide", repo_root=repo, archive=info)
    pj = json.loads(Path(res.project_json).read_text())
    assert pj["language"] == {"code": "et", "name": "Estonian",
                              "direction": "EN->ET", "tokenizer_lang": "en"}
    assert pj["paths"]["data_dir"] == "data/languages/et"
    assert pj["optimization"]["hints_file"] == "configs/et/hints.yaml"
    src = json.loads((Path(res.configs_dir) / "sources" / "et_snomed.json").read_text())
    assert src["language_refset_id"] == "71000181105"
    # every scaffolded section dir exists
    for sub in ("flows", "problems", "sources", "eval_sets"):
        assert (Path(res.configs_dir) / sub).is_dir()


def test_scaffold_refuses_existing(tmp_path):
    repo = tmp_path / "repo"
    kw = dict(code="et", name="Estonian", configs_root=repo / "configs",
              data_root=repo / "data" / "languages", style_guide_root=repo / "style_guide",
              repo_root=repo)
    P.scaffold_language_project(**kw)
    with pytest.raises(ValueError, match="already exists"):
        P.scaffold_language_project(**kw)


def test_sniff_pool_columns(tmp_path):
    csv = tmp_path / "pool.csv"
    csv.write_text("EN,EE\nheart,süda\n", encoding="utf-8")
    assert P.sniff_pool_columns(csv, "et") == {"en": "EN", "target": "EE"}
    csv2 = tmp_path / "pool2.csv"
    csv2.write_text("sctid,preferred_term,translation,source\n1,heart,süda,kr\n", encoding="utf-8")
    m = P.sniff_pool_columns(csv2, "et")
    assert m["en"] == "preferred_term" and m["target"] == "translation"
    assert m["sctid"] == "sctid" and m["source"] == "source"


def test_register_pool_flags_missing_sctid(tmp_path):
    repo = tmp_path / "repo"
    (repo / "configs" / "et" / "sources").mkdir(parents=True)
    csv = tmp_path / "pool.csv"
    csv.write_text("EN,EE\nheart,süda\n", encoding="utf-8")
    spec = P.register_bilingual_pool(code="et", csv_path=csv, configs_root=repo / "configs")
    assert spec["csv_columns"] == {"en": "EN", "target": "EE"}
    assert "sctid" in spec.get("notes", "")


def test_invalid_code_rejected(tmp_path):
    repo = tmp_path / "repo"
    with pytest.raises(ValueError, match="invalid language code"):
        P.scaffold_language_project(
            code="ET", name="x", configs_root=repo / "c",
            data_root=repo / "d", style_guide_root=repo / "s")


# --- template instantiation -------------------------------------------------
def test_list_templates_has_translation_project():
    assert "translation_project" in P.list_templates()


def test_instantiate_template_wires_valid_flows(tmp_path):
    from pipelines.flow import FlowSpec
    from pipelines.problem import ProblemSpec

    cfgroot = tmp_path / "configs"
    (cfgroot / "et").mkdir(parents=True)
    res = P.instantiate_template(code="et", name="Estonian", configs_root=cfgroot)
    assert res["counts"] == {"problems": 4, "flows": 2, "sources": 3, "plan_tasks": 5}

    # flows load as FlowSpec and every input wire resolves to a node in the flow
    import glob, json
    for f in glob.glob(str(cfgroot / "et" / "flows" / "*.json")):
        spec = FlowSpec(**json.loads(open(f).read()))
        node_ids = {n.id for n in spec.nodes}
        for n in spec.nodes:
            for ref in (n.inputs or {}).values():
                assert ref in node_ids, f"dangling input {ref} in {spec.id}"
        assert spec.id.startswith("et_")

    # datasource nodes are rebound to this project's source ids
    tj = json.loads((cfgroot / "et" / "flows" / "et_translate_eval.json").read_text())
    srcs = {n["params"]["source"] for n in tj["nodes"] if n["type"] == "datasource"}
    assert srcs == {"et_test_split", "et_pool"}
    assert "{{" not in (cfgroot / "et" / "flows" / "et_translate_eval.json").read_text()

    # problem tree: single root, children point at it
    roots, parents = [], set()
    for f in glob.glob(str(cfgroot / "et" / "problems" / "*.json")):
        p = ProblemSpec(**json.loads(open(f).read()))
        (roots if not p.parent else parents).append(p.id) if not p.parent else parents.add(p.parent)
    assert roots == ["snomed-translation"] and parents == {"snomed-translation"}

    # plan tasks only reference seeded problems
    plan = json.loads((cfgroot / "et" / "problems" / ".plan.json").read_text())
    prob_ids = {P_.stem for P_ in (cfgroot / "et" / "problems").glob("*.json")}
    assert all(t["problem"] in prob_ids for t in plan["tasks"])


def test_instantiate_unknown_template(tmp_path):
    with pytest.raises(ValueError, match="unknown template"):
        P.instantiate_template(code="et", name="x", configs_root=tmp_path, template="nope")
