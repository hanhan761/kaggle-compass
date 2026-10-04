import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

FILE = Path(__file__).parents[1] / "skills/kaggle-compass/scripts/compass.py"
spec = importlib.util.spec_from_file_location("compass", FILE)
compass = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compass)


class CompassTests(unittest.TestCase):
    def data(self):
        base = {"schema_version": 1, "metric_id": "mrr@25",
                "cohort_id": "synthetic", "baseline_id": "champion",
                "rows": [{"query_id": "a", "rank": 1, "group": "strong", "block_id": "s1"},
                         {"query_id": "b", "rank": 0, "group": "missing", "block_id": "s2"}]}
        variant = {"schema_version": 1, "metric_id": "mrr@25",
                   "cohort_id": "synthetic", "baseline_id": "champion",
                   "component_id": "trial", "family_id": "independent",
                   "mode": "fused", "rows": [{"query_id": "a", "rank": 2},
                                            {"query_id": "b", "rank": 10}]}
        return base, variant

    def test_rescue_does_not_hide_larger_harm(self):
        b, v = self.data()
        r = compass.compare_value(b, v, samples=300)
        self.assertAlmostEqual(r["delta_mrr"], -0.2)
        self.assertEqual(r["top1_harm"], 1)
        self.assertEqual(r["decision"], "investigate_or_defer")
        self.assertAlmostEqual(sum(w*c for w,c in zip(
            r["demand"]["population_vector"], r["capability_vector"])), r["delta_mrr"])

    def test_no_silent_query_intersection(self):
        b, v = self.data()
        v["rows"].pop()
        with self.assertRaisesRegex(ValueError, "query sets"):
            compass.compare_value(b, v)

    def test_no_incomparable_cohorts(self):
        b, v = self.data()
        v["cohort_id"] = "confirmation"
        with self.assertRaisesRegex(ValueError, "identity"):
            compass.compare_value(b, v)

    def test_duplicate_and_invalid_rank_rejected(self):
        b, v = self.data()
        v["rows"].append(copy.deepcopy(v["rows"][0]))
        with self.assertRaises(ValueError):
            compass.compare_value(b, v)
        for rank in (True, -1, 1.5, float("nan")):
            with self.assertRaises(ValueError):
                compass.rr(rank)

    def test_one_independent_block_is_not_significant(self):
        b, v = self.data()
        for row in b["rows"]:
            row["block_id"] = "one-scaffold"
        r = compass.compare_value(b, v)
        self.assertIsNone(r["ci95"]["low"])
        self.assertIsNone(r["conservative_experiment_priority"])

    def test_reproducible_block_interval(self):
        pairs = [("a", .1), ("a", -.2), ("b", .4), ("c", -.1)]
        self.assertEqual(compass.interval(pairs, 500, 7), compass.interval(pairs, 500, 7))

    def test_notebook_outputs_excluded_and_magic_never_executed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"trial.ipynb"
            p.write_text(json.dumps({"cells":[
                {"cell_type":"code", "source":["%time x\n", "model.predict(x)\n"],
                 "outputs":[{"text":"SECRET_OUTPUT"}]},
                {"cell_type":"code", "source":["def rerank(x):\n", "    return sorted(x)\n"]}]}))
            result = compass.extract(p, {})
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["parse_status"], "lexical_fallback")
            self.assertNotIn("SECRET_OUTPUT", json.dumps(result))

    def test_hash_embedding_distinguishes_modules(self):
        sim = lambda a,b: sum(x*y for x,y in zip(compass.embed(a),compass.embed(b)))
        self.assertGreater(sim("cosine spectrum similarity", "cosine spectrum similarity"),
                           sim("cosine spectrum similarity", "smiles beam decode"))
        with self.assertRaises(ValueError):
            compass.normalize([0, 0], 2)
        with self.assertRaises(ValueError):
            compass.normalize([float("nan")], 1)

    def test_rank_cutoff_and_external_encoder_contract(self):
        self.assertEqual(compass.rr(26), 0)
        self.assertEqual(compass.rr(25), 0.04)
        with self.assertRaises(ValueError):
            compass.validate_encoder({"name":"model", "dimensions":3})


if __name__ == "__main__":
    unittest.main()
