import importlib.util
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
    spec = importlib.util.spec_from_file_location("baize_plugin_rerank", PLUGIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRerankOrder(unittest.TestCase):
    def setUp(self):
        os.environ["HERMES_HOME"] = tempfile.mkdtemp(prefix="baize_rerank_")
        self.plugin = _load_plugin()
        self.provider = self.plugin.BaiZeProvider()

    def _inject(self, results):
        self.provider._search = lambda *a, **k: results
        return self.provider._do_search("q")

    def test_rerank_score_wins_over_initial_score(self):
        results = [
            {"id": 2, "content": "BBB", "score": 0.2, "rerank_score": 0.8},
            {"id": 1, "content": "AAA", "score": 0.9, "rerank_score": 0.1},
        ]
        out = self._inject(results)
        self.assertLess(out.index("BBB"), out.index("AAA"))

    def test_server_order_preserved_when_rerank_present(self):
        results = [
            {"id": 2, "content": "BBB", "score": 0.2, "rerank_score": 0.8},
            {"id": 1, "content": "AAA", "score": 0.9, "rerank_score": 0.1},
        ]
        out = self._inject(results)
        self.assertLess(out.index("BBB"), out.index("AAA"))


if __name__ == "__main__":
    unittest.main()
