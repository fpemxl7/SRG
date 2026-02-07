# scripts/make_suite.py
import argparse
import json
import random
import hashlib
from pathlib import Path
from collections import defaultdict, Counter

CATEGORIES = ["self_harm", "weapons", "drugs", "cybercrime", "hate_harassment", "sexual_exploitation"]
ID_FIELDS = ("prompt_id", "suite_id", "id", "uid")

def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def map_to_bucket(rec) -> str | None:
    """
    Map a prompt record into one of CATEGORIES (or None if out of scope).
    The mapping is deterministic and conservative.
    """
    src = (rec.get("source") or "").lower()
    cat = rec.get("category") or {}
    prompt = (rec.get("prompt") or "").lower()

    # AIR-Bench mapping
    if "air-bench" in src or src == "air-bench-2024":
        l2 = (cat.get("l2") or "").strip().lower()
        l3 = (cat.get("l3") or "").strip().lower()
        l4 = (cat.get("l4") or "").strip().lower()

        if "self-harm" in l2:
            return "self_harm"

        if "weapon usage & development" in l3:
            return "weapons"
        if "violence" in l2 and ("weapon" in l3 or "weapon" in l4):
            return "weapons"

        if l2 == "security risks":
            return "cybercrime"
        if l3 in {"confidentiality", "integrity"}:
            return "cybercrime"
        if "network intrusion" in l4 or "malware" in l4 or "hacking" in l3:
            return "cybercrime"

        if l2 == "hate/toxicity":
            return "hate_harassment"
        if l3 in {"harassment", "hate speech (inciting/promoting/expressing hatred)"}:
            return "hate_harassment"

        if l2 in {"sexual content", "child harm"}:
            return "sexual_exploitation"
        if "adult content" in l3:
            return "sexual_exploitation"

        if l2 == "illicit behavior":
            # drugs/weapons/cyber often live here; use keywords as a fallback
            if "drug" in prompt or "cocaine" in prompt or "meth" in prompt:
                return "drugs"
            if "weapon" in prompt or "gun" in prompt or "bomb" in prompt:
                return "weapons"
            if "hack" in prompt or "malware" in prompt:
                return "cybercrime"
            return "drugs"

        return None

    # Generic fallback mapping for other sources
    if any(k in prompt for k in ["kill myself", "suicide", "self harm", "self-harm"]):
        return "self_harm"
    if any(k in prompt for k in ["gun", "bomb", "weapon", "explosive"]):
        return "weapons"
    if any(k in prompt for k in ["cocaine", "meth", "heroin", "drug"]):
        return "drugs"
    if any(k in prompt for k in ["hack", "phishing", "malware", "exploit"]):
        return "cybercrime"
    if any(k in prompt for k in ["hate", "racial", "slur", "harass"]):
        return "hate_harassment"
    if any(k in prompt for k in ["child", "sexual", "exploit", "rape"]):
        return "sexual_exploitation"
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in_pool", required=True, help="Prompt pool JSONL")
    ap.add_argument("--out_suite", required=True, help="Suite JSONL")
    ap.add_argument("--out_report", required=True, help="Suite report JSON")
    ap.add_argument("--out_hash", required=True, help="SHA256 file path")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--k_per_cat", type=int, default=25)
    ap.add_argument("--suite_prefix", default="S_v1")
    args = ap.parse_args()

    random.seed(args.seed)

    buckets = defaultdict(list)
    raw_n = 0
    for rec in read_jsonl(Path(args.in_pool)):
        raw_n += 1
        b = map_to_bucket(rec)
        if b is None:
            continue
        rec2 = dict(rec)
        rec2["_bucket"] = b
        buckets[b].append(rec2)

    # sample
    suite_rows = []
    stats = {}
    idx = 0
    for b in CATEGORIES:
        pool = buckets.get(b, [])
        if len(pool) < args.k_per_cat:
            raise RuntimeError(f"Not enough samples for bucket={b}: have={len(pool)}, need={args.k_per_cat}")
        sampled = random.sample(pool, args.k_per_cat)
        stats[b] = {"pool": len(pool), "picked": len(sampled)}
        for r in sampled:
            idx += 1
            suite_rows.append({
                "prompt_id": f"{args.suite_prefix}_{idx:04d}",
                "prompt": r.get("prompt"),
                "bucket": b,
                "source": r.get("source", "unknown"),
                "meta": {
                    "orig_id": next((r.get(k) for k in ID_FIELDS if r.get(k) is not None), None),
                    "category": r.get("category", None),
                }
            })

    out_suite = Path(args.out_suite)
    write_jsonl(out_suite, suite_rows)

    digest = sha256_file(out_suite)
    out_hash = Path(args.out_hash)
    out_hash.parent.mkdir(parents=True, exist_ok=True)
    out_hash.write_text(digest + "\n", encoding="utf-8")

    report = {
        "in_pool": str(args.in_pool),
        "raw_records": raw_n,
        "seed": args.seed,
        "k_per_cat": args.k_per_cat,
        "categories": CATEGORIES,
        "picked_total": len(suite_rows),
        "bucket_stats": stats,
        "suite_sha256": digest,
    }
    out_report = Path(args.out_report)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[suite] wrote: {out_suite} (n={len(suite_rows)})")
    print(f"[suite] sha256: {digest}")

if __name__ == "__main__":
    main()
