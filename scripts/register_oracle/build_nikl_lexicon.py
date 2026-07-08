"""Download the NIKL open dictionaries (표준국어대사전 + 우리말샘) and distil them
into a compact word -> 원어(origin) lexicon for Korean register classification.

Source: FOSS mirror github.com/spellcheck-ko/korean-dict-nikl (the National
Institute of Korean Language data, CC BY-SA 2.0 KR). Each XML <item> carries:
  <word_type>   한자어 (Sino) | 고유어 (native) | 외래어 (loan) | 혼종어 (hybrid)
  <original_language> hanja (for 한자어) / source string (for 외래어)
  <word>        headword, hyphens mark lexicographer morpheme boundaries

We stream each file, keep only (word, origin, hanja, morphemes), and delete the
raw XML so the ~2.3 GB source never fully lands on disk. Output:
  data/lexicon_nikl/nikl_origin.tsv   word \t origin \t hanja \t hyphenated
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "lexicon_nikl"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_TSV = OUT_DIR / "nikl_origin.tsv"
DONE = OUT_DIR / ".files_done"

RAW = "https://raw.githubusercontent.com/spellcheck-ko/korean-dict-nikl/master"
KRDICT = [f"krdict/{i:03d}.xml" for i in range(1, 12)]
OPENDICT = [f"opendict/{n:07d}.xml" for n in range(50000, 1250000, 50000)] + [
    "opendict/1204559.xml"
]
FILES = KRDICT + OPENDICT

ORIGIN = {"한자어": "sino", "고유어": "native", "외래어": "loan", "혼종어": "hybrid"}

ITEM = re.compile(r"<word><!\[CDATA\[(.*?)\]\]>.*?<word_type>(.*?)</word_type>", re.S)
OLANG = re.compile(r"<original_language><!\[CDATA\[(.*?)\]\]>")


def parse(xml: str, out) -> int:
    n = 0
    for m in re.finditer(r"<wordInfo>(.*?)</wordInfo>", xml, re.S):
        block = m.group(1)
        wm = re.search(r"<word><!\[CDATA\[(.*?)\]\]>", block)
        tm = re.search(r"<word_type>(.*?)</word_type>", block)
        if not wm or not tm:
            continue
        hyph = wm.group(1).strip()
        word = hyph.replace("-", "").replace("^", "").replace(" ", "")
        origin = ORIGIN.get(tm.group(1).strip(), "other")
        hm = OLANG.search(block)
        hanja = hm.group(1).strip() if hm else ""
        if word:
            out.write(f"{word}\t{origin}\t{hanja}\t{hyph}\n")
            n += 1
    return n


def load_done() -> set[str]:
    return set(DONE.read_text().split()) if DONE.exists() else set()


def main() -> None:
    done = load_done()
    mode = "a" if done else "w"
    tmp = OUT_DIR / "_tmp.xml"
    total = 0
    with OUT_TSV.open(mode, encoding="utf-8") as out:
        for i, rel in enumerate(FILES, 1):
            if rel in done:
                print(f"[{i}/{len(FILES)}] skip {rel} (done)")
                continue
            url = f"{RAW}/{rel}"
            print(f"[{i}/{len(FILES)}] fetch {rel} ...", flush=True)
            r = subprocess.run(
                ["curl", "-sL", "--max-time", "300", "-o", str(tmp), url]
            )
            if r.returncode != 0 or not tmp.exists():
                print(f"    FAILED {rel}", file=sys.stderr)
                continue
            xml = tmp.read_text(encoding="utf-8", errors="replace")
            n = parse(xml, out)
            out.flush()
            total += n
            done.add(rel)
            DONE.write_text("\n".join(sorted(done)))
            print(f"    +{n:,} entries (running {total:,})", flush=True)
            tmp.unlink(missing_ok=True)
    print(f"done: {total:,} new entries -> {OUT_TSV}")


if __name__ == "__main__":
    main()
