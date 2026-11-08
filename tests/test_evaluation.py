import math
import unittest

from ai_engine.evaluation import evaluate_binary_forecasts


class BinaryForecastEvaluationTests(unittest.TestCase):
    def test_perfect_forecasts_have_zero_brier_and_log_loss(self):
        rows = [
            {"estimated_probability_exploratory": 1, "outcome": 1, "outcome_verified": True},
            {"estimated_probability_exploratory": 0, "outcome": 0, "outcome_verified": True},
        ]
        result = evaluate_binary_forecasts(rows, minimum_sample=2)
        self.assertEqual(result["sample_size"], 2)
        self.assertEqual(result["brier_score"], 0)
        self.assertEqual(result["log_loss"], 0)
        self.assertTrue(result["minimum_sample_reached"])

    def test_unverified_and_invalid_rows_are_excluded(self):
        rows = [
            {"estimated_probability_exploratory": 0.8, "outcome": 1, "outcome_verified": True},
            {"estimated_probability_exploratory": 0.2, "outcome": 0, "outcome_verified": False},
            {"estimated_probability_exploratory": "bad", "outcome": 1, "outcome_verified": True},
            {"estimated_probability_exploratory": math.inf, "outcome": 1, "outcome_verified": True},
            {"estimated_probability_exploratory": 0.4, "outcome": "unknown", "outcome_verified": True},
        ]
        result = evaluate_binary_forecasts(rows)
        self.assertEqual(result["sample_size"], 1)
        self.assertEqual(result["excluded"], 4)
        self.assertFalse(result["minimum_sample_reached"])

    def test_reliability_bins_include_probability_one(self):
        rows = [
            {"estimated_probability_exploratory": 0.05, "outcome": 0, "outcome_verified": True},
            {"estimated_probability_exploratory": 1.0, "outcome": 1, "outcome_verified": True},
        ]
        result = evaluate_binary_forecasts(rows, bins=10)
        self.assertEqual(len(result["reliability"]), 2)
        self.assertEqual(result["reliability"][-1]["upper_bound"], 1.0)

    def test_canonical_probability_field_is_supported(self):
        rows = [
            {"probability": 0.8, "outcome": 1, "outcome_verified": True},
            {"probability": 0.2, "outcome": 0, "outcome_verified": True},
        ]
        result = evaluate_binary_forecasts(rows, minimum_sample=2)
        self.assertEqual(result["sample_size"], 2)
        self.assertEqual(result["brier_score"], 0.04)

    def test_empty_data_returns_null_metrics(self):
        result = evaluate_binary_forecasts([{"outcome": 1, "outcome_verified": False}])
        self.assertEqual(result["sample_size"], 0)
        self.assertIsNone(result["brier_score"])
        self.assertEqual(result["reliability"], [])


    def test_observed_rate_includes_wilson_95_percent_interval(self):
        rows = [
            {"probability": 0.7, "outcome": 1, "outcome_verified": True},
            {"probability": 0.4, "outcome": 0, "outcome_verified": True},
            {"probability": 0.6, "outcome": 1, "outcome_verified": True},
            {"probability": 0.3, "outcome": 0, "outcome_verified": True},
        ]
        result = evaluate_binary_forecasts(rows, minimum_sample=4)
        lower, upper = result["observed_rate_ci_95"]
        self.assertAlmostEqual(result["observed_rate"], 0.5)
        self.assertLess(lower, result["observed_rate"])
        self.assertGreater(upper, result["observed_rate"])
        self.assertGreaterEqual(lower, 0)
        self.assertLessEqual(upper, 1)

    def test_empty_data_has_no_confidence_interval(self):
        result = evaluate_binary_forecasts([])
        self.assertIsNone(result["observed_rate_ci_95"])

    def test_invalid_configuration_raises(self):
        with self.assertRaises(ValueError):
            evaluate_binary_forecasts([], bins=0)
        with self.assertRaises(ValueError):
            evaluate_binary_forecasts([], minimum_sample=0)


    def test_grouped_evaluation_separates_markets_and_ignores_unverified(self):
        from ai_engine.evaluation import evaluate_forecasts_by_group

        rows = [
            {"market": "Corners", "estimated_probability_exploratory": 0.8, "outcome": 1, "outcome_verified": True},
            {"market": "Corners", "estimated_probability_exploratory": 0.3, "outcome": 0, "outcome_verified": True},
            {"market": "Goals", "estimated_probability_exploratory": 0.7, "outcome": 1, "outcome_verified": True},
            {"market": "Goals", "estimated_probability_exploratory": 0.6, "outcome": 1, "outcome_verified": False},
            {"market": "", "estimated_probability_exploratory": 0.5, "outcome": 1, "outcome_verified": True},
        ]
        result = evaluate_forecasts_by_group(rows, group_key="market", minimum_sample=2)
        self.assertEqual([item["group"] for item in result], ["Corners", "Goals"])
        self.assertEqual(result[0]["sample_size"], 2)
        self.assertEqual(result[1]["sample_size"], 1)
        self.assertFalse(result[1]["minimum_sample_reached"])

    def test_grouped_evaluation_rejects_empty_group_key(self):
        from ai_engine.evaluation import evaluate_forecasts_by_group

        with self.assertRaises(ValueError):
            evaluate_forecasts_by_group([], group_key=" ")


    def test_chronological_holdout_keeps_fixture_snapshots_together(self):
        from ai_engine.evaluation import evaluate_chronological_holdout
        rows = []
        for index in range(10):
            for snapshot in range(2):
                rows.append({
                    "fixture_id": f"fx-{index}",
                    "recorded_at": f"2026-01-{index + 1:02d}T12:0{snapshot}:00Z",
                    "estimated_probability_exploratory": 0.8,
                    "outcome": 1,
                    "outcome_verified": True,
                })
        result = evaluate_chronological_holdout(rows, minimum_train_fixtures=5, minimum_test_fixtures=2)
        self.assertTrue(result["available"])
        self.assertEqual(result["train_fixture_count"], 8)
        self.assertEqual(result["test_fixture_count"], 2)
        self.assertEqual(result["train_row_count"], 16)
        self.assertEqual(result["test_row_count"], 4)
        self.assertEqual(result["test_metrics"]["sample_size"], 2)
        self.assertEqual(result["test_metrics"]["raw_verified_sample_size"], 4)
        self.assertEqual(result["test_metrics"]["deduplicated_snapshots"], 2)
        self.assertLess(result["train_last_timestamp"], result["test_first_timestamp"])

    def test_chronological_holdout_breakdowns_use_only_test_fixtures(self):
        from ai_engine.evaluation import evaluate_chronological_holdout
        rows = []
        for index in range(10):
            rows.append({
                "fixture_id": f"fx-{index}",
                "recorded_at": f"2026-02-{index + 1:02d}T12:00:00+00:00",
                "market": "Corners" if index < 8 else "Goals",
                "league": "League A" if index < 8 else "League B",
                "estimated_probability_exploratory": 0.8,
                "outcome": 1,
                "outcome_verified": True,
            })
        result = evaluate_chronological_holdout(
            rows, minimum_train_fixtures=5, minimum_test_fixtures=2
        )
        self.assertEqual(result["test_fixture_count"], 2)
        self.assertEqual(result["test_metrics_by_market"][0]["group"], "Goals")
        self.assertEqual(result["test_metrics_by_market"][0]["sample_size"], 2)
        self.assertEqual(result["test_metrics_by_league"][0]["group"], "League B")
        self.assertEqual(result["test_metrics_by_league"][0]["sample_size"], 2)

    def test_chronological_holdout_excludes_bad_temporal_rows(self):
        from ai_engine.evaluation import evaluate_chronological_holdout
        rows = [
            {"fixture_id": "a", "recorded_at": "2026-01-01T00:00:00"},
            {"fixture_id": "b", "recorded_at": "bad-date"},
            {"fixture_id": "", "recorded_at": "2026-01-03T00:00:00Z"},
        ]
        result = evaluate_chronological_holdout(rows, minimum_train_fixtures=1, minimum_test_fixtures=1)
        self.assertEqual(result["excluded_temporal_rows"], 3)
        self.assertFalse(result["available"])

    def test_chronological_holdout_validates_configuration(self):
        from ai_engine.evaluation import evaluate_chronological_holdout
        with self.assertRaises(ValueError):
            evaluate_chronological_holdout([], train_fraction=1.0)
        with self.assertRaises(ValueError):
            evaluate_chronological_holdout([], minimum_test_fixtures=0)
    def test_market_line_evaluation_keeps_lines_and_models_separate(self):
        from ai_engine.evaluation import evaluate_forecasts_by_market_line
        rows = [
            {"market": "total_goals", "selection": "over", "line": "2.5",
             "phase": "pre_match", "model_id": "goal", "model_version": "0.1",
             "probability": 0.8, "outcome": 1, "outcome_verified": True},
            {"market": "total_goals", "selection": "over", "line": "3.5",
             "phase": "pre_match", "model_id": "goal", "model_version": "0.1",
             "probability": 0.4, "outcome": 0, "outcome_verified": True},
            {"market": "total_goals", "selection": "over", "line": "2.5",
             "phase": "pre_match", "model_id": "goal", "model_version": "0.2",
             "probability": 0.7, "outcome": 1, "outcome_verified": True},
            {"market": "total_goals", "selection": "over", "line": "",
             "probability": 0.9, "outcome": 1, "outcome_verified": True},
        ]
        result = evaluate_forecasts_by_market_line(rows, minimum_sample=1)
        self.assertEqual(len(result), 3)
        self.assertEqual({(r["line"], r["model_version"]) for r in result},
                         {("2.5", "0.1"), ("3.5", "0.1"), ("2.5", "0.2")})
        self.assertTrue(all(r["sample_size"] == 1 for r in result))

    def test_chronological_holdout_adds_market_line_breakdown_from_test_only(self):
        from ai_engine.evaluation import evaluate_chronological_holdout
        rows = []
        for index in range(10):
            rows.append({
                "fixture_id": f"line-fx-{index}",
                "recorded_at": f"2026-03-{index + 1:02d}T12:00:00Z",
                "market": "total_goals", "selection": "over",
                "line": "2.5" if index < 8 else "3.5",
                "phase": "pre_match", "model_id": "goal", "model_version": "0.1",
                "probability": 0.8, "outcome": 1, "outcome_verified": True,
            })
        result = evaluate_chronological_holdout(
            rows, minimum_train_fixtures=5, minimum_test_fixtures=2
        )
        breakdown = result["test_metrics_by_market_line"]
        self.assertEqual(len(breakdown), 1)
        self.assertEqual(breakdown[0]["line"], "3.5")
        self.assertEqual(breakdown[0]["sample_size"], 2)


    def test_market_breakdown_uses_canonical_type_not_selection_label(self):
        from ai_engine.evaluation import evaluate_forecasts_by_market
        rows = [
            {"market": "Empate final", "market_type": "draw", "probability": 0.7,
             "outcome": 1, "outcome_verified": True},
            {"market": "Gana local", "market_type": "goals", "probability": 0.6,
             "outcome": 1, "outcome_verified": True},
            {"market": "Más de 2.5 goles", "market_type": "goals", "probability": 0.8,
             "outcome": 1, "outcome_verified": True},
            {"market": "Ambos equipos marcan: Sí", "market_type": "btts", "probability": 0.5,
             "outcome": 0, "outcome_verified": True},
        ]
        result = evaluate_forecasts_by_market(rows, minimum_sample=1)
        self.assertEqual([item["group"] for item in result], ["btts", "draw", "goals"])
        goals = next(item for item in result if item["group"] == "goals")
        self.assertEqual(goals["sample_size"], 2)

    def test_market_breakdown_keeps_legacy_fallback(self):
        from ai_engine.evaluation import evaluate_forecasts_by_market
        rows = [
            {"market": "Corners", "probability": 0.8, "outcome": 1, "outcome_verified": True},
            {"market": "Corners", "probability": 0.3, "outcome": 0, "outcome_verified": True},
        ]
        result = evaluate_forecasts_by_market(rows, minimum_sample=2)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["group"], "Corners")
        self.assertEqual(result[0]["sample_size"], 2)

    def test_market_line_breakdown_prefers_canonical_type(self):
        from ai_engine.evaluation import evaluate_forecasts_by_market_line
        rows = [
            {"market": "Más de 2.5 goles", "market_type": "goals", "selection": "over",
             "line": "2.5", "probability": 0.8, "outcome": 1, "outcome_verified": True},
            {"market": "Menos de 2.5 goles", "market_type": "goals", "selection": "under",
             "line": "2.5", "probability": 0.4, "outcome": 0, "outcome_verified": True},
        ]
        result = evaluate_forecasts_by_market_line(rows, minimum_sample=1)
        self.assertEqual({item["market"] for item in result}, {"goals"})
        self.assertEqual({item["selection"] for item in result}, {"over", "under"})

    def test_market_line_breakdown_never_pools_different_event_definitions(self):
        from ai_engine.evaluation import evaluate_forecasts_by_market_line

        base = {
            "market_type": "corners", "selection": "over", "line": "8.5",
            "phase": "live", "model_id": "corners-model", "model_version": "1.0",
            "probability": 0.7, "outcome": 1, "outcome_verified": True,
        }
        variations = [
            {"market_type": "goals"},
            {"selection": "under"},
            {"line": "9.5"},
            {"phase": "pre_match"},
            {"model_id": "other-model"},
            {"model_version": "2.0"},
        ]
        rows = [dict(base)]
        for change in variations:
            row = dict(base)
            row.update(change)
            rows.append(row)

        result = evaluate_forecasts_by_market_line(rows, minimum_sample=1)

        self.assertEqual(len(result), 1 + len(variations))
        self.assertTrue(all(item["sample_size"] == 1 for item in result))
        keys = {
            (item["market"], item["selection"], item["line"], item["phase"],
             item["model_id"], item["model_version"])
            for item in result
        }
        self.assertEqual(len(keys), 1 + len(variations))


    def test_model_versions_require_same_verified_fixtures_for_comparison(self):
        from ai_engine.evaluation import evaluate_model_version_comparability

        rows = []
        for fixture in ("fx-1", "fx-2", "fx-3"):
            for version in ("1.0", "2.0"):
                rows.append({
                    "fixture_id": fixture, "market_type": "corners",
                    "selection": "over", "line": "8.5", "phase": "live",
                    "model_id": "corner-model", "model_version": version,
                    "outcome_verified": True,
                })
        rows.extend([
            {"fixture_id": "fx-4", "market_type": "corners", "selection": "over",
             "line": "8.5", "phase": "live", "model_id": "corner-model",
             "model_version": "1.0", "outcome_verified": True},
            {"fixture_id": "fx-5", "market_type": "corners", "selection": "over",
             "line": "8.5", "phase": "live", "model_id": "corner-model",
             "model_version": "2.0", "outcome_verified": True},
            {"fixture_id": "fx-1", "market_type": "goals", "selection": "over",
             "line": "2.5", "phase": "live", "model_id": "corner-model",
             "model_version": "3.0", "outcome_verified": True},
            {"fixture_id": "fx-1", "market_type": "corners", "selection": "under",
             "line": "8.5", "phase": "live", "model_id": "corner-model",
             "model_version": "3.0", "outcome_verified": True},
            {"fixture_id": "fx-1", "market_type": "corners", "selection": "over",
             "line": "8.5", "phase": "live", "model_id": "corner-model",
             "model_version": "3.0", "outcome_verified": False},
        ])

        result = evaluate_model_version_comparability(rows, minimum_common_fixtures=3)

        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]["version_a"], result[0]["version_b"]), ("1.0", "2.0"))
        self.assertEqual(result[0]["common_fixture_count"], 3)
        self.assertTrue(result[0]["comparable_cohort"])

    def test_model_version_comparison_is_blocked_below_common_fixture_minimum(self):
        from ai_engine.evaluation import evaluate_model_version_comparability

        rows = []
        for fixture in ("fx-1", "fx-2"):
            for version in ("1.0", "2.0"):
                rows.append({
                    "fixture_id": fixture, "market_type": "goals",
                    "selection": "over", "line": "2.5", "phase": "pre_match",
                    "model_id": "goals-model", "model_version": version,
                    "outcome_verified": True,
                })

        result = evaluate_model_version_comparability(rows, minimum_common_fixtures=3)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["common_fixture_count"], 2)
        self.assertFalse(result[0]["comparable_cohort"])
        self.assertIn("No comparable", result[0]["status"])

    def test_model_version_comparability_validates_minimum(self):
        from ai_engine.evaluation import evaluate_model_version_comparability
        with self.assertRaises(ValueError):
            evaluate_model_version_comparability([], minimum_common_fixtures=0)


    def test_model_versions_report_paired_losses_on_exact_common_fixtures(self):
        from ai_engine.evaluation import evaluate_model_version_comparability

        rows = []
        outcomes = [1, 0, 1]
        for index, outcome in enumerate(outcomes):
            common = {
                "fixture_id": f"fx-{index}", "market_type": "corners",
                "selection": "over", "line": "8.5", "phase": "live",
                "model_id": "corner-model", "outcome": outcome,
                "outcome_verified": True,
            }
            rows.append({**common, "model_version": "1.0", "probability": 0.5})
            rows.append({**common, "model_version": "2.0", "probability": 0.9 if outcome else 0.1})
        result = evaluate_model_version_comparability(
            rows, probability_key="probability", minimum_common_fixtures=3
        )
        self.assertEqual(len(result), 1)
        comparison = result[0]
        self.assertEqual(comparison["common_fixture_count"], 3)
        self.assertAlmostEqual(comparison["brier_a"], 0.25)
        self.assertAlmostEqual(comparison["brier_b"], 0.01)
        self.assertLess(comparison["brier_delta_b_minus_a"], 0)
        self.assertLess(comparison["log_loss_delta_b_minus_a"], 0)

    def test_model_version_paired_metrics_exclude_mismatched_outcomes_and_invalid_probabilities(self):
        from ai_engine.evaluation import evaluate_model_version_comparability

        rows = []
        for version, outcome, probability in (
            ("1.0", 1, 0.8), ("2.0", 0, 0.2),
            ("1.0", 1, 1.2), ("2.0", 1, 0.7),
        ):
            rows.append({
                "fixture_id": "same", "market_type": "goals", "selection": "over",
                "line": "2.5", "phase": "pre_match", "model_id": "goals",
                "model_version": version, "outcome": outcome,
                "outcome_verified": True, "probability": probability,
            })
        result = evaluate_model_version_comparability(
            rows, probability_key="probability", minimum_common_fixtures=1
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["common_fixture_count"], 1)
        self.assertEqual(result[0]["matching_outcome_fixture_count"], 1)
        self.assertEqual(result[0]["paired_metric_fixture_count"], 0)
        self.assertFalse(result[0]["paired_metrics_available"])
        self.assertIsNone(result[0]["brier_delta_b_minus_a"])



    def test_model_version_pairing_uses_latest_snapshot_per_fixture(self):
        from ai_engine.evaluation import evaluate_model_version_comparability

        common = {
            "fixture_id": "fx-1", "market_type": "corners", "selection": "over",
            "line": "8.5", "phase": "live", "model_id": "corners",
            "outcome": 1, "outcome_verified": True,
        }
        rows = [
            {**common, "model_version": "1.0", "probability": 0.2,
             "recorded_at": "2026-11-01T10:00:00+00:00"},
            {**common, "model_version": "1.0", "probability": 0.8,
             "recorded_at": "2026-11-01T10:05:00+00:00"},
            {**common, "model_version": "2.0", "probability": 0.7,
             "recorded_at": "2026-11-01T10:04:00+00:00"},
        ]
        result = evaluate_model_version_comparability(
            rows, probability_key="probability", minimum_common_fixtures=1
        )
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["brier_a"], 0.04)
        self.assertAlmostEqual(result[0]["brier_b"], 0.09)


    def test_model_version_latest_snapshot_normalizes_timezone_offsets_and_input_order(self):
        from ai_engine.evaluation import evaluate_model_version_comparability

        common = {
            "fixture_id": "fx-offset", "market_type": "goals", "selection": "over",
            "line": "2.5", "phase": "live", "model_id": "goals",
            "outcome": 1, "outcome_verified": True,
        }
        rows = [
            # 15:00 UTC is later than 14:30 UTC, despite its earlier local clock.
            {**common, "model_version": "1.0", "probability": 0.1,
             "recorded_at": "2026-11-01T09:30:00-05:00"},
            {**common, "model_version": "1.0", "probability": 0.8,
             "recorded_at": "2026-11-01T14:30:00Z"},
            {**common, "model_version": "2.0", "probability": 0.7,
             "recorded_at": "2026-11-01T15:00:00+00:00"},
        ]
        result = evaluate_model_version_comparability(
            rows, probability_key="probability", minimum_common_fixtures=1
        )
        self.assertAlmostEqual(result[0]["brier_a"], 0.04)
        self.assertAlmostEqual(result[0]["brier_b"], 0.09)

        shuffled = [rows[1], rows[0], rows[2]]
        shuffled_result = evaluate_model_version_comparability(
            shuffled, probability_key="probability", minimum_common_fixtures=1
        )
        self.assertAlmostEqual(shuffled_result[0]["brier_a"], 0.04)

    def test_model_version_timestamp_fallback_uses_first_parseable_timezone_field(self):
        from ai_engine.evaluation import evaluate_model_version_comparability

        common = {
            "fixture_id": "fx-fallback", "market_type": "goals", "selection": "over",
            "line": "2.5", "phase": "live", "model_id": "goals",
            "outcome": 1, "outcome_verified": True,
        }
        rows = [
            {**common, "model_version": "1.0", "probability": 0.2,
             "recorded_at": "invalid", "created_at": "2026-11-01T10:00:00Z"},
            {**common, "model_version": "1.0", "probability": 0.8,
             "recorded_at": "2026-11-01T10:05:00Z"},
            {**common, "model_version": "2.0", "probability": 0.7,
             "recorded_at": "2026-11-01T10:04:00Z"},
        ]
        result = evaluate_model_version_comparability(
            rows, probability_key="probability", minimum_common_fixtures=1
        )
        self.assertAlmostEqual(result[0]["brier_a"], 0.04)

    def test_model_version_overlap_does_not_count_unknown_or_disagreeing_outcomes_as_scoring_data(self):
        from ai_engine.evaluation import evaluate_model_version_comparability

        rows = []
        cases = [
            ("unknown", None, None),
            ("disagree", 1, 0),
            ("valid", 1, 1),
        ]
        for fixture, outcome_a, outcome_b in cases:
            for version, outcome, probability in (
                ("1.0", outcome_a, 0.8), ("2.0", outcome_b, 0.7)
            ):
                rows.append({
                    "fixture_id": fixture, "market_type": "goals",
                    "selection": "over", "line": "2.5", "phase": "live",
                    "model_id": "goals", "model_version": version,
                    "outcome": outcome, "outcome_verified": True,
                    "probability": probability,
                })

        result = evaluate_model_version_comparability(
            rows, probability_key="probability", minimum_common_fixtures=2
        )
        comparison = result[0]
        self.assertEqual(comparison["common_fixture_count"], 3)
        self.assertEqual(comparison["matching_outcome_fixture_count"], 1)
        self.assertEqual(comparison["paired_metric_fixture_count"], 1)
        self.assertFalse(comparison["paired_metrics_available"])
        self.assertIsNone(comparison["brier_a"])

    def test_model_version_overlap_can_be_reported_without_valid_paired_probabilities(self):
        from ai_engine.evaluation import evaluate_model_version_comparability

        rows = []
        for version in ("1.0", "2.0"):
            rows.append({
                "fixture_id": "fx-1", "market_type": "goals", "selection": "over",
                "line": "2.5", "phase": "pre_match", "model_id": "goals",
                "model_version": version, "outcome": 1, "outcome_verified": True,
                "probability": "not-a-number",
            })
        result = evaluate_model_version_comparability(
            rows, probability_key="probability", minimum_common_fixtures=1
        )
        self.assertEqual(result[0]["common_fixture_count"], 1)
        self.assertTrue(result[0]["comparable_cohort"])
        self.assertIsNone(result[0]["brier_a"])
        self.assertIsNone(result[0]["log_loss_a"])


if __name__ == "__main__":
    unittest.main()


class ModelReadinessTests(unittest.TestCase):
    def test_model_requires_sample_calibration_and_complete_identity(self):
        from ai_engine.evaluation import assess_model_readiness

        result = assess_model_readiness(
            {"sample_size": 29, "calibration_gap": 0.12},
            model_id="",
            model_version="unknown",
        )
        self.assertFalse(result["eligible_for_controlled_monitoring"])
        self.assertEqual(result["status"], "No habilitado")
        self.assertEqual(len(result["reasons"]), 4)

    def test_model_passes_only_for_controlled_monitoring(self):
        from ai_engine.evaluation import assess_model_readiness

        result = assess_model_readiness(
            {"sample_size": 30, "calibration_gap": 0.099},
            model_id="corners_live",
            model_version="2.1",
        )
        self.assertTrue(result["eligible_for_controlled_monitoring"])
        self.assertEqual(result["status"], "Apto para seguimiento controlado")

    def test_calibration_threshold_is_exclusive(self):
        from ai_engine.evaluation import assess_model_readiness

        result = assess_model_readiness(
            {"sample_size": 50, "calibration_gap": 0.10},
            model_id="goals",
            model_version="1.0",
        )
        self.assertFalse(result["eligible_for_controlled_monitoring"])

    def test_invalid_readiness_configuration_raises(self):
        from ai_engine.evaluation import assess_model_readiness

        with self.assertRaises(ValueError):
            assess_model_readiness({}, model_id="x", model_version="1", minimum_sample=0)
        with self.assertRaises(ValueError):
            assess_model_readiness({}, model_id="x", model_version="1", maximum_calibration_gap=1.1)
