
import json
import sys
import unittest
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from binaryaudit import abicheck  # noqa: E402

data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class AbicheckTestSuite(unittest.TestCase):
    def test_is_elf(self):
        assert abicheck.is_elf("/bin/ls")

    def test_get_bits(self):
        code = 8 | 4
        a = abicheck.diff_get_bits(code)
        assert len(a) == 2
        assert "CHANGE" in a
        assert "INCOMPATIBLE_CHANGE" in a

        code = 1 | 2
        a = abicheck.diff_get_bits(code)
        assert len(a) == 2
        assert "ERROR" in a
        assert "USAGE_ERROR" in a

        code = 0
        a = abicheck.diff_get_bits(code)
        assert len(a) == 1
        assert "OK" in a

    def test_get_soname_from_xml(self):
        fn = os.path.join(data_dir, "libssl.so.xml")
        with open(fn, "rb") as fd:
            xml = fd.read()
            fd.close()
        soname = abicheck.get_soname_from_xml(xml)
        assert "libssl.so.1.1" == soname

    def test_compare_no_suppress(self):
        ref = os.path.join(data_dir, "libtest1-v0.so")
        cur = os.path.join(data_dir, "libtest1-v1.so")
        code, out, cmd = abicheck.compare(ref, cur)
        expected_out = open(os.path.join(data_dir, 'test_compare_no_suppress_expected')).read()
        assert code == 4
        assert out == expected_out

    def test_compare_with_suppress(self):
        ref = os.path.join(data_dir, "libtest1-v0.so")
        cur = os.path.join(data_dir, "libtest1-v1.so")
        sup_1 = os.path.join(data_dir, "test1-0.suppr")
        sup_2 = os.path.join(data_dir, "test1-1.suppr")
        suppr = [sup_1, sup_2]
        code, out, cmd = abicheck.compare(ref, cur, suppr)
        expected_out = open(os.path.join(data_dir, 'test_compare_with_suppress_expected')).read()
        assert code == 0
        assert out == expected_out

    def test_generate_json_packages(self):
        source_dir = os.path.join(data_dir, "generate_package_json_test")
        output_file = os.path.join(data_dir, "generate_package_json_test_out")
        abicheck.generate_package_json(source_dir, output_file)
        with open(output_file, "r") as json_file:
            data = json.load(json_file)
        assert len(data) == 1
        os.remove(output_file)
