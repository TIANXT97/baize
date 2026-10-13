"""白泽 System One 双子星门控单测：覆盖主门控调用、备用门控静默降级与双机失效 Fail-open。"""

import unittest
from unittest.mock import patch, MagicMock
import json

from modules.jev_gate import JevGate


class SystemOneDualGateTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "enabled": True,
            "api_key": "mock_primary_key",
            "api_url": "https://api.mock-primary.ai/v1/systemone",
            "model": "openjev-latest",
            "threshold": 0.25,
            "search_threshold": 0.35,
            "timeout_sec": 1.5,
            "backup_gate": {
                "enabled": True,
                "api_key": "mock_backup_key",
                "api_url": "https://console.mock-backup.ai/v1/systemone",
                "model": "drex-v2.0",
                "timeout_sec": 1.5,
            },
        }

    @patch.object(JevGate, "_call_systemone_api")
    def test_primary_gate_success_filters_ephemeral(self, mock_api):
        mock_api.return_value = {
            "answers": {
                "should_memorize": {"noul": 0.01},
                "category": {"choice": "ephemeral"},
            }
        }
        gate = JevGate(self.config)
        filtered, reason = gate.should_filter("今天中午在公司食堂吃了个牛肉面")

        self.assertTrue(filtered)
        self.assertIn("openjev-latest", reason)
        mock_api.assert_called_once()
        self.assertEqual(mock_api.call_args[0][2], "openjev-latest")

    @patch.object(JevGate, "_call_systemone_api")
    def test_primary_gate_failure_fallbacks_to_backup_drex(self, mock_api):
        # 第一次调用主门控抛异常，第二次调用备用门控成功
        mock_api.side_effect = [
            RuntimeError("Primary gateway 502 Bad Gateway"),
            {
                "answers": {
                    "should_memorize": {"noul": 0.04},
                    "category": {"choice": "ephemeral"},
                }
            },
        ]
        gate = JevGate(self.config)
        filtered, reason = gate.should_filter("今天中午在公司食堂吃了个牛肉面")

        self.assertTrue(filtered)
        self.assertIn("drex-v2.0_backup", reason)
        self.assertEqual(mock_api.call_count, 2)
        # 验证第二次确实打向了 backup
        self.assertEqual(mock_api.call_args_list[1][0][2], "drex-v2.0")

    @patch.object(JevGate, "_call_systemone_api")
    def test_all_gates_failure_fails_open(self, mock_api):
        # 主备双机均宕机
        mock_api.side_effect = [
            RuntimeError("Primary timeout"),
            RuntimeError("Backup timeout"),
        ]
        gate = JevGate(self.config)
        filtered, reason = gate.should_filter("重要事实：老板的出生年份是1996年")

        # 铁律：Fail-open 放行，严禁拦截
        self.assertFalse(filtered)
        self.assertEqual(reason, "gate_all_failed_fail_open")


if __name__ == "__main__":
    unittest.main()
