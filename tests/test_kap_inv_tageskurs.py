"""Regression tests for KAP-INV Tageskurs correction with Teilfreistellung."""
import contextlib
import csv
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculate_tax_report import calculate_tax, get_kap_inv_tageskurs_delta_for_reporting


def calculate_for_trades(trades, closed_lots, conversion_rates):
    trade_fields = sorted({k for row in trades for k in row})
    lot_fields = sorted({k for row in closed_lots for k in row})
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "account_info.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["currency", "tax_year", "fx_transactions_count"])
            writer.writeheader()
            writer.writerow({"currency": "EUR", "tax_year": "2025", "fx_transactions_count": "0"})
        with open(os.path.join(tmp, "trades.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=trade_fields)
            writer.writeheader()
            writer.writerows(trades)
        with open(os.path.join(tmp, "closed_lots.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=lot_fields)
            writer.writeheader()
            writer.writerows(closed_lots)
        with open(os.path.join(tmp, "conversion_rates.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["reportDate", "fromCurrency", "toCurrency", "rate"])
            writer.writeheader()
            writer.writerows(conversion_rates)
        with contextlib.redirect_stdout(io.StringIO()):
            return calculate_tax(tmp)


def make_trade(symbol, isin, trade_id, pnl):
    return {
        "tradeID": trade_id,
        "assetCategory": "STK",
        "subCategory": "ETF",
        "transactionType": "ExchTrade",
        "buySell": "SELL",
        "symbol": symbol,
        "isin": isin,
        "quantity": "-10",
        "tradePrice": "110",
        "closePrice": "110",
        "fifoPnlRealized": str(pnl),
        "fxRateToBase": "0.9",
        "currency": "USD",
        "dateTime": "2025-02-01 10:00:00",
        "tradeDate": "2025-02-01",
        "reportDate": "2025-02-01",
    }


def make_closed_lot(symbol, isin):
    return {
        "assetCategory": "STK",
        "subCategory": "ETF",
        "currency": "USD",
        "symbol": symbol,
        "isin": isin,
        "openDateTime": "2025-01-01 10:00:00",
        "dateTime": "2025-02-01 10:00:00",
        "reportDate": "2025-02-01",
        "quantity": "10",
        "cost": "1000",
        "fifoPnlRealized": "100",
        "fxRateToBase": "0.9",
    }


def test_kap_inv_tageskurs_delta_applies_tfs_per_isin():
    rd = calculate_for_trades(
        trades=[
            make_trade("SPY", "US78462F1030", "SPY_SELL", 100),
            make_trade("SHY", "US4642874576", "SHY_SELL", 100),
        ],
        closed_lots=[
            make_closed_lot("SPY", "US78462F1030"),
            make_closed_lot("SHY", "US4642874576"),
        ],
        conversion_rates=[
            {"reportDate": "2025-01-01", "fromCurrency": "USD", "toCurrency": "EUR", "rate": "0.8"},
            {"reportDate": "2025-02-01", "fromCurrency": "USD", "toCurrency": "EUR", "rate": "0.9"},
        ],
    )

    raw_kap_inv_delta = rd["fx_correction_by_topf"]["KAP-INV"]
    taxable_kap_inv_delta = get_kap_inv_tageskurs_delta_for_reporting(rd)
    by_isin = rd["fx_correction_kap_inv_by_isin"]

    assert round(raw_kap_inv_delta, 2) == 200.00
    assert round(by_isin["US78462F1030"]["taxable_delta"], 2) == 70.00
    assert round(by_isin["US4642874576"]["taxable_delta"], 2) == 100.00
    assert round(taxable_kap_inv_delta, 2) == 170.00


if __name__ == "__main__":
    test_kap_inv_tageskurs_delta_applies_tfs_per_isin()
    print("OK: KAP-INV Tageskurs TFS")
