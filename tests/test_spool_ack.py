import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_PATH = os.path.join(PROJECT_ROOT, "plugin", "baize", "__init__.py")


def _load_plugin():
    stub = types.ModuleType("agent.memory_provider")

    class MemoryProvider:
        pass

    stub.MemoryProvider = MemoryProvider
    sys.modules.setdefault("agent", types.ModuleType("agent"))
    sys.modules["agent.memory_provider"] = stub
    spec = importlib.util.spec_from_file_location("baize_plugin_under_test", PLUGIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSpoolAck(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="baize_spool_")
        os.environ["HERMES_HOME"] = self.home
        self.plugin = _load_plugin()
        self.provider = self.plugin.BaiZeProvider()
        self.provider._spool_interval = 10 ** 9
        self.spool = self.provider._spool_path

    def _write_spool(self, n):
        for i in range(n):
            self.provider._spool_write([{"role": "user", "content": f"msg{i}"}], "hermes")

    def _spool_lines(self):
        if not os.path.exists(self.spool):
            return []
        with open(self.spool, encoding="utf-8") as f:
            return [ln for ln in f if ln.strip()]

    def test_error_response_keeps_spool_record(self):
        self._write_spool(2)
        self.provider._add_memory = lambda *a, **k: {"error": "HTTP 500"}
        self.provider._flush_spool()
        self.assertEqual(len(self._spool_lines()), 2)

    def test_ack_removes_spool_record(self):
        self._write_spool(2)
        self.provider._add_memory = lambda *a, **k: {"status": "accepted"}
        self.provider._flush_spool()
        self.assertEqual(self._spool_lines(), [])

    def test_exception_keeps_spool_record(self):
        self._write_spool(1)

        def boom(*a, **k):
            raise ConnectionError("unreachable")

        self.provider._add_memory = boom
        self.provider._flush_spool()
        self.assertEqual(len(self._spool_lines()), 1)


if __name__ == "__main__":
    unittest.main()
