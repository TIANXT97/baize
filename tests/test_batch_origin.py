import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBatchOrigin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="baize_origin_")
        for name in ("api_server.py", "config.json"):
            shutil.copy(os.path.join(PROJECT_ROOT, name), os.path.join(self.tmp, name))
        shutil.copytree(os.path.join(PROJECT_ROOT, "modules"), os.path.join(self.tmp, "modules"))
        self.sys_path_before = list(sys.path)
        sys.path.insert(0, self.tmp)

    def tearDown(self):
        sys.path[:] = self.sys_path_before
        for mod in [m for m in sys.modules if m == "api_server" or m.startswith("modules")]:
            del sys.modules[mod]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_mixed_batch_keeps_per_message_origin(self):
        api_server = importlib.import_module("api_server")
        calls = []

        def recorder(text, source="hermes", user_id="default", is_replay=False, msg_origin="user"):
            calls.append((text, msg_origin))
            return []

        api_server._store_extracted_facts = recorder
        messages = json.dumps([
            {"role": "user", "content": "我叫张三"},
            {"role": "assistant", "content": "推测你可能是程序员"},
            {"role": "user", "content": "我喜欢喝茶"},
        ])
        req = api_server.AddRequest(messages=messages, user_id="default", metadata={}, async_mode=False)
        api_server.add_memory(req)

        by_origin = {origin: text for text, origin in calls}
        self.assertEqual(by_origin.get("user"), "我叫张三\n我喜欢喝茶")
        self.assertEqual(by_origin.get("agent-inferred"), "推测你可能是程序员")
        for text, origin in calls:
            if "推测" in text:
                self.assertEqual(origin, "agent-inferred")


if __name__ == "__main__":
    unittest.main()
