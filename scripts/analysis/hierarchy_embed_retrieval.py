"""Benchmark SNOMED-hierarchy-trained embedding models vs BGE-M3 for back-translation retrieval.

Tests HiT + OnT (hyperbolic hierarchy encoders) and a plain SBERT-MiniLM baseline
(externally supplied in example_ret_script/, SNOMED 20250901, MiniLM-L12 base) on
recall of the source concept from back-translated English queries, vs our BGE-M3
hybrid index. Scores HiT/OnT by Poincare distance (nearest concept), SBERT by
cosine; GPU-batched. Reads a sample CSV (sctid,query,hierarchy,bge_rank).

Setup (one-off): from example_ret_script/, `uv pip install geoopt && uv pip install -e . --no-deps`,
then run THIS script FROM example_ret_script/ (it uses ./models, ./embeddings):
    python hierarchy_embed_retrieval.py <sample_dir_with_ret_sample.csv>

Result (2,159-concept stratified sample): HiT 49.0 / OnT 50.2 / SBERT-MiniLM 49.9
recall@1 vs BGE-M3 61.6 — the hierarchy models do not help flat concept retrieval
(they are trained for subsumption, on a weaker MiniLM base).
"""
import csv, json, sys, numpy as np, torch
sys.path.insert(0, ".")
from hierarchy_transformers import HierarchyTransformer
from OnT.OnT import OntologyTransformer
from sentence_transformers import SentenceTransformer

SCRATCH = sys.argv[1]; dev = "cuda"
samp = list(csv.DictReader(open(f"{SCRATCH}/ret_sample.csv")))
queries = [r["query"] for r in samp]; gold = [r["sctid"] for r in samp]
mm = json.load(open("embeddings/entity_mappings.json"))
row_sctid = np.array([m["iri"].rsplit("/", 1)[-1] for m in mm])
present = set(row_sctid)
keep = [i for i, g in enumerate(gold) if g in present]
gold_keep = [gold[i] for i in keep]
qkeep = [queries[i] for i in keep]
print(f"queries={len(samp)} present={len(keep)}", flush=True)


def recall(ranks):
    n = len(ranks); at = lambda k: 100 * sum(1 for r in ranks if 0 < r <= k) / n
    return n, at(1), at(5), at(10)


def topk_hyp(Q, V, k, bs=64):
    Vt = torch.tensor(V, device=dev); vn = (Vt * Vt).sum(1)
    inv = 1.0 / np.sqrt(k); out = []
    for s in range(0, len(Q), bs):
        U = torch.tensor(Q[s:s + bs], device=dev); un = (U * U).sum(1)
        l2 = un[:, None] + vn[None, :] - 2 * U @ Vt.T
        denom = (1 - k * un)[:, None] * (1 - k * vn)[None, :]
        arg = torch.clamp(1 + 2 * k * l2 / (denom + 1e-7), min=1.0)
        d = inv * torch.acosh(arg)
        out.append(torch.topk(d, 10, dim=1, largest=False).indices.cpu().numpy())
    return np.concatenate(out)


def topk_cos(Q, V, bs=256):
    Vt = torch.tensor(V, device=dev); Vt = Vt / Vt.norm(dim=1, keepdim=True).clamp_min(1e-9)
    out = []
    for s in range(0, len(Q), bs):
        U = torch.tensor(Q[s:s + bs], device=dev); U = U / U.norm(dim=1, keepdim=True).clamp_min(1e-9)
        out.append(torch.topk(U @ Vt.T, 10, dim=1, largest=True).indices.cpu().numpy())
    return np.concatenate(out)


def eval_topidx(topidx):
    rs = []
    for j, g in enumerate(gold_keep):
        top = row_sctid[topidx[j]]
        rs.append(next((p + 1 for p, sid in enumerate(top) if sid == g), 0))
    return recall(rs)


res = {}
hit = HierarchyTransformer.from_pretrained("./models/HiT-FULL-SNOMED-20250901-MiniLM-L12-V2-BASE-BS-512-EBS-256-EPOCH-1/final")
kH = float(hit.get_circum_poincareball(hit.embed_dim).c)
Vh = np.load("embeddings/hit-snomed-25-mixed-random-embs.npy").astype(np.float32)
Qh = hit.encode(qkeep).astype(np.float32)
res["HiT"] = eval_topidx(topk_hyp(Qh, Vh, kH)); print("HiT done", flush=True); del Vh

ont = OntologyTransformer.from_pretrained("./models/OnTr-SNOMED-FULL-20250901-MiniLM-L12-V2-BASE-BS-42-EBS-24-EPOCH-1/final")
kO = float(ont.hit_model.get_circum_poincareball(ont.hit_model.embed_dim).c)
Vo = np.load("embeddings/ont-snomed-25-embs.npy").astype(np.float32)
Qo = ont.encode_concept(qkeep).astype(np.float32)
res["OnT"] = eval_topidx(topk_hyp(Qo, Vo, kO)); print("OnT done", flush=True); del Vo

sb = SentenceTransformer("sentence-transformers/all-MiniLM-L12-v2")
Vs = np.load("embeddings/sbert-plm-embeddings.npy").astype(np.float32)
Qs = sb.encode(qkeep).astype(np.float32)
res["SBERT-MiniLM"] = eval_topidx(topk_cos(Qs, Vs)); print("SBERT done", flush=True)

res["BGE-M3(hybrid)"] = recall([int(samp[i]["bge_rank"]) for i in keep])
print(f"\n{'model':16s} {'n':>5} {'r@1':>6} {'r@5':>6} {'r@10':>6}", flush=True)
for k, (n, a1, a5, a10) in res.items():
    print(f"{k:16s} {n:>5} {a1:6.1f} {a5:6.1f} {a10:6.1f}", flush=True)
