import csv
import tempfile
import unittest
from pathlib import Path

from calculate_tax_report import calculate_tax


def write_statement_of_funds(base_dir, rows):
    path = Path(base_dir) / "statement_of_funds.csv"
    headers = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


class GermanDividendTaxTest(unittest.TestCase):
    def test_german_dividend_tax_is_not_foreign_withholding(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_statement_of_funds(
                tmp,
                [
                    {
                        "activityCode": "DIV",
                        "activityDescription": "SAP Cash Dividend",
                        "amount": "1000",
                        "assetCategory": "STK",
                        "currency": "EUR",
                        "date": "2025-05-22",
                        "fxRateToBase": "1",
                        "isin": "DE0007164600",
                        "reportDate": "2025-05-22",
                        "symbol": "SAP",
                    },
                    {
                        "activityCode": "",
                        "activityDescription": "SAP Cash Dividend - DE Steuer",
                        "amount": "-263.75",
                        "assetCategory": "STK",
                        "currency": "EUR",
                        "date": "2025-05-22",
                        "fxRateToBase": "1",
                        "isin": "DE0007164600",
                        "reportDate": "2025-05-22",
                        "symbol": "SAP",
                    },
                    {
                        "activityCode": "DIV",
                        "activityDescription": "AAPL Cash Dividend",
                        "amount": "500",
                        "assetCategory": "STK",
                        "currency": "EUR",
                        "date": "2025-02-14",
                        "fxRateToBase": "1",
                        "isin": "US0378331005",
                        "reportDate": "2025-02-14",
                        "symbol": "AAPL",
                    },
                    {
                        "activityCode": "FRTAX",
                        "activityDescription": "AAPL Cash Dividend - US Tax",
                        "amount": "-75",
                        "assetCategory": "STK",
                        "currency": "EUR",
                        "date": "2025-02-14",
                        "fxRateToBase": "1",
                        "isin": "US0378331005",
                        "reportDate": "2025-02-14",
                        "symbol": "AAPL",
                    },
                ],
            )

            report = calculate_tax(tmp, tax_year=2025)

        self.assertEqual(
            round(report["zeile_7_kapitalertraege_mit_inlaendischem_steuerabzug_eur"], 2),
            1000.00,
        )
        self.assertEqual(round(report["zeile_19_netto_eur"], 2), 500.00)
        self.assertEqual(round(report["zeile_37_kapitalertragsteuer_eur"], 2), 250.00)
        self.assertEqual(round(report["zeile_38_solidaritaetszuschlag_eur"], 2), 13.75)
        self.assertEqual(round(report["zeile_41_withholding_tax_eur"], 2), 75.00)

    def test_german_dividend_tax_with_frtax_de_tax_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_statement_of_funds(
                tmp,
                [
                    {
                        "activityCode": "DIV",
                        "activityDescription": (
                            "RHM(DE0007030009) Cash Dividend EUR 11.50 per Share "
                            "(Ordinary Dividend)"
                        ),
                        "amount": "287.5",
                        "assetCategory": "STK",
                        "currency": "EUR",
                        "date": "2026-05-15",
                        "fxRateToBase": "1",
                        "isin": "DE0007030009",
                        "reportDate": "2026-05-15",
                        "symbol": "RHM",
                    },
                    {
                        "activityCode": "FRTAX",
                        "activityDescription": (
                            "RHM(DE0007030009) Cash Dividend EUR 11.50 per Share "
                            "- DE Tax"
                        ),
                        "amount": "-75.83",
                        "assetCategory": "STK",
                        "currency": "EUR",
                        "date": "2026-05-15",
                        "fxRateToBase": "1",
                        "isin": "DE0007030009",
                        "reportDate": "2026-05-15",
                        "symbol": "RHM",
                    },
                ],
            )

            report = calculate_tax(tmp, tax_year=2026)

        self.assertEqual(
            round(report["zeile_7_kapitalertraege_mit_inlaendischem_steuerabzug_eur"], 2),
            287.50,
        )
        self.assertEqual(round(report["zeile_19_netto_eur"], 2), 0.00)
        self.assertEqual(round(report["zeile_37_kapitalertragsteuer_eur"], 2), 71.88)
        self.assertEqual(round(report["zeile_38_solidaritaetszuschlag_eur"], 2), 3.95)
        self.assertEqual(round(report["zeile_41_withholding_tax_eur"], 2), 0.00)


if __name__ == "__main__":
    unittest.main()
