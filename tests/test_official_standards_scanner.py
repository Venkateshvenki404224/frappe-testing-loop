import tempfile
import unittest
from pathlib import Path

from frappe_testing_loop.scanners import scan_official_standards


class OfficialStandardsScannerTests(unittest.TestCase):
    def scan_text(self, text: str):
        with tempfile.TemporaryDirectory() as tmp:
            app_path = Path(tmp) / "sample_app"
            app_path.mkdir()
            (app_path / "api.py").write_text(text)
            return scan_official_standards(app_path)

    def test_whitelisted_methods_need_type_hints_and_explicit_http_methods(self):
        findings = self.scan_text(
            "import frappe\n\n"
            "@frappe.whitelist()\n"
            "def create_expense(title, amount):\n"
            "    return {}\n"
        )

        messages = "\n".join(f.message for f in findings)
        self.assertIn("Whitelisted method parameter 'title' should have a type hint", messages)
        self.assertIn("Whitelisted method parameter 'amount' should have a type hint", messages)
        self.assertIn("Whitelisted method should declare allowed HTTP methods", messages)

    def test_typed_whitelisted_methods_with_methods_are_clean(self):
        findings = self.scan_text(
            "import frappe\n\n"
            "@frappe.whitelist(methods=['POST'])\n"
            "def create_expense(title: str, amount: float, tags: list | None = None) -> dict:\n"
            "    return {}\n"
        )

        self.assertEqual(findings, [])

    def test_mutable_default_arguments_are_flagged(self):
        findings = self.scan_text(
            "def collect(items=[]):\n"
            "    return items\n\n"
            "def merge(options={}):\n"
            "    return options\n"
        )

        messages = "\n".join(f.message for f in findings)
        self.assertIn("Mutable default argument", messages)
        self.assertEqual(len([f for f in findings if "Mutable default" in f.message]), 2)

    def test_string_formatted_sql_is_high_severity(self):
        findings = self.scan_text(
            "import frappe\n\n"
            "def bad(name):\n"
            "    return frappe.db.sql(f\"select * from `tabUser` where name='{name}'\")\n"
        )

        sql_findings = [f for f in findings if "SQL" in f.message]
        self.assertTrue(sql_findings)
        self.assertEqual(sql_findings[0].severity, "high")

    def test_db_calls_inside_loops_are_flagged(self):
        findings = self.scan_text(
            "import frappe\n\n"
            "def enrich(rows):\n"
            "    for row in rows:\n"
            "        row.label = frappe.db.get_value('Customer', row.customer, 'customer_name')\n"
            "    return rows\n"
        )

        self.assertTrue(any("DB call inside loop" in f.message for f in findings))


if __name__ == "__main__":
    unittest.main()
