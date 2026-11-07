import unittest

from ai_engine.dataset_audit import audit_forecast_dataset


class ForecastDatasetAuditTests(unittest.TestCase):
    def row(self, **updates):
        row = {
            "recorded_at": "2026-11-01T19:00:00",
            "fixture_id": "123",
            "market": "Más de 2.5 goles",
            "minute": 60,
            "score_home": 1,
            "score_away": 0,
            "league": "Liga A",
            "estimated_probability_exploratory": 0.72,
            "outcome": "",
            "outcome_verified": "",
        }
        row.update(updates)
        return row

    def test_counts_valid_rows_and_distinct_forecasts(self):
        first = self.row()
        duplicate = self.row()
        another = self.row(minute=70, estimated_probability_exploratory=0.65)
        result = audit_forecast_dataset([first, duplicate, another])
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["structurally_valid_rows"], 3)
        self.assertEqual(result["distinct_valid_forecasts"], 2)
        self.assertEqual(result["duplicate_forecasts"], 1)

    def test_invalid_metadata_and_probability_are_reported(self):
        result = audit_forecast_dataset([
            self.row(recorded_at="fecha-invalida"),
            self.row(estimated_probability_exploratory=1.2),
            self.row(fixture_id=""),
        ])
        self.assertEqual(result["invalid_metadata_rows"], 2)
        self.assertEqual(result["invalid_probability_rows"], 1)
        self.assertEqual(result["distinct_valid_forecasts"], 0)

    def test_only_explicit_verified_binary_outcomes_count(self):
        result = audit_forecast_dataset([
            self.row(outcome=1, outcome_verified="true"),
            self.row(outcome="", outcome_verified="true"),
            self.row(outcome=0, outcome_verified="false"),
        ])
        self.assertEqual(result["verified_valid_outcomes"], 1)
        self.assertEqual(result["verified_invalid_outcomes"], 1)

    def test_groups_are_counted_only_from_structurally_valid_rows(self):
        result = audit_forecast_dataset([
            self.row(),
            self.row(league="Liga B", market="Ambos marcan", minute=75),
            self.row(league="Liga C", estimated_probability_exploratory="N/D"),
        ])
        self.assertEqual(result["market_count"], 2)
        self.assertEqual(result["league_count"], 2)
        self.assertEqual(result["leagues"], ["Liga A", "Liga B"])

    def test_canonical_probability_field_is_supported(self):
        row = self.row()
        row.pop("estimated_probability_exploratory")
        row["probability"] = 0.72
        result = audit_forecast_dataset([row])
        self.assertEqual(result["structurally_valid_rows"], 1)
        self.assertEqual(result["invalid_probability_rows"], 0)

    def test_non_list_input_is_safe(self):
        result = audit_forecast_dataset(None)
        self.assertEqual(result["row_count"], 0)
        self.assertEqual(result["distinct_valid_forecasts"], 0)


if __name__ == "__main__":
    unittest.main()
