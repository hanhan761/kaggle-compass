#!/usr/bin/env python3
"""Kaggle Compass 0.1: module retrieval and paired behavioral evidence."""
import argparse
import ast
import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

VERSION = "0.1.0"
ENCODER = {"name": "lexical-ast-blake2b-v1", "revision": VERSION,
           "pooling": "signed-hash-l2", "dimensions": 256}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def emit(value, out=None):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def normalize(vector, dimensions):
    if not isinstance(vector, list) or len(vector) != dimensions:
        raise ValueError("vector dimensions mismatch")
    if any(isinstance(x, bool) or not isinstance(x, (int, float))
           or not math.isfinite(x) for x in vector):
        raise ValueError("vector must contain finite numbers")
    length = math.sqrt(sum(x * x for x in vector))
    if not length or not math.isfinite(length):
        raise ValueError("vector must be nonzero and finite")
    return [x / length for x in vector]


def features(source):
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z_0-9]*", source.lower())
    result = Counter(tokens)
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                result["call:" + ast.unparse(node.func).lower()] += 2
            elif isinstance(node, (ast.For, ast.If, ast.Return, ast.ClassDef)):
                result["ast:" + type(node).__name__.lower()] += 1
    except SyntaxError:
        pass  # Notebook magics: lexical fallback, never execute code.
    return result


def embed(source):
    vector = [0.0] * ENCODER["dimensions"]
    for token, count in features(source).items():
        h = hashlib.blake2b(token.encode(), digest_size=8).digest()
        slot = int.from_bytes(h[:4], "little") % len(vector)
        vector[slot] += (1 if h[4] & 1 else -1) * (1 + math.log(count))
    return normalize(vector, len(vector))


def extract(path, manifest):
    raw = path.read_text(encoding="utf-8-sig")
    if path.suffix == ".ipynb":
        nb = json.loads(raw)
        cells = [(i, "".join(c.get("source", [])))
                 for i, c in enumerate(nb["cells"]) if c.get("cell_type") == "code"]
    elif path.suffix == ".py":
        cells = [(0, raw)]
    else:
        raise ValueError("index supports explicit .py and .ipynb files only")
    modules = []
    for cell, source in cells:
        if not re.search(r"[a-zA-Z_]", source):
            continue
        parts = []
        try:
            tree = ast.parse(source)
            lines = source.splitlines(keepends=True)
            occupied = set()
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                    parts.append((node.name, start, "".join(lines[start-1:node.end_lineno])))
                    occupied.update(range(start-1, node.end_lineno))
            rest = "".join(line if i not in occupied else "\n"
                           for i, line in enumerate(lines))
            if re.search(r"[a-zA-Z_]", rest):
                parts.append(("cell", 1, rest))
        except SyntaxError:
            parts = [("cell", 1, source)]
        for name, line, body in parts:
            sha = hashlib.sha256(body.encode()).hexdigest()
            try:
                tree = ast.parse(body)
                imports = sorted({ast.unparse(n) for n in ast.walk(tree)
                                  if isinstance(n, (ast.Import, ast.ImportFrom))})
                calls = sorted({ast.unparse(n.func) for n in ast.walk(tree)
                                if isinstance(n, ast.Call)})
                parse_status = "ast"
            except SyntaxError:
                imports, calls, parse_status = [], [], "lexical_fallback"
            # Preserve externally supplied claims as metadata; never infer scores.
            meta = {k: manifest.get(k, "unknown") for k in
                    ("source_url", "source_version", "family_id", "weight_ids",
                     "data_ids", "license")}
            modules.append({"module_id": f"{path.name}:cell{cell}:{name}:{line}:{sha[:12]}",
                            "module_sha256": sha, "file_sha256": digest(path),
                            "source_file": path.name, "cell": cell, "line": line,
                            "name": name, "imports": imports, "calls": calls,
                            "parse_status": parse_status, "provenance": meta,
                            "vector": embed(body)})
    return modules


def validate_encoder(encoder):
    required = ("name", "revision", "pooling", "dimensions")
    if not isinstance(encoder, dict) or any(k not in encoder for k in required):
        raise ValueError("encoder must record name, revision, pooling, dimensions")
    d = encoder["dimensions"]
    if isinstance(d, bool) or not isinstance(d, int) or d <= 0:
        raise ValueError("encoder dimensions must be positive")
    if any(not isinstance(encoder[k], str) or not encoder[k]
           for k in required[:-1]):
        raise ValueError("encoder provenance must be nonempty strings")


def index(args):
    manifest = read(args.manifest) if args.manifest else {}
    modules = []
    for filename in args.files:
        path = Path(filename)
        modules.extend(extract(path, manifest.get(path.name, manifest.get("default", {}))))
    if not modules:
        raise ValueError("no indexable modules")
    ids = [m["module_id"] for m in modules]
    if len(set(ids)) != len(ids):
        raise ValueError("module IDs collide: use distinct source filenames")
    encoder = ENCODER
    if args.embeddings:
        external = read(args.embeddings)
        encoder = external["encoder"]
        validate_encoder(encoder)
        for m in modules:
            sha = m["module_sha256"]
            if sha not in external["vectors"]:
                raise ValueError("external embedding missing module " + sha)
            m["vector"] = normalize(external["vectors"][sha], encoder["dimensions"])
    emit({"tool_version": VERSION, "kind": "code_retrieval", "encoder": encoder,
          "modules": modules, "warnings": [
              "Similarity is retrieval evidence, not measured competition improvement.",
              "Shared weights/assets require ancestry review; code hashes alone are insufficient."
          ]}, args.out)


def search(args):
    data = read(args.index)
    if data.get("kind") != "code_retrieval":
        raise ValueError("expected a code retrieval index")
    validate_encoder(data["encoder"])
    if args.query_vector:
        query = read(args.query_vector)
        if query["encoder"] != data["encoder"]:
            raise ValueError("query and index encoder provenance mismatch")
        vector = normalize(query["vector"], data["encoder"]["dimensions"])
    else:
        if data["encoder"] != ENCODER:
            raise ValueError("external index requires --query-vector")
        vector = embed(args.query)
    hits = []
    for module in data["modules"]:
        v = normalize(module["vector"], len(vector))
        hits.append({"module_id": module["module_id"],
                     "similarity": sum(x*y for x, y in zip(vector, v)),
                     "provenance": module["provenance"],
                     "calls": module["calls"]})
    hits.sort(key=lambda h: (-h["similarity"], h["module_id"]))
    emit({"kind": "retrieval_only", "matches": hits[:args.top]}, args.out)


def rr(rank):
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 0:
        raise ValueError("rank must be integer >= 0 (0 means no hit)")
    return 1 / rank if 1 <= rank <= 25 else 0.0


def validate_rows(data, baseline=False):
    if data.get("schema_version") != 1 or data.get("metric_id") != "mrr@25":
        raise ValueError("unsupported schema/metric")
    for key in ("cohort_id", "baseline_id"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValueError("missing identity: " + key)
    if not isinstance(data.get("rows"), list) or not data["rows"]:
        raise ValueError("rows must be nonempty")
    result = {}
    for row in data["rows"]:
        qid = row.get("query_id")
        if not isinstance(qid, str) or not qid or qid in result:
            raise ValueError("invalid or duplicate query_id")
        rr(row["rank"])
        if baseline:
            for key in ("group", "block_id"):
                if not isinstance(row.get(key), str) or not row[key]:
                    raise ValueError("baseline rows need group and independent block_id")
        result[qid] = row
    return result


def profile_value(data):
    rows = validate_rows(data, baseline=True)
    groups = defaultdict(list)
    for row in rows.values():
        groups[row["group"]].append(1 - rr(row["rank"]))
    total_loss = sum(sum(v) for v in groups.values())
    axes = sorted(groups)
    info = {g: {"n": len(groups[g]), "population_weight": len(groups[g])/len(rows),
                "mean_loss": sum(groups[g])/len(groups[g]),
                "loss_share": sum(groups[g])/total_loss if total_loss else 0.0}
            for g in axes}
    return {"kind": "error_demand", "axes": axes, "groups": info,
            "n": len(rows), "baseline_mrr": 1-total_loss/len(rows),
            "loss_vector": [info[g]["loss_share"] for g in axes],
            "population_vector": [info[g]["population_weight"] for g in axes]}


def interval(pairs, samples, seed):
    blocks = defaultdict(list)
    for block, value in pairs:
        blocks[block].append(value)
    units = list(blocks.values())
    if len(units) < 2:
        return {"low": None, "high": None, "blocks": len(units),
                "warning": "too few independent blocks"}
    rng = random.Random(seed)
    estimates = []
    for _ in range(samples):
        selected = [units[rng.randrange(len(units))] for _ in units]
        estimates.append(sum(sum(x) for x in selected)/sum(len(x) for x in selected))
    estimates.sort()
    low = estimates[int((samples-1)*0.025)]
    high = estimates[int((samples-1)*0.975)]
    warning = "few blocks; interval is exploratory" if len(units) < 20 else None
    if low == high:
        warning = "degenerate bootstrap interval; do not infer certainty"
    return {"low": low, "high": high, "blocks": len(units), "warning": warning}


def compare_value(base, variant, samples=1000, seed=2026, penalty=0.0):
    before = validate_rows(base, baseline=True)
    after = validate_rows(variant)
    for key in ("cohort_id", "baseline_id", "metric_id", "schema_version"):
        if base[key] != variant[key]:
            raise ValueError("incomparable identity: " + key)
    if before.keys() != after.keys():
        raise ValueError("query sets differ; no silent intersection")
    if variant.get("mode") not in ("standalone", "fused"):
        raise ValueError("mode must be standalone or fused")
    for key in ("component_id", "family_id"):
        if not isinstance(variant.get(key), str) or not variant[key]:
            raise ValueError("missing component provenance: " + key)
    if samples < 100 or not math.isfinite(penalty) or penalty < 0:
        raise ValueError("bootstrap >=100, cost penalty finite >=0 required")
    demand = profile_value(base)
    differences, grouped = [], defaultdict(list)
    rescue = harm = 0
    for qid, row in before.items():
        a, b = rr(row["rank"]), rr(after[qid]["rank"])
        item = (row["block_id"], b-a)
        differences.append(item)
        grouped[row["group"]].append(item)
        rescue += int(b == 1 and a != 1)
        harm += int(a == 1 and b != 1)
    groups = {g: {"n": len(values), "delta_mrr": sum(v for _, v in values)/len(values),
                  "ci95": interval(values, samples, seed)}
              for g, values in sorted(grouped.items())}
    capability = [groups[g]["delta_mrr"] for g in demand["axes"]]
    delta = sum(v for _, v in differences)/len(differences)
    ci = interval(differences, samples, seed)
    loss = demand["loss_vector"]
    denom = math.sqrt(sum(v*v for v in loss)*sum(v*v for v in capability))
    direction = sum(a*b for a, b in zip(loss, capability))/denom if denom else None
    priority = ci["low"]-penalty if ci["low"] is not None else None
    return {"tool_version": VERSION, "kind": "measured_capability",
            "cohort_id": base["cohort_id"], "baseline_id": base["baseline_id"],
            "metric_id": base["metric_id"], "component_id": variant["component_id"],
            "family_id": variant["family_id"], "mode": variant["mode"],
            "n": len(before), "axes": demand["axes"], "capability_vector": capability,
            "demand": demand, "groups": groups,
            "baseline_mrr": demand["baseline_mrr"],
            "variant_mrr": demand["baseline_mrr"]+delta, "delta_mrr": delta,
            "ci95": ci, "top1_rescue": rescue, "top1_harm": harm,
            "mean_mrr_gain": sum(max(v,0) for _,v in differences)/len(before),
            "mean_mrr_loss": sum(max(-v,0) for _,v in differences)/len(before),
            "demand_direction_cosine": direction,
            "cost_penalty_mrr": penalty, "conservative_experiment_priority": priority,
            "decision": "test_fusion" if priority is not None and priority > 0
                        else "investigate_or_defer",
            "warnings": ["Not automatic adoption or Kaggle submission authorization.",
                         "Standalone gains do not establish fusion gains.",
                         "Group labels are offline analysis, not inference routing.",
                         "Final ranks alone do not measure full candidate recall."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("index")
    p.add_argument("files", nargs="+")
    p.add_argument("--manifest")
    p.add_argument("--embeddings")
    p.add_argument("--out")
    p = sub.add_parser("search")
    p.add_argument("--index", required=True)
    query = p.add_mutually_exclusive_group(required=True)
    query.add_argument("--query")
    query.add_argument("--query-vector")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--out")
    p = sub.add_parser("profile")
    p.add_argument("--baseline", required=True)
    p.add_argument("--out")
    p = sub.add_parser("compare")
    p.add_argument("--baseline", required=True)
    p.add_argument("--variant", required=True)
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--cost-penalty", type=float, default=0.0)
    p.add_argument("--out")
    args = parser.parse_args()
    try:
        if args.command == "index":
            index(args)
        elif args.command == "search":
            if args.top < 1:
                raise ValueError("top must be positive")
            search(args)
        elif args.command == "profile":
            value = profile_value(read(args.baseline))
            value["input_sha256"] = digest(args.baseline)
            emit(value, args.out)
        else:
            value = compare_value(read(args.baseline), read(args.variant),
                                  args.bootstrap, args.seed, args.cost_penalty)
            value["input_sha256"] = {"baseline": digest(args.baseline),
                                     "variant": digest(args.variant)}
            emit(value, args.out)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
