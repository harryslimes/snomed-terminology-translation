from fastapi import FastAPI
from snomed_graph.snomed_graph import *
import logging
import os
import re
from typing import Iterable

import yake
from serpapi import GoogleSearch
from dotenv import load_dotenv

from qdrant_client import models as qmodels

from qdrant_store import (
    BGEM3Config,
    BGEM3Embedder,
    QdrantHybridStore,
    direction_filter,
    lang_filter,
)

load_dotenv()

PATH_TO_SERIALIZED_SNOMED_GRAPH = "./data/snomed_graph/full_concept_graph.gml"
PATH_TO_STYLE_GUIDE = "./data/style_guide/style_guide.md"
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")

hierarchies_in_use = [
    "substance",
    "body structure",
    "finding",
    "disorder",
    "procedure",
    "morphologic abnormality"
]

important_attributes = {
    # 'Access (attribute)',
    # 'After (attribute)',
    'Associated finding (attribute)',
    'Associated morphology (attribute)',
    'Associated procedure (attribute)',
    'Associated with (attribute)',
    'Before (attribute)',
    'Causative agent (attribute)',
    'Characterizes (attribute)',
    # 'Clinical course (attribute)',
    'Component (attribute)',
    'Direct device (attribute)',
    'Direct morphology (attribute)',
    'Direct site (attribute)',
    'Direct substance (attribute)',
    'Due to (attribute)',
    'During (attribute)',
    # 'Finding context (attribute)',
    'Finding informer (attribute)',
    'Finding method (attribute)',
    'Finding site (attribute)',
    'Has absorbability (attribute)',
    'Has active ingredient (attribute)',
    'Has basic dose form (attribute)',
    'Has basis of strength substance (attribute)',
    'Has coating material (attribute)',
    'Has compositional material (attribute)',
    'Has concentration strength denominator unit (attribute)',
    'Has concentration strength numerator unit (attribute)',
    'Has device intended site (attribute)',
    'Has disposition (attribute)',
    'Has dose form administration method (attribute)',
    'Has dose form intended site (attribute)',
    'Has dose form release characteristic (attribute)',
    'Has dose form transformation (attribute)',
    'Has filling (attribute)',
    'Has focus (attribute)',
    'Has ingredient qualitative strength (attribute)',
    'Has intent (attribute)',
    # 'Has interpretation (attribute)',
    'Has manufactured dose form (attribute)',
    'Has precise active ingredient (attribute)',
    'Has presentation strength denominator unit (attribute)',
    'Has presentation strength numerator unit (attribute)',
    'Has realization (attribute)',
    'Has specimen (attribute)',
    'Has state of matter (attribute)',
    'Has surface texture (attribute)',
    'Has target population (attribute)',
    'Has unit of presentation (attribute)',
    'Indirect device (attribute)',
    'Indirect morphology (attribute)',
    'Inherent location (attribute)',
    'Inheres in (attribute)',
    'Interprets (attribute)',
    # 'Is a (attribute)',
    'Is modification of (attribute)',
    'Is sterile (attribute)',
    'Laterality (attribute)',
    'Measurement method (attribute)',
    'Method (attribute)',
    'Occurrence (attribute)',
    'Pathological process (attribute)',
    'Plays role (attribute)',
    'Precondition (attribute)',
    'Priority (attribute)',
    'Procedure context (attribute)',
    'Procedure device (attribute)',
    'Procedure morphology (attribute)',
    'Procedure site (attribute)',
    'Procedure site - Direct (attribute)',
    'Procedure site - Indirect (attribute)',
    'Process acts on (attribute)',
    'Process duration (attribute)',
    'Process extends to (attribute)',
    'Process output (attribute)',
    'Property (attribute)',
    'Recipient category (attribute)',
    'Relative to (attribute)',
    'Relative to part of (attribute)',
    'Revision status (attribute)',
    'Route of administration (attribute)',
    # 'Scale type (attribute)',
    # 'Severity (attribute)',
    'Specimen procedure (attribute)',
    'Specimen source identity (attribute)',
    'Specimen source morphology (attribute)',
    'Specimen source topography (attribute)',
    'Specimen substance (attribute)',
    # 'Subject relationship context (attribute)',
    'Surgical approach (attribute)',
    'Technique (attribute)',
    # 'Temporal context (attribute)',
    # 'Temporally related to (attribute)',
    # 'Time aspect (attribute)',
    # 'Units (attribute)',
    'Using access device (attribute)',
    'Using device (attribute)',
    'Using energy (attribute)',
    'Using substance (attribute)'
}

def split_markdown_into_chunks(filepath):
    """
    Load a markdown file and split it into chunks. Each chunk is a section that begins with a Level 1 heading
    denoted by a single '#' followed by a space. Any text before the first heading is ignored.
    
    Args:
        filepath (str): Path to the markdown file.
        
    Returns:
        dict: Dictionary where keys are headings (trimmed) and values are the markdown content beneath that heading.
    """
    # Regular expression to match a Level 1 heading at the beginning of a line.
    heading_regex = re.compile(r'^#\s+(.*)$')

    chunks = {}
    current_heading = None
    current_content = []

    with open(filepath, 'r', encoding='utf-8') as file:
        for line in file:
            heading_match = heading_regex.match(line)
            if heading_match:
                # If we have already been collecting content for a previous heading,
                # add it to the dictionary.
                if current_heading is not None:
                    chunks[current_heading] = ''.join(current_content).strip()
                # Start a new chunk for the new heading.
                current_heading = heading_match.group(1).strip()
                current_content = []
            elif current_heading is not None:
                # Only collect content if we've already encountered a heading.
                current_content.append(line)
    
    # Add the final chunk if exists.
    if current_heading is not None:
        chunks[current_heading] = ''.join(current_content).strip()

    return chunks

style_guide = split_markdown_into_chunks(PATH_TO_STYLE_GUIDE)
# To map the hierarchies, we need to make a couple of amendments
style_guide["disorder"] = style_guide["finding"]
style_guide["morphologic abnormality"] = style_guide["finding"]
G = SnomedGraph.from_serialized(PATH_TO_SERIALIZED_SNOMED_GRAPH)
logger = logging.getLogger("snomed.tools")

# Load the embedder once at startup. This is GPU-aware and will use fp16 on CUDA.
embedder = BGEM3Embedder(BGEM3Config())
qdrant_store = QdrantHybridStore()
app = FastAPI()


def _iter_points(result) -> Iterable:
    points = getattr(result, "points", None)
    if points is not None:
        return points
    if isinstance(result, dict):
        return result.get("points", []) or result.get("result", []) or []
    return []


def _hybrid_lookup(
    collection_name: str,
    query_text: str,
    max_results: int,
    query_filter: qmodels.Filter | None = None,
):
    dense_vec, sparse_vec = embedder.encode_query(query_text)
    result = qdrant_store.hybrid_query(
        collection_name=collection_name,
        dense_vector=dense_vec,
        sparse_vector=sparse_vec,
        limit=max_results,
        query_filter=query_filter,
    )
    return list(_iter_points(result))

@app.get("/check_concept")
async def check_concept(sctid: int):
    try:
        G.get_concept_details(sctid)        
    except:
        return False
    else:
        return True

@app.get("/snomed_graph")
async def read_root(sctid: int):
    def format_fsn(concept):
        return concept.fsn.replace(f"({concept.hierarchy})", "").strip()
    
    concept = G.get_full_concept(sctid)
    parent_concepts = [
        format_fsn(G.get_full_concept(p.sctid)) for p in concept.parents
    ]
    related_concepts = [
        format_fsn(G.get_full_concept(r.tgt.sctid))
        for g in concept.inferred_relationship_groups
        for r in g.relationships
        if r.type in important_attributes
    ]
    preferred_term = format_fsn(concept)
    synonyms = [s for s in concept.synonyms if s != preferred_term]
    return {
        "preferred_term": preferred_term,
        "hierarchy": concept.hierarchy,
        "synonyms": synonyms,
        "parent_concepts": parent_concepts, 
        "related_concepts": related_concepts,
    }


async def find_paired_translations(text: str, where_: str, topn: int = 3) -> list[str]:
    kw_extractor = yake.KeywordExtractor(
        lan="en" if where_ == "EN->EE" else "et",
        n=1,
        dedupLim=0.7,
        top=10,
    )
    keywords = [kw for kw, _ in kw_extractor.extract_keywords(text)]
    if text not in keywords:
        keywords = [text, *keywords]

    filt = direction_filter(where_)
    hits_by_id: dict[str, tuple[float, dict]] = {}

    for keyword in keywords:
        try:
            hits = _hybrid_lookup(
                collection_name="paired_translations",
                query_text=keyword,
                max_results=max(topn * 3, topn),
                query_filter=filt,
            )
        except Exception as exc:  # pragma: no cover - runtime system dependency
            logger.warning("Paired translation lookup failed for %r: %s", keyword, exc)
            continue

        for point in hits:
            payload = getattr(point, "payload", {}) or {}
            pid = str(getattr(point, "id", payload.get("id", "")))
            score = float(getattr(point, "score", 0.0))
            if not pid:
                continue
            prev = hits_by_id.get(pid)
            if prev is None or score > prev[0]:
                hits_by_id[pid] = (score, payload)

    ranked = sorted(hits_by_id.values(), key=lambda item: item[0], reverse=True)
    top_payloads = [payload for _, payload in ranked[:topn]]
    return [(p.get("text", ""), p.get("translation", "")) for p in top_payloads]
    
@app.get("/paired_translations_en_to_ee")
async def get_paired_translations_en_to_ee(preferred_term: str, max_results: int = 1):    
    results = await find_paired_translations(preferred_term, "EN->EE", max_results)
    return [
        {"en": en, "ee": ee}
        for en, ee in results
    ]

# I wish I'd realised I was mixing "ET" and "EE" in the codebase.
# Now, it's just a damn nightmare.
@app.get("/paired_translations_ee_to_en")
async def get_paired_translations_ee_to_en(preferred_term: str, max_results: int = 1):    
    results = await find_paired_translations(preferred_term, "ET->EN", max_results)
    return [
        {"en": en, "ee": ee}
        for ee, en in results
    ]

@app.get("/sonaveeb")
async def sonaveeb_lookup(estonian_term: str, max_results: int = 1):
    try:
        hits = _hybrid_lookup(
            collection_name="sonaveeb",
            query_text=estonian_term,
            max_results=max_results,
            query_filter=lang_filter("et"),
        )
    except Exception as exc:  # pragma: no cover - depends on runtime services
        logger.warning("Sonaveeb lookup failed: %s", exc)
        return []

    results = []
    for point in hits:
        payload = getattr(point, "payload", {}) or {}
        term = payload.get("term") or payload.get("doc_id") or str(getattr(point, "id", ""))
        definition = payload.get("definition") or payload.get("text", "")
        if term:
            results.append({"term": term, "definition": definition})
    return results
    
@app.get("/eesti_arst")
async def eesti_arst_lookup(estonian_term: str, max_results: int = 1):
    try:
        hits = _hybrid_lookup("eesti_arst", estonian_term, max_results)
    except Exception as exc:  # pragma: no cover - depends on runtime services
        logger.warning("eesti_arst lookup failed: %s", exc)
        return []

    return [
        {
            "source": f"eesti_arst/{(getattr(point, 'payload', {}) or {}).get('doc_id', getattr(point, 'id', ''))}",
            "passage": (getattr(point, "payload", {}) or {}).get("text", ""),
        }
        for point in hits
    ]
    
@app.get("/kliinikum")
async def kliinikum_lookup(estonian_term: str, max_results: int = 1):
    try:
        hits = _hybrid_lookup("kliinikum", estonian_term, max_results)
    except Exception as exc:  # pragma: no cover - depends on runtime services
        logger.warning("kliinikum lookup failed: %s", exc)
        return []

    return [
        {
            "source": f"kliinikum/{(getattr(point, 'payload', {}) or {}).get('doc_id', getattr(point, 'id', ''))}",
            "passage": (getattr(point, "payload", {}) or {}).get("text", ""),
        }
        for point in hits
    ]

# @app.get("/ravimregister")
# async def ravimregister_lookup(estonian_term: str, max_results: int = 1):
#     collection = chromadb_client.get_collection("ravimregister")
#     results = collection.query(
#         query_texts=[estonian_term],
#         n_results=max_results,
#     )
#     return [
#         {"source": f"ravimregister/SPC/{doc}", "passage": passage}
#         for doc, passage in zip(results["ids"][0], results["documents"][0])
#     ]

@app.get("/haiglateliit")
async def haiglateliit_lookup(estonian_term: str, max_results: int = 1):
    try:
        hits = _hybrid_lookup("haiglateliit", estonian_term, max_results)
    except Exception as exc:  # pragma: no cover - depends on runtime services
        logger.warning("haiglateliit lookup failed: %s", exc)
        return []

    return [
        {
            "source": f"haiglateliit/{(getattr(point, 'payload', {}) or {}).get('doc_id', getattr(point, 'id', ''))}",
            "passage": (getattr(point, "payload", {}) or {}).get("text", ""),
        }
        for point in hits
    ]

@app.get("/style_guide")
async def style_guide_lookup(hierarchy: str):        
    return  {
        "general": style_guide.get("general", "No specific guidance required."),
        "specific": style_guide.get(hierarchy, "No specific guidance required.")
    }
    
@app.get("/web_search")
async def web_search(estonian_term: str, max_results: int = 1):
    params = {
        "engine": "google_light",
        "domain": "google.ee",
        "q": estonian_term,
        "num": max_results,
        "hl": "et",        # restrict results to Estonian language
        "gl": "ee",
        "api_key": SERPAPI_API_KEY
    }
    search = GoogleSearch(params)
    results = search.get_dict()
    return [
        {"title": result["title"], "snippet": result["snippet"]}
        for result in results.get("organic_results", [])
    ]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8008)
