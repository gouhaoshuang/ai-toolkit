import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('audit',Path(__file__).with_name('audit_latex_tables.py'))
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class TableAuditTests(unittest.TestCase):
    def test_commented_old_result_is_not_reported_as_missing(self):
        tex='\\begin{table}\nA & 2.30 & -0.43 \\\\% & +6.03 \\\\\n\\end{table}'
        md='| A | **2.30** | -0.43 |'
        result=audit.audit(tex,md)
        self.assertTrue(result['coverage_passed'])
        self.assertEqual(result['source_decimal_values'],2)

    def test_wrong_sign_is_detected(self):
        tex='\\begin{table}\nA & -0.43 \\\\\n\\end{table}'
        self.assertFalse(audit.audit(tex,'| A | +0.43 |')['coverage_passed'])


if __name__=='__main__':unittest.main()
