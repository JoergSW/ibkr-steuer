"""Synthetische Regression-Tests fuer GH Issues #56, #61 und #62.

Cross-Year-Same-Series-FIFO-Konflikt: Wenn dieselbe Option-Series sowohl im
Vorjahr als auch im Steuerjahr angedient wurde, hat der Same-Year-Block frueher
faelschlich die aeltesten Sells konsumiert (die im Vorjahres-Lauf bereits
versteuert waren). Pre-consume im _current_year_series_state-Build verschiebt
den FIFO-Startpunkt auf die juengeren Sells.

Mixed-Year-Konsum: Wenn eine Steuerjahr-Andienung Sells aus mehreren Jahren
konsumiert, muss nur der Vorjahresanteil als cross-year gelten.

Aufruf: python tests/test_cross_year_series.py
"""
import os
import sys
import contextlib
import csv
import io
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculate_tax_report import (
    _build_stillhalter_details_for_assignment,
    _consume_open_sells_fifo,
    _get_open_option_sells,
    calculate_tax,
    safe_float,
)


def make_sell(date, qty, price, strike="100", expiry="2024-12-20", pc="P",
              underlying="TEST", a_cat="OPT", multiplier="100", commission=-1.0):
    return {
        "tradeID": f"sell_{date}_{qty}",
        "assetCategory": a_cat,
        "transactionType": "ExchTrade",
        "buySell": "SELL",
        "putCall": pc,
        "strike": strike,
        "expiry": expiry,
        "underlyingSymbol": underlying,
        "symbol": f"{underlying} {strike} {expiry} {pc}",
        "quantity": str(-qty),
        "tradePrice": str(price),
        "closePrice": str(price),
        "multiplier": multiplier,
        "ibCommission": str(commission),
        "fxRateToBase": "1.0",
        "dateTime": f"{date} 10:00:00",
        "tradeDate": date,
        "reportDate": date,
        "fifoPnlRealized": "0",
    }


def make_assignment(date, qty, strike="100", expiry="2024-12-20", pc="P",
                    underlying="TEST", a_cat="OPT", multiplier="100"):
    return {
        "tradeID": f"assign_{date}_{qty}",
        "assetCategory": a_cat,
        "transactionType": "BookTrade",
        "buySell": "BUY",
        "putCall": pc,
        "strike": strike,
        "expiry": expiry,
        "underlyingSymbol": underlying,
        "symbol": f"{underlying} {strike} {expiry} {pc}",
        "quantity": str(qty),
        "tradePrice": "0",
        "closePrice": "0",
        "multiplier": multiplier,
        "ibCommission": "0",
        "fxRateToBase": "1.0",
        "dateTime": f"{date} 16:20:00",
        "tradeDate": date,
        "reportDate": date,
        "fifoPnlRealized": "0",
    }


def make_buy_close(date, qty, price, pnl, strike="100", expiry="2024-12-20",
                   pc="P", underlying="TEST", a_cat="OPT", multiplier="100"):
    return {
        "tradeID": f"close_{underlying}_{date}_{qty}_{price}",
        "assetCategory": a_cat,
        "transactionType": "ExchTrade",
        "buySell": "BUY",
        "putCall": pc,
        "strike": strike,
        "expiry": expiry,
        "underlyingSymbol": underlying,
        "symbol": f"{underlying} {strike} {expiry} {pc}",
        "quantity": str(qty),
        "tradePrice": str(price),
        "closePrice": str(price),
        "multiplier": multiplier,
        "ibCommission": "0",
        "fxRateToBase": "1.0",
        "currency": "USD",
        "dateTime": f"{date} 10:00:00",
        "tradeDate": date,
        "reportDate": date,
        "fifoPnlRealized": str(pnl),
    }


def calculate_for_trades(trades, tax_year=2022, closed_lots=None, conversion_rates=None):
    fieldnames = sorted({k for row in trades for k in row})
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "account_info.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["currency", "tax_year", "fx_transactions_count"])
            writer.writeheader()
            writer.writerow({"currency": "EUR", "tax_year": str(tax_year), "fx_transactions_count": "0"})
        with open(os.path.join(tmp, "trades.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(trades)
        if closed_lots:
            lot_fields = sorted({k for row in closed_lots for k in row})
            with open(os.path.join(tmp, "closed_lots.csv"), "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=lot_fields)
                writer.writeheader()
                writer.writerows(closed_lots)
        if conversion_rates:
            with open(os.path.join(tmp, "conversion_rates.csv"), "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["reportDate", "fromCurrency", "toCurrency", "rate"])
                writer.writeheader()
                writer.writerows(conversion_rates)
        with contextlib.redirect_stdout(io.StringIO()):
            return calculate_tax(tmp)


def simulate_pre_consume(trades, series_key, tax_year, base_currency="EUR",
                         usd_to_eur_rates=None):
    """Repliziert den Pre-consume-Block aus calculate_tax_report.py.

    Liefert den State NACH Pre-consume zurueck. Same-Year-Iteration kann
    dann auf diesem State fortsetzen.
    """
    a_cat, a_underlying, strike, expiry, pc = series_key
    assign_qty_series = sum(
        abs(int(safe_float(t.get("quantity"))))
        for t in trades
        if t.get("assetCategory") == a_cat
        and t.get("transactionType") == "BookTrade"
        and t.get("buySell") == "BUY"
        and t.get("strike") == strike
        and t.get("expiry") == expiry
        and t.get("putCall") == pc
        and t.get("underlyingSymbol", "") == a_underlying
        and abs(safe_float(t.get("fifoPnlRealized"))) < 0.01
    )
    state = _get_open_option_sells(
        trades, a_cat, strike, expiry, pc, assign_qty_series, underlying=a_underlying
    )

    from calculate_tax_report import parse_date
    prior_assigns = sorted(
        [t for t in trades
         if t.get("assetCategory") == a_cat
         and t.get("transactionType") == "BookTrade"
         and t.get("buySell") == "BUY"
         and t.get("strike") == strike
         and t.get("expiry") == expiry
         and t.get("putCall") == pc
         and t.get("underlyingSymbol", "") == a_underlying
         and abs(safe_float(t.get("fifoPnlRealized"))) < 0.01
         and (pd_ := parse_date(t.get("reportDate") or t.get("dateTime") or t.get("tradeDate"))) is not None
         and pd_.year < tax_year],
        key=lambda t: (t.get("dateTime", "") or t.get("tradeDate", "") or t.get("reportDate", "") or "")
    )
    if prior_assigns and state:
        first_open_pre = next((o for o in state if o.get("_open_qty", 0) > 0), None)
        if first_open_pre and safe_float(first_open_pre.get("multiplier")) > 0:
            mult_pre = int(safe_float(first_open_pre.get("multiplier"), 100))
        else:
            mult_pre = int(safe_float(prior_assigns[0].get("multiplier"), 100))
        for pa in prior_assigns:
            pa_qty = abs(int(safe_float(pa.get("quantity"))))
            if pa_qty <= 0:
                continue
            _consume_open_sells_fifo(state, pa_qty, mult_pre, base_currency, usd_to_eur_rates)

    return state


def assert_close(actual, expected, tol=0.001, label=""):
    if abs(actual - expected) > tol:
        raise AssertionError(f"{label}: erwartet {expected}, aktuell {actual} (delta {actual - expected})")


def test_cross_year_put_series():
    """TC1: Put-Series mit Vorjahr- und Steuerjahr-Andienung.

    Sells und Andienungen so konstruiert, dass close_qty = 0 (alle Sells offen).
    Vor-Fix (ohne Pre-consume): Same-Year-Block startet bei aeltestem Sell ->
    falsche Praemie. Mit Pre-consume: Vorjahres-Andienung verbraucht aeltesten
    Sell, Same-Year-Block startet bei juengerem Sell -> korrekte Praemie.
    """
    trades = [
        make_sell("2023-01-15", 10, 1.00),
        make_sell("2023-06-15", 10, 3.00),
        make_sell("2024-03-15", 10, 5.00),
        make_assignment("2023-12-15", 10),
        make_assignment("2024-04-15", 20),
    ]
    series_key = ("OPT", "TEST", "100", "2024-12-20", "P")
    state = simulate_pre_consume(trades, series_key, tax_year=2024)

    open_after_pre = [(o.get("dateTime"), o.get("_open_qty")) for o in state]
    assert open_after_pre[0][1] == 0, f"2023-01-Sell muss nach Pre-consume 0 sein, ist {open_after_pre[0][1]}"
    assert open_after_pre[1][1] == 10, f"2023-06-Sell muss 10 sein, ist {open_after_pre[1][1]}"
    assert open_after_pre[2][1] == 10, f"2024-03-Sell muss 10 sein, ist {open_after_pre[2][1]}"

    premium_raw, _comm, _fx, premium_eur, sells_consumed, consumed = _consume_open_sells_fifo(
        state, a_qty=20, mult=100, base_currency="EUR"
    )

    assert consumed == 20, f"erwartet 20 ct konsumiert, aktuell {consumed}"
    assert_close(premium_raw, 10 * 3 * 100 + 10 * 5 * 100, label="TC1 premium_raw")
    consumed_dates = [o[0].get("dateTime") for o in sells_consumed]
    assert "2023-06-15 10:00:00" in consumed_dates and "2024-03-15 10:00:00" in consumed_dates, \
        f"erwartete Sells: 2023-06 + 2024-03, aktuell {consumed_dates}"
    assert "2023-01-15 10:00:00" not in consumed_dates, "2023-01-Sell darf NICHT im Same-Year-Konsum sein"

    print("  TC1 Cross-Year-Put-Series: OK")
    print(f"    Same-Year-Praemie raw = {premium_raw:.2f} USD (erwartet 8000.00)")


def test_cross_year_call_series():
    """TC2: Call-Series mit Vorjahr- und Steuerjahr-Andienung.

    Pre-consume gilt fuer Calls UND Puts (series_key enthaelt pc).
    Vorjahres-Call-Praemie wird verworfen (im Vorjahres-Lauf bereits versteuert),
    Same-Year-Block sieht nur die juengeren Sells.
    """
    trades = [
        make_sell("2023-02-10", 5, 2.00, pc="C", underlying="AAPL"),
        make_sell("2024-01-10", 5, 4.00, pc="C", underlying="AAPL"),
        make_assignment("2023-12-15", 5, pc="C", underlying="AAPL"),
        make_assignment("2024-05-15", 5, pc="C", underlying="AAPL"),
    ]
    series_key = ("OPT", "AAPL", "100", "2024-12-20", "C")
    state = simulate_pre_consume(trades, series_key, tax_year=2024)

    open_after_pre = [(o.get("dateTime"), o.get("_open_qty")) for o in state]
    assert open_after_pre[0][1] == 0, f"2023-02-Sell muss 0 sein nach Pre-consume, ist {open_after_pre[0][1]}"
    assert open_after_pre[1][1] == 5, f"2024-01-Sell muss 5 sein, ist {open_after_pre[1][1]}"

    premium_raw, _comm, _fx, premium_eur, sells_consumed, consumed = _consume_open_sells_fifo(
        state, a_qty=5, mult=100, base_currency="EUR"
    )
    assert consumed == 5, f"erwartet 5 ct konsumiert, aktuell {consumed}"
    assert_close(premium_raw, 5 * 4 * 100, label="TC2 premium_raw")
    consumed_dates = [o[0].get("dateTime") for o in sells_consumed]
    assert "2024-01-10 10:00:00" in consumed_dates, \
        f"erwartet 2024-01-Sell, aktuell {consumed_dates}"
    assert "2023-02-10 10:00:00" not in consumed_dates, \
        "2023-02-Sell darf nicht doppelt versteuert werden"

    print("  TC2 Cross-Year-Call-Series: OK")
    print(f"    Same-Year-Praemie raw = {premium_raw:.2f} USD (erwartet 2000.00)")


def test_steueryahr_only_no_op():
    """TC3: Series ohne Vorjahres-Andienung. Pre-consume ist no-op."""
    trades = [
        make_sell("2024-02-10", 10, 2.50),
        make_sell("2024-08-10", 10, 4.00),
        make_assignment("2024-09-15", 10),
    ]
    series_key = ("OPT", "TEST", "100", "2024-12-20", "P")
    state = simulate_pre_consume(trades, series_key, tax_year=2024)

    open_qtys = sum(o.get("_open_qty", 0) for o in state)
    assert open_qtys == 10, f"State muss 10 OPEN qty haben (close_qty=10), ist {open_qtys}"

    premium_raw, _comm, _fx, premium_eur, sells_consumed, consumed = _consume_open_sells_fifo(
        state, a_qty=10, mult=100, base_currency="EUR"
    )
    assert consumed == 10
    consumed_dates = [o[0].get("dateTime") for o in sells_consumed]
    assert len(consumed_dates) == 1, f"erwartet 1 Sell konsumiert, aktuell {len(consumed_dates)}"
    print(f"  TC3 Steuerjahr-only no-op: OK (consumed Sell {consumed_dates[0]})")


def test_mixed_year_assignment_splits_cross_year_premium():
    """TC4: Eine Steuerjahr-Andienung konsumiert Sells aus zwei Jahren.

    Nur der 2023-Anteil darf cross-year sein. Vor Issue #62 wurde wegen des
    fruehesten orig_sell_date die komplette Assignment-Praemie markiert.
    """
    trades = [
        make_sell("2023-06-15", 2, 3.00),
        make_sell("2024-03-15", 5, 5.00),
        make_assignment("2024-04-15", 7),
    ]
    assignment = trades[-1]
    state = _get_open_option_sells(
        trades, "OPT", "100", "2024-12-20", "P", 7, underlying="TEST"
    )
    premium_raw, commission_raw, _fx, premium_eur, sells_consumed, consumed = _consume_open_sells_fifo(
        state, a_qty=7, mult=100, base_currency="EUR"
    )
    assert consumed == 7

    details = _build_stillhalter_details_for_assignment(
        assignment, "100", "2024-12-20", "P", 7, 100, 2024,
        sells_consumed, premium_raw, commission_raw, premium_eur, base_currency="EUR"
    )

    assert len(details) == 2, f"erwartet 2 Detail-Splits, aktuell {len(details)}"
    by_year = {d["orig_sell_year"]: d for d in details}
    assert by_year[2023]["quantity"] == 2
    assert by_year[2024]["quantity"] == 5
    assert by_year[2023]["is_cross_year"] is True
    assert by_year[2024]["is_cross_year"] is False

    cross_year_premium = sum(d["premium_eur"] for d in details if d["is_cross_year"])
    detail_total = sum(d["premium_eur"] for d in details)
    assert_close(cross_year_premium, 2 * 3 * 100 - 1, label="TC4 cross_year_premium")
    assert_close(detail_total, premium_eur, label="TC4 detail_total")

    print("  TC4 Mixed-Year-Assignment-Split: OK")
    print(f"    Cross-Year-Praemie = {cross_year_premium:.2f} EUR, Gesamt = {detail_total:.2f} EUR")


def test_issue_56_prior_year_correction_uses_underlying():
    """TC5: Vorjahres-Zufluss darf gleichartige Serien anderer Underlyings nicht konsumieren."""
    trades = [
        make_sell("2021-12-01", 2, 19.90, strike="155", expiry="2022-01-21", underlying="GPN"),
        make_sell("2021-12-03", 1, 3.20, strike="155", expiry="2022-01-21", underlying="SQ"),
        make_buy_close("2022-01-05", 1, 11.65, -847, strike="155", expiry="2022-01-21", underlying="SQ"),
    ]
    rd = calculate_for_trades(trades, tax_year=2022)
    audit = rd.get("audit", {})

    assert_close(audit.get("prior_zufluss_correction_eur", 0), 319.0,
                 label="TC5 prior_zufluss_correction_eur")
    details = audit.get("prior_zufluss_details", [])
    assert len(details) == 1, f"erwartet 1 Vorjahres-Korrektur, aktuell {len(details)}"
    assert details[0].get("underlyingSymbol") == "SQ", \
        f"erwartet SQ-Korrektur, aktuell {details[0].get('underlyingSymbol')}"

    print("  TC5 Issue #56 Vorjahres-Korrektur nach Underlying: OK")
    print(f"    Korrektur = {audit.get('prior_zufluss_correction_eur', 0):.2f} EUR (SQ, nicht GPN)")


def test_issue_56_current_year_zufluss_uses_underlying():
    """TC6: Current-year Zufluss muss offene Fills pro Underlying bestimmen."""
    trades = [
        make_sell("2022-01-01", 1, 10.00, strike="155", expiry="2022-01-21", underlying="GPN"),
        make_sell("2022-01-02", 1, 2.00, strike="155", expiry="2022-01-21", underlying="SQ"),
        make_buy_close("2022-01-03", 1, 5.00, -300, strike="155", expiry="2022-01-21", underlying="SQ"),
    ]
    rd = calculate_for_trades(trades, tax_year=2022)
    audit = rd.get("audit", {})

    assert_close(audit.get("zufluss_premium_eur", 0), 999.0,
                 label="TC6 zufluss_premium_eur")
    details = audit.get("zufluss_details", [])
    assert len(details) == 1, f"erwartet 1 offene Zufluss-Position, aktuell {len(details)}"
    assert details[0].get("underlyingSymbol") == "GPN", \
        f"erwartet GPN-Zufluss, aktuell {details[0].get('underlyingSymbol')}"

    print("  TC6 Issue #56 Current-Year-Zufluss nach Underlying: OK")
    print(f"    Zufluss = {audit.get('zufluss_premium_eur', 0):.2f} EUR (GPN offen, SQ geschlossen)")


def _mu_put_assignment_trade_set(stock_cost, stock_pnl, assignment_datetime="2025-04-28 16:20:00",
                                 stock_book_cost=None):
    """Synthetic MU weekly put assignment based on the user-reported screenshots."""
    premium = 184.37773
    return [
        {
            "tradeID": "mu_put_sell",
            "assetCategory": "OPT",
            "transactionType": "ExchTrade",
            "buySell": "SELL",
            "openCloseIndicator": "O",
            "putCall": "P",
            "strike": "84",
            "expiry": "2025-04-25",
            "underlyingSymbol": "MU",
            "symbol": "MU 25APR25 84 P",
            "description": "MU 25APR25 84 P",
            "quantity": "-1",
            "tradePrice": str(premium / 100),
            "closePrice": str(premium / 100),
            "multiplier": "100",
            "ibCommission": "0",
            "fxRateToBase": "0.87998",
            "currency": "USD",
            "dateTime": "2025-04-25 10:00:00",
            "tradeDate": "2025-04-25",
            "reportDate": "2025-04-25",
            "fifoPnlRealized": "0",
            "cost": "0",
            "proceeds": str(premium),
        },
        {
            "tradeID": "mu_put_assignment",
            "assetCategory": "OPT",
            "transactionType": "BookTrade",
            "buySell": "BUY",
            "openCloseIndicator": "C",
            "putCall": "P",
            "strike": "84",
            "expiry": "2025-04-25",
            "underlyingSymbol": "MU",
            "symbol": "MU 25APR25 84 P",
            "description": "MU 25APR25 84 P",
            "quantity": "1",
            "tradePrice": "0",
            "closePrice": "4.22",
            "multiplier": "100",
            "ibCommission": "0",
            "fxRateToBase": "0.87551",
            "currency": "USD",
            "dateTime": assignment_datetime,
            "tradeDate": "2025-04-25",
            "reportDate": assignment_datetime[:10],
            "fifoPnlRealized": "0",
            "cost": "0",
            "proceeds": "0",
        },
        {
            "tradeID": "mu_stock_assignment",
            "assetCategory": "STK",
            "transactionType": "BookTrade",
            "buySell": "BUY",
            "openCloseIndicator": "O",
            "underlyingSymbol": "MU",
            "symbol": "MU",
            "description": "MICRON TECHNOLOGY INC",
            "quantity": "100",
            "tradePrice": "84",
            "closePrice": "78.56",
            "ibCommission": "0",
            "fxRateToBase": "0.87551",
            "currency": "USD",
            "dateTime": "2025-04-25 16:20:00",
            "tradeDate": "2025-04-25",
            "reportDate": assignment_datetime[:10],
            "fifoPnlRealized": "0",
            "cost": str(stock_book_cost if stock_book_cost is not None else stock_cost),
            "proceeds": "-8400",
            "isin": "US5951121038",
        },
        {
            "tradeID": "mu_stock_sale",
            "assetCategory": "STK",
            "transactionType": "ExchTrade",
            "buySell": "SELL",
            "openCloseIndicator": "C",
            "underlyingSymbol": "MU",
            "symbol": "MU",
            "description": "MICRON TECHNOLOGY INC",
            "quantity": "-100",
            "tradePrice": "116.38",
            "closePrice": "116.38",
            "ibCommission": "-1.02",
            "fxRateToBase": "0.8705",
            "currency": "USD",
            "dateTime": "2025-06-11 10:00:00",
            "tradeDate": "2025-06-11",
            "reportDate": "2025-06-11",
            "fifoPnlRealized": str(stock_pnl),
            "cost": str(stock_cost),
            "proceeds": "11636.98",
            "isin": "US5951121038",
        },
    ]


def _mu_closed_lot(cost):
    return [{
        "assetCategory": "STK",
        "currency": "USD",
        "reportDate": "2025-06-11",
        "dateTime": "2025-06-11 10:00:00",
        "openDateTime": "2025-04-25 16:20:00",
        "quantity": "100",
        "cost": str(cost),
        "fifoPnlRealized": "3236.98",
        "fxRateToBase": "0.8705",
        "symbol": "MU",
        "description": "MICRON TECHNOLOGY INC",
        "isin": "US5951121038",
        "underlyingSymbol": "MU",
    }]


def test_put_assignment_does_not_double_correct_strike_basis():
    """TC7: Weekly/early put assignment where IBKR already uses strike as stock basis."""
    trades = _mu_put_assignment_trade_set(8400.0, 3236.98, stock_book_cost=8400.0)
    rd = calculate_for_trades(
        trades,
        tax_year=2025,
        closed_lots=_mu_closed_lot(8400.0),
        conversion_rates=[
            {"reportDate": "2025-04-25", "fromCurrency": "USD", "toCurrency": "EUR", "rate": "0.87998"},
            {"reportDate": "2025-06-11", "fromCurrency": "USD", "toCurrency": "EUR", "rate": "0.87050"},
        ],
    )
    stock_rows = [r for r in rd["trade_details"] if r.get("symbol") == "MU" and r.get("source") == "trades"]
    assert len(stock_rows) == 1, f"erwartet 1 MU-Aktienzeile, aktuell {len(stock_rows)}"
    assert_close(stock_rows[0]["cost"], 8400.0, label="TC7 stock cost")
    assert_close(stock_rows[0]["fifoPnlRealized"], 3236.98, label="TC7 stock pnl raw")

    fx_details = rd.get("fx_correction_details", [])
    assert len(fx_details) == 1, f"erwartet 1 Tageskurs-Lot, aktuell {len(fx_details)}"
    assert_close(fx_details[0]["cost"], 8400.0, label="TC7 Tageskurs cost")

    print("  TC7 Put-Assignment mit Strike-Basis nicht doppelt korrigiert: OK")
    print(f"    Kostenbasis bleibt {stock_rows[0]['cost']:.2f} USD")


def test_put_assignment_corrects_reduced_cost_basis():
    """TC8: Put assignment where IBKR stock basis is reduced by the premium."""
    premium = 184.37773
    reduced_cost = 8400.0 - premium
    reduced_pnl = 11636.98 - reduced_cost
    trades = _mu_put_assignment_trade_set(
        reduced_cost, reduced_pnl, assignment_datetime="2025-04-25 16:20:00",
        stock_book_cost=reduced_cost
    )
    rd = calculate_for_trades(
        trades,
        tax_year=2025,
        closed_lots=_mu_closed_lot(reduced_cost),
        conversion_rates=[
            {"reportDate": "2025-04-25", "fromCurrency": "USD", "toCurrency": "EUR", "rate": "0.87998"},
            {"reportDate": "2025-06-11", "fromCurrency": "USD", "toCurrency": "EUR", "rate": "0.87050"},
        ],
    )
    stock_rows = [r for r in rd["trade_details"] if r.get("symbol") == "MU" and r.get("source") == "trades"]
    assert len(stock_rows) == 1, f"erwartet 1 MU-Aktienzeile, aktuell {len(stock_rows)}"
    assert_close(stock_rows[0]["cost"], 8400.0, label="TC8 stock cost")
    assert_close(stock_rows[0]["fifoPnlRealized"], 3236.98, label="TC8 stock pnl raw")
    assert_close(rd["fx_correction_details"][0]["cost"], 8400.0, label="TC8 Tageskurs cost")

    print("  TC8 Put-Assignment mit reduzierter IBKR-Basis korrigiert: OK")
    print(f"    {reduced_cost:.2f} USD -> {stock_rows[0]['cost']:.2f} USD")


def test_same_day_put_assignment_does_not_double_correct_strike_basis():
    """TC9: Early/same-day put assignment where IBKR already uses strike as stock basis."""
    trades = _mu_put_assignment_trade_set(
        8400.0, 3236.98, assignment_datetime="2025-04-25 16:20:00",
        stock_book_cost=8400.0
    )
    rd = calculate_for_trades(
        trades,
        tax_year=2025,
        closed_lots=_mu_closed_lot(8400.0),
        conversion_rates=[
            {"reportDate": "2025-04-25", "fromCurrency": "USD", "toCurrency": "EUR", "rate": "0.87998"},
            {"reportDate": "2025-06-11", "fromCurrency": "USD", "toCurrency": "EUR", "rate": "0.87050"},
        ],
    )
    stock_rows = [r for r in rd["trade_details"] if r.get("symbol") == "MU" and r.get("source") == "trades"]
    assert len(stock_rows) == 1, f"erwartet 1 MU-Aktienzeile, aktuell {len(stock_rows)}"
    assert_close(stock_rows[0]["cost"], 8400.0, label="TC9 stock cost")
    assert_close(stock_rows[0]["fifoPnlRealized"], 3236.98, label="TC9 stock pnl raw")

    print("  TC9 Same-Day-Put-Assignment mit Strike-Basis nicht doppelt korrigiert: OK")
    print(f"    Kostenbasis bleibt {stock_rows[0]['cost']:.2f} USD")


def test_prior_year_put_lot_sold_before_tax_year_does_not_touch_current_sale():
    """TC10: History-lot from prior year must not leak into an unrelated 2025 sale."""
    prior_year_trades = [
        make_sell("2024-03-01", 1, 2.00, strike="70", expiry="2024-03-15",
                  pc="P", underlying="MU", commission=-1.0),
        make_assignment("2024-03-15", 1, strike="70", expiry="2024-03-15",
                        pc="P", underlying="MU"),
        {
            "tradeID": "mu_2024_stock_sale",
            "assetCategory": "STK",
            "transactionType": "ExchTrade",
            "buySell": "SELL",
            "openCloseIndicator": "C",
            "underlyingSymbol": "MU",
            "symbol": "MU",
            "description": "MICRON TECHNOLOGY INC",
            "quantity": "-100",
            "tradePrice": "75",
            "closePrice": "75",
            "ibCommission": "0",
            "fxRateToBase": "1.0",
            "currency": "USD",
            "dateTime": "2024-04-01 10:00:00",
            "tradeDate": "2024-04-01",
            "reportDate": "2024-04-01",
            "fifoPnlRealized": "500",
            "cost": "7000",
            "proceeds": "7500",
            "isin": "US5951121038",
        },
    ]
    trades = prior_year_trades + _mu_put_assignment_trade_set(
        8400.0, 3236.98, assignment_datetime="2025-04-25 16:20:00",
        stock_book_cost=8400.0
    )
    rd = calculate_for_trades(
        trades,
        tax_year=2025,
        closed_lots=_mu_closed_lot(8400.0),
        conversion_rates=[
            {"reportDate": "2025-04-25", "fromCurrency": "USD", "toCurrency": "EUR", "rate": "0.87998"},
            {"reportDate": "2025-06-11", "fromCurrency": "USD", "toCurrency": "EUR", "rate": "0.87050"},
        ],
    )
    stock_rows = [r for r in rd["trade_details"] if r.get("symbol") == "MU" and r.get("source") == "trades"]
    assert len(stock_rows) == 1, f"erwartet 1 MU-Aktienzeile, aktuell {len(stock_rows)}"
    assert_close(stock_rows[0]["cost"], 8400.0, label="TC10 stock cost")
    assert_close(stock_rows[0]["fifoPnlRealized"], 3236.98, label="TC10 stock pnl raw")
    assert not rd["audit"].get("cross_year_put_corrections"), \
        f"unerwartete Cross-Year-Korrektur: {rd['audit'].get('cross_year_put_corrections')}"

    print("  TC10 Verkaufte Vorjahres-Andienung leakt nicht in 2025-MU-Verkauf: OK")
    print(f"    Kostenbasis bleibt {stock_rows[0]['cost']:.2f} USD")


def test_prior_year_put_lot_sold_in_tax_year_is_still_corrected():
    """TC11: Matching CLOSED_LOT open date still allows real cross-year correction."""
    trades = [
        make_sell("2024-03-01", 1, 2.00, strike="70", expiry="2024-03-15",
                  pc="P", underlying="MU", commission=-1.0),
        make_assignment("2024-03-15", 1, strike="70", expiry="2024-03-15",
                        pc="P", underlying="MU"),
        {
            "tradeID": "mu_2025_sale_prior_lot",
            "assetCategory": "STK",
            "transactionType": "ExchTrade",
            "buySell": "SELL",
            "openCloseIndicator": "C",
            "underlyingSymbol": "MU",
            "symbol": "MU",
            "description": "MICRON TECHNOLOGY INC",
            "quantity": "-100",
            "tradePrice": "80",
            "closePrice": "80",
            "ibCommission": "0",
            "fxRateToBase": "1.0",
            "currency": "USD",
            "dateTime": "2025-02-01 10:00:00",
            "tradeDate": "2025-02-01",
            "reportDate": "2025-02-01",
            "fifoPnlRealized": "1199",
            "cost": "6801",
            "proceeds": "8000",
            "isin": "US5951121038",
        },
    ]
    closed_lots = [{
        "assetCategory": "STK",
        "currency": "USD",
        "reportDate": "2025-02-01",
        "dateTime": "2025-02-01 10:00:00",
        "openDateTime": "2024-03-15 16:20:00",
        "quantity": "100",
        "cost": "6801",
        "fifoPnlRealized": "1199",
        "fxRateToBase": "1.0",
        "symbol": "MU",
        "description": "MICRON TECHNOLOGY INC",
        "isin": "US5951121038",
        "underlyingSymbol": "MU",
    }]
    rd = calculate_for_trades(trades, tax_year=2025, closed_lots=closed_lots)
    stock_rows = [r for r in rd["trade_details"] if r.get("symbol") == "MU" and r.get("source") == "trades"]
    assert len(stock_rows) == 1, f"erwartet 1 MU-Aktienzeile, aktuell {len(stock_rows)}"
    assert_close(stock_rows[0]["cost"], 7000.0, label="TC11 stock cost")
    assert_close(stock_rows[0]["fifoPnlRealized"], 1000.0, label="TC11 stock pnl raw")
    assert len(rd["audit"].get("cross_year_put_corrections", [])) == 1, \
        f"erwartet 1 Cross-Year-Korrektur, aktuell {rd['audit'].get('cross_year_put_corrections')}"

    print("  TC11 Echte Cross-Year-Andienung mit CLOSED_LOT-Match bleibt korrigiert: OK")
    print(f"    Kostenbasis {stock_rows[0]['cost']:.2f} USD")


def test_same_year_put_requires_matching_closed_lot():
    """TC12: Same-Year-Put darf keinen alten Aktienverkauf desselben Symbols korrigieren."""
    trades = [
        {
            "tradeID": "mu_old_stock_sale",
            "assetCategory": "STK",
            "transactionType": "ExchTrade",
            "buySell": "SELL",
            "openCloseIndicator": "C",
            "underlyingSymbol": "MU",
            "symbol": "MU",
            "description": "MICRON TECHNOLOGY INC",
            "quantity": "-100",
            "tradePrice": "90",
            "closePrice": "90",
            "ibCommission": "0",
            "fxRateToBase": "1.0",
            "currency": "USD",
            "dateTime": "2025-01-10 10:00:00",
            "tradeDate": "2025-01-10",
            "reportDate": "2025-01-10",
            "fifoPnlRealized": "1000",
            "cost": "8000",
            "proceeds": "9000",
            "isin": "US5951121038",
        },
    ] + _mu_put_assignment_trade_set(
        8400.0, 3236.98, assignment_datetime="2025-04-25 16:20:00",
        stock_book_cost=8400.0
    )[:3]
    closed_lots = [{
        "assetCategory": "STK",
        "currency": "USD",
        "reportDate": "2025-01-10",
        "dateTime": "2025-01-10 10:00:00",
        "openDateTime": "2024-12-01 10:00:00",
        "quantity": "100",
        "cost": "8000",
        "fifoPnlRealized": "1000",
        "fxRateToBase": "1.0",
        "symbol": "MU",
        "description": "MICRON TECHNOLOGY INC",
        "isin": "US5951121038",
        "underlyingSymbol": "MU",
    }]
    rd = calculate_for_trades(trades, tax_year=2025, closed_lots=closed_lots)
    stock_rows = [r for r in rd["trade_details"] if r.get("symbol") == "MU" and r.get("source") == "trades"]
    assert len(stock_rows) == 1, f"erwartet 1 MU-Aktienzeile, aktuell {len(stock_rows)}"
    assert_close(stock_rows[0]["cost"], 8000.0, label="TC12 stock cost")
    assert_close(stock_rows[0]["fifoPnlRealized"], 1000.0, label="TC12 stock pnl raw")
    assert not stock_rows[0].get("stillhalter_adjusted"), "alter MU-Verkauf darf nicht korrigiert werden"

    print("  TC12 Same-Year-Put ohne CLOSED_LOT-Match korrigiert keinen Altbestand: OK")
    print(f"    alter MU-Verkauf bleibt bei {stock_rows[0]['cost']:.2f} USD Kostenbasis")


def test_zufluss_fifo_current_close_consumes_prior_sell_first():
    """TC13: Ein Steuerjahr-Rueckkauf schliesst FIFO erst den Vorjahres-Short."""
    trades = [
        make_sell("2024-12-15", 1, 5.00, strike="100", expiry="2025-03-21", underlying="FIFO"),
        make_sell("2025-01-10", 1, 7.00, strike="100", expiry="2025-03-21", underlying="FIFO"),
        make_buy_close("2025-01-20", 1, 2.00, -300, strike="100", expiry="2025-03-21", underlying="FIFO"),
    ]
    rd = calculate_for_trades(trades, tax_year=2025)
    audit = rd.get("audit", {})

    assert_close(audit.get("prior_zufluss_correction_eur", 0), 499.0,
                 label="TC13 prior_zufluss_correction_eur")
    assert_close(audit.get("zufluss_premium_eur", 0), 699.0,
                 label="TC13 zufluss_premium_eur")

    print("  TC13 Zufluss-FIFO: Steuerjahr-Close konsumiert Vorjahres-Sell zuerst: OK")
    print("    Vorjahreskorrektur 499.00 EUR, offener Steuerjahr-Zufluss 699.00 EUR")


def test_zufluss_fifo_prior_close_consumes_prior_sell_before_tax_year():
    """TC14: Bereits im Vorjahr geschlossene Shorts duerfen 2025 nicht erneut korrigiert werden."""
    trades = [
        make_sell("2024-12-01", 1, 5.00, strike="100", expiry="2025-03-21", underlying="FIFO"),
        make_buy_close("2024-12-15", 1, 1.00, 399, strike="100", expiry="2025-03-21", underlying="FIFO"),
        make_sell("2025-01-10", 1, 7.00, strike="100", expiry="2025-03-21", underlying="FIFO"),
        make_buy_close("2025-01-20", 1, 2.00, 499, strike="100", expiry="2025-03-21", underlying="FIFO"),
    ]
    rd = calculate_for_trades(trades, tax_year=2025)
    audit = rd.get("audit", {})

    assert_close(audit.get("prior_zufluss_correction_eur", 0), 0.0,
                 label="TC14 prior_zufluss_correction_eur")
    assert_close(audit.get("zufluss_premium_eur", 0), 0.0,
                 label="TC14 zufluss_premium_eur")

    print("  TC14 Zufluss-FIFO: im Vorjahr geschlossener Short bleibt erledigt: OK")
    print("    keine falsche Vorjahreskorrektur in 2025")


if __name__ == "__main__":
    test_cross_year_put_series()
    test_cross_year_call_series()
    test_steueryahr_only_no_op()
    test_mixed_year_assignment_splits_cross_year_premium()
    test_issue_56_prior_year_correction_uses_underlying()
    test_issue_56_current_year_zufluss_uses_underlying()
    test_put_assignment_does_not_double_correct_strike_basis()
    test_put_assignment_corrects_reduced_cost_basis()
    test_same_day_put_assignment_does_not_double_correct_strike_basis()
    test_prior_year_put_lot_sold_before_tax_year_does_not_touch_current_sale()
    test_prior_year_put_lot_sold_in_tax_year_is_still_corrected()
    test_same_year_put_requires_matching_closed_lot()
    test_zufluss_fifo_current_close_consumes_prior_sell_first()
    test_zufluss_fifo_prior_close_consumes_prior_sell_before_tax_year()
    print("\nOK: alle 14 TCs gruen")
