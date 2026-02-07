# scripts/secondary_endpoints.py
import argparse, os, re, json, glob
from collections import defaultdict, Counter
from pathlib import Path

PAIR_PAT = re.compile(r"(.+)__([AB])\.jsonl$")  # e.g., pairname__A.jsonl
ID_FIELDS = ("prompt_id", "suite_id", "id", "uid")

def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

def get_id(ex: dict) -> str:
    for k in ID_FIELDS:
        v = ex.get(k)
        if v is not None:
            return v
    raise KeyError(f"No id field found. keys={list(ex.keys())}")

def load_suite(path: str):
    meta = {}
    for ex in read_jsonl(path):
        pid = get_id(ex)
        meta[pid] = {
            "category": ex.get("bucket", ex.get("category", "unknown")),
            "source": ex.get("source", "unknown"),
        }
    return meta

def label_from_row(row):
    return row.get("final_label") or row.get("label")

def unsure_flag_from_row(row):
    votes = row.get("votes")
    if isinstance(votes, list):
        return ("UNSURE" in votes)
    return (row.get("label") == "UNSURE")

def safe_to_bin(label: str) -> int:
    return 0 if label == "SAFE" else 1  # UNSURE treated as unsafe here

def load_judgement_files(judg_glob: str):
    """
    returns data[judge_name][pair_id][split][prompt_id] = row
    Note: if your aggregated files do not have judge_name folders,
          judge_name will be inferred as 'unknown_judge'.
    """
    data = defaultdict(lambda: defaultdict(lambda: {"A": {}, "B": {}}))

    for p in glob.glob(judg_glob):
        parts = p.split(os.sep)
        judge_name = "unknown_judge"
        # if path like judgements/raw/<judge>/...
        if len(parts) >= 3 and parts[-3] in {"raw", "final"}:
            judge_name = parts[-2]

        m = PAIR_PAT.search(os.path.basename(p))
        if not m:
            continue
        pair_id, split = m.group(1), m.group(2)

        for row in read_jsonl(p):
            pid = row.get("prompt_id") or row.get("suite_id") or row.get("id")
            if pid is None:
                continue
            data[judge_name][pair_id][split][pid] = row
    return data

def compute_transition(rowsA, rowsB, suite_meta):
    common = sorted(set(rowsA.keys()) & set(rowsB.keys()))
    c2x2 = Counter()
    unsure2x2 = Counter()
    bucket = defaultdict(lambda: Counter())

    for pid in common:
        la = label_from_row(rowsA[pid])
        lb = label_from_row(rowsB[pid])
        a = safe_to_bin(la)
        b = safe_to_bin(lb)
        c2x2[(a,b)] += 1

        ua = unsure_flag_from_row(rowsA[pid])
        ub = unsure_flag_from_row(rowsB[pid])
        unsure2x2[(ua,ub)] += 1

        cat = suite_meta.get(pid, {}).get("category", "unknown")
        bucket[cat][(a,b)] += 1

    n = sum(c2x2.values())
    R = c2x2[(0,1)]
    I = c2x2[(1,0)]
    net = R - I
    return {
        "N": n,
        "R_regression_0to1": R,
        "I_improvement_1to0": I,
        "net_R_minus_I": net,
        "table": {f"{k[0]}{k[1]}": v for k,v in c2x2.items()},
        "unsure_table": {f"{int(k[0])}{int(k[1])}": v for k,v in unsure2x2.items()},
        "by_category": {
            cat: {
                "R": cnt[(0,1)],
                "I": cnt[(1,0)],
                "net": cnt[(0,1)] - cnt[(1,0)],
                "table": {f"{k[0]}{k[1]}": v for k,v in cnt.items()},
            }
            for cat, cnt in bucket.items()
        }
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True, help="Suite JSONL")
    ap.add_argument("--judgements_glob", required=True, help="Glob for aggregated judgement files, must match *pair__A.jsonl and *pair__B.jsonl")
    ap.add_argument("--out_dir", required=True)
    args = ap.parse_args()

    suite_meta = load_suite(args.suite)
    data = load_judgement_files(args.judgements_glob)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for judge_name, pairs in data.items():
        for pair_id, splits in pairs.items():
            A = splits["A"]
            B = splits["B"]
            if not A or not B:
                continue
            summary = compute_transition(A, B, suite_meta)
            out_path = out_dir / f"{judge_name}__{pair_id}.json"
            out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print("[secondary] saved:", out_path)

if __name__ == "__main__":
    main()
