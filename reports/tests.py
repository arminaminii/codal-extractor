from django.test import SimpleTestCase

from .services import (
    _find_value_in_sheet,
    _discover_primary_sheet_ids,
    _parse_cell_value,
    _parse_codal_date,
    _profit_after_expense,
    calculate_financial_ratios,
    parse_financial_report,
)
from .templatetags.codal_tags import format_num, format_ratio, format_ratio_field


def cell(address, column, value, row_code=None):
    return {
        "address": address,
        "columnCode": column,
        "rowCode": row_code or int("".join(filter(str.isdigit, address))),
        "value": value,
        "periodEndToDate": "1404/12/29" if column != 1 else "",
        "yearEndToDate": "1403/12/30" if column != 1 else "",
        "rowTypeName": "FixedRow",
    }


def datasource(cells, code=0, title="صورت وضعیت مالی"):
    return {
        "title_Fa": "گزارش آزمون",
        "sheets": [{
            "code": code,
            "title_Fa": title,
            "tables": [{"title_Fa": title, "cells": cells}],
        }],
    }


class CodalDateTests(SimpleTestCase):
    def test_current_jalali_publish_date_is_parsed(self):
        value = _parse_codal_date("۱۴۰۵/۰۷/۰۷ ۱۸:۵۵:۳۴")
        self.assertIsNotNone(value)
        self.assertEqual((value.hour, value.minute, value.second), (18, 55, 34))
        self.assertIsNotNone(value.tzinfo)

    def test_persian_thousands_separator_is_parsed(self):
        self.assertEqual(_parse_cell_value("۱٬۲۳۴٬۵۶۷"), 1234567.0)

    def test_real_zero_is_rendered_while_missing_value_is_dash(self):
        self.assertEqual(format_num(0), "۰")
        self.assertEqual(format_num(None), "—")

    def test_financial_numbers_are_rendered_with_persian_digits(self):
        self.assertEqual(format_num(1234567), "۱٬۲۳۴٬۵۶۷")
        self.assertEqual(format_ratio(0.123, "percent"), "۱۲٫۳٪")
        self.assertEqual(format_ratio(1.25, "ratio"), "۱٫۲۵")


class FinancialParserTests(SimpleTestCase):
    def test_sheet_ids_are_discovered_from_codal_selector(self):
        page = """
        <html><head><title>صورت‌های مالی تلفیقی ۱۲ ماهه</title></head><body>
        <select name="ctl00$ddlTable" id="ddlTable">
          <option value="13">صورت سود و زیان تلفیقی</option>
          <option value="1097">صورت سود و زیان جامع تلفیقی</option>
          <option value="14">صورت وضعیت مالی تلفیقی</option>
          <option value="15">صورت جریان های نقدی تلفیقی</option>
          <option value="1">صورت سود و زیان</option>
          <option value="0">صورت وضعیت مالی</option>
          <option value="9">صورت جریان های نقدی</option>
        </select></body></html>
        """
        self.assertEqual(_discover_primary_sheet_ids(page), [13, 14, 15])

    def test_standalone_report_does_not_mix_consolidated_sheets(self):
        page = """
        <html><head><title>صورت‌های مالی ۱۲ ماهه</title></head><body>
        <select id="ddlTable">
          <option value="13">صورت سود و زیان تلفیقی</option>
          <option value="14">صورت وضعیت مالی تلفیقی</option>
          <option value="1">صورت سود و زیان</option>
          <option value="0">صورت وضعیت مالی</option>
          <option value="9">صورت جریان های نقدی</option>
        </select></body></html>
        """
        self.assertEqual(_discover_primary_sheet_ids(page), [1, 0, 9])

    def test_dual_panel_insurance_balance_sheet_keeps_both_halves(self):
        cells = [
            cell("A1", 1, "دارایی‌ها"), cell("B1", 2, "پایان عملکرد 1404/12/29"),
            cell("C1", 3, "1403/12/30"), cell("D1", 4, "درصد تغییر"),
            cell("E1", 5, "بدهی‌ها و حقوق مالکانه"), cell("F1", 6, "پایان عملکرد 1404/12/29"),
            cell("G1", 7, "1403/12/30"), cell("H1", 8, "درصد تغییر"),
            cell("A2", 1, "جمع دارایی‌ها"), cell("B2", 2, "1000"),
            cell("C2", 3, "800"), cell("D2", 4, "25"),
            cell("E2", 5, "جمع بدهی‌ها"), cell("F2", 6, "400"),
            cell("G2", 7, "300"), cell("H2", 8, "33"),
            cell("A3", 1, "موجودی نقد"), cell("B3", 2, "100"),
            cell("C3", 3, "90"), cell("D3", 4, "11"),
            cell("E3", 5, "جمع حقوق مالکانه"), cell("F3", 6, "600"),
            cell("G3", 7, "500"), cell("H3", 8, "20"),
        ]

        parsed = parse_financial_report(datasource(cells))
        rows = parsed["sheets"][0]["tables"][0]["rows"]
        by_concept = {row["concept"]: row for row in rows}

        self.assertEqual(by_concept["جمع دارایی‌ها"]["period_value"], 1000)
        self.assertEqual(by_concept["جمع بدهی‌ها"]["period_value"], 400)
        self.assertEqual(by_concept["جمع حقوق مالکانه"]["year_value"], 500)
        self.assertEqual({row["panel"] for row in rows}, {0, 1})
        self.assertTrue(by_concept["دارایی‌ها"]["is_header"])
        self.assertIsNone(by_concept["دارایی‌ها"]["period_value"])

    def test_insurance_income_uses_populated_comparison_not_zero_placeholder(self):
        cells = [
            cell("A1", 1, "شرح"), cell("B1", 2, "دوره جاری"),
            cell("C1", 3, "دوره مشابه"), cell("E1", 4, "درصد تغییر"),
            cell("D1", 5, "سال مالی قبل"), cell("F1", 6, ""),
            cell("A2", 1, "درآمدهای بیمه ای"), cell("B2", 2, "500"),
            cell("C2", 3, "0"), cell("E2", 4, "-Infinity"),
            cell("D2", 5, "400"), cell("F2", 6, "25"),
            cell("A3", 1, "سود (زیان) خالص"), cell("B3", 2, "100"),
            cell("C3", 3, "0"), cell("E3", 4, "-Infinity"),
            cell("D3", 5, "80"), cell("F3", 6, "25"),
        ]

        parsed = parse_financial_report(datasource(cells, code=1, title="صورت سود و زیان"))
        rows = parsed["sheets"][0]["tables"][0]["rows"]
        revenue = next(row for row in rows if row["concept"] == "درآمدهای بیمه ای")
        heading = next(row for row in rows if row["concept"] == "شرح")

        self.assertEqual(revenue["period_value"], 500)
        self.assertEqual(revenue["year_value"], 400)
        self.assertTrue(heading["is_header"])
        self.assertIsNone(heading["year_value"])

    def test_address_only_legacy_table_is_supported(self):
        cells = [
            {"address": "A1", "value": "شرح"},
            {"address": "B1", "value": "دوره جاری"},
            {"address": "C1", "value": "سال قبل"},
            {"address": "A2", "value": "فروش خالص"},
            {"address": "B2", "periodEndToDate": "120", "value": "120"},
            {"address": "C2", "yearEndToDate": "100", "value": "100"},
            {"address": "A3", "value": "سود خالص"},
            {"address": "B3", "periodEndToDate": "30", "value": "30"},
            {"address": "C3", "yearEndToDate": "20", "value": "20"},
        ]
        parsed = parse_financial_report(datasource(cells, code=1, title="صورت سود و زیان"))
        rows = parsed["sheets"][0]["tables"][0]["rows"]
        revenue = next(row for row in rows if row["concept"] == "فروش خالص")
        self.assertEqual((revenue["period_value"], revenue["year_value"]), (120, 100))

    def test_real_zero_is_data_not_missing_or_header(self):
        cells = [
            cell("A1", 1, "شرح"), cell("B1", 2, "جاری"), cell("C1", 3, "قبل"),
            cell("A2", 1, "تسهیلات مالی"), cell("B2", 2, "0"), cell("C2", 3, "0"),
            cell("A3", 1, "سایر بدهی‌ها"), cell("B3", 2, "10"), cell("C3", 3, "5"),
        ]
        parsed = parse_financial_report(datasource(cells))
        row = next(row for row in parsed["sheets"][0]["tables"][0]["rows"] if row["concept"] == "تسهیلات مالی")
        self.assertFalse(row["is_header"])
        self.assertEqual((row["period_value"], row["year_value"]), (0, 0))


class RatioTests(SimpleTestCase):
    def test_exact_grand_total_beats_earlier_noncurrent_subtotal(self):
        sheet = {"tables": [{"rows": [
            {"concept": "جمع دارایی‌های غیرجاری", "period_value": 200, "is_header": False},
            {"concept": "جمع دارایی‌ها", "period_value": 1000, "is_header": False},
            {"concept": "جمع بدهی‌های غیرجاری", "period_value": 50, "is_header": False},
            {"concept": "جمع بدهی‌ها", "period_value": 400, "is_header": False},
        ]}]}
        self.assertEqual(_find_value_in_sheet(sheet, "total_assets"), 1000)
        self.assertEqual(_find_value_in_sheet(sheet, "total_liabilities"), 400)

    def test_negative_expense_is_added_not_subtracted_twice(self):
        self.assertEqual(_profit_after_expense(1000, -700), 300)
        self.assertEqual(_profit_after_expense(1000, 700), 300)

    def test_official_codal_operating_cashflow_caption_is_matched(self):
        sheet = {"tables": [{"rows": [{
            "concept": "جریان خالص ورود (خروج) نقد حاصل از فعالیت‌های عملیاتی",
            "period_value": 1555190,
            "year_value": 1769198,
            "is_header": False,
        }]}]}
        self.assertEqual(
            _find_value_in_sheet(sheet, "operating_cashflow"),
            1555190,
        )

    def test_insurance_ratios_are_exposed_for_dashboard(self):
        parsed = {"sheets": [
            {"category": "income", "tables": [{"rows": [
                {"concept": "درآمدهای بیمه ای", "period_value": 500, "year_value": 400},
                {"concept": "حق بیمه خالص (سهم نگهداری)", "period_value": 450, "year_value": 360},
                {"concept": "خسارت و مزایای پرداختی خالص", "period_value": -270, "year_value": -180},
                {"concept": "درآمد سرمایه گذاری از محل منابع بیمه ای", "period_value": 50, "year_value": 40},
                {"concept": "سود خالص", "period_value": 100, "year_value": 80},
            ]}]},
            {"category": "balance", "tables": [{"rows": [
                {"concept": "جمع دارایی ها", "period_value": 1000, "year_value": 800},
                {"concept": "جمع بدهی ها", "period_value": 400, "year_value": 300},
                {"concept": "جمع حقوق مالکانه", "period_value": 600, "year_value": 500},
            ]}]},
        ]}
        ratios = calculate_financial_ratios(parsed)
        self.assertEqual(parsed["analysis_profile"], "insurance")
        self.assertAlmostEqual(ratios["debt_to_assets"]["period"], 0.4)
        self.assertAlmostEqual(ratios["net_claims_paid_ratio"]["period"], 0.6)
        self.assertAlmostEqual(ratios["roe"]["period"], 100 / 550)
        self.assertAlmostEqual(ratios["roa"]["period"], 100 / 900)
        self.assertTrue(ratios["net_claims_paid_ratio"]["available"])
        self.assertEqual(ratios["net_claims_paid_ratio"]["category"], "insurance")
        self.assertFalse(ratios["gross_margin"]["applicable"])
        self.assertEqual(
            format_ratio_field(ratios["gross_margin"], "period"),
            "نامرتبط با صنعت بیمه",
        )
        self.assertEqual(
            format_ratio_field(ratios["cashflow_quality"], "period"),
            "داده ارائه نشده",
        )

    def test_roe_is_not_reported_when_equity_crosses_zero(self):
        parsed = {"sheets": [
            {"category": "income", "tables": [{"rows": [
                {"concept": "فروش", "period_value": 500, "year_value": 400},
                {"concept": "سود خالص", "period_value": 100, "year_value": -20},
            ]}]},
            {"category": "balance", "tables": [{"rows": [
                {"concept": "جمع دارایی ها", "period_value": 1000, "year_value": 900},
                {"concept": "جمع بدهی ها", "period_value": 800, "year_value": 950},
                {"concept": "جمع حقوق مالکانه", "period_value": 200, "year_value": -50},
            ]}]},
        ]}
        ratios = calculate_financial_ratios(parsed)
        self.assertIsNone(ratios["roe"]["period"])
        self.assertIsNone(ratios["roe"]["year"])
        self.assertIsNone(ratios["debt_to_equity"]["year"])
