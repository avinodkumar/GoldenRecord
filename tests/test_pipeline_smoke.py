from datetime import date

from goldenrecord import pipeline, synth


def test_end_to_end_on_small_dataset(tmp_path):
    synth.generate(n_vendors=300, n_invoices=3000, seed=7, raw_dir=tmp_path / "raw", truth_dir=tmp_path / "truth")
    metrics = pipeline.run(as_of=date(2026, 9, 30), data_dir=tmp_path)

    assert metrics["active_rules"] >= 5
    assert metrics["match_precision"] >= 0.95
    assert metrics["match_recall"] >= 0.85
    assert metrics["catch_rate"] >= 0.90
    assert metrics["dq_score_after"] > metrics["dq_score_before"]
    for name in ("gold_vendor.csv", "vendor_xref.csv", "gold_spend_fact.csv", "review_queue.csv"):
        assert (tmp_path / "gold" / name).exists()


def test_steward_review_closes_the_loop(tmp_path):
    synth.generate(n_vendors=300, n_invoices=1000, seed=11, raw_dir=tmp_path / "raw", truth_dir=tmp_path / "truth")
    first = pipeline.run(as_of=date(2026, 9, 30), data_dir=tmp_path)
    pipeline.simulate_review(data_dir=tmp_path)
    second = pipeline.run(as_of=date(2026, 9, 30), data_dir=tmp_path)
    assert second["review_queue_size"] == 0
    assert second["match_recall"] >= first["match_recall"]
