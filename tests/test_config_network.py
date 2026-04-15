"""
Unit tests for config.py network helpers:
  - _fill_network_defaults (缺省补全 + 老配置向后兼容)
  - resolve_allowed_clients (IP/Domain 集合展开)
  - generate_token (长度 + 随机性)
  - save_config roundtrip (原子写入 + 字段保留)
"""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import config as cfg_mod


class FillNetworkDefaultsTests(unittest.TestCase):

    def test_missing_section_gets_full_defaults(self):
        c = {"db_dir": "x"}
        cfg_mod._fill_network_defaults(c)
        net = c["network"]
        # 所有 _DEFAULT_NETWORK 的 top-level key 都应当存在
        for k in cfg_mod._DEFAULT_NETWORK.keys():
            self.assertIn(k, net)
        self.assertFalse(net["enabled"])
        self.assertEqual(net["transport"], "sse")
        self.assertEqual(net["bind_port"], 8765)
        self.assertEqual(net["allow_clients"], [])
        self.assertEqual(net["tls"]["enabled"], False)

    def test_partial_section_preserves_user_values(self):
        c = {
            "db_dir": "x",
            "network": {
                "enabled": True,
                "bind_port": 9999,
                "allow_clients": [
                    {"label": "me", "ip": "1.1.1.1", "domain": "", "enabled": True}
                ],
            },
        }
        cfg_mod._fill_network_defaults(c)
        self.assertTrue(c["network"]["enabled"])
        self.assertEqual(c["network"]["bind_port"], 9999)
        self.assertEqual(len(c["network"]["allow_clients"]), 1)
        # 未设置的字段被补齐
        self.assertEqual(c["network"]["transport"], "sse")
        self.assertEqual(c["network"]["rate_limit_per_min"], 120)
        self.assertFalse(c["network"]["tls"]["enabled"])

    def test_malformed_section_gets_defaults(self):
        c = {"db_dir": "x", "network": "not a dict"}
        cfg_mod._fill_network_defaults(c)
        self.assertIsInstance(c["network"], dict)
        self.assertFalse(c["network"]["enabled"])

    def test_tls_subfield_fill(self):
        c = {
            "db_dir": "x",
            "network": {"tls": {"enabled": True}},
        }
        cfg_mod._fill_network_defaults(c)
        tls = c["network"]["tls"]
        self.assertTrue(tls["enabled"])
        self.assertEqual(tls["cert"], "")  # 被补齐
        self.assertEqual(tls["key"], "")


class ResolveAllowedClientsTests(unittest.TestCase):

    def test_expands_ip_and_domain(self):
        net = {
            "allow_clients": [
                {"label": "a", "ip": "1.2.3.4", "domain": "a.lan", "enabled": True},
                {"label": "b", "ip": "5.6.7.8", "domain": "B.LAN", "enabled": True},
            ]
        }
        ip_set, dom_set = cfg_mod.resolve_allowed_clients(net)
        self.assertEqual(ip_set, {"1.2.3.4", "5.6.7.8"})
        # domain 小写归一
        self.assertEqual(dom_set, {"a.lan", "b.lan"})

    def test_excludes_disabled_entries(self):
        net = {
            "allow_clients": [
                {"label": "on", "ip": "1.1.1.1", "domain": "on.lan", "enabled": True},
                {"label": "off", "ip": "2.2.2.2", "domain": "off.lan", "enabled": False},
            ]
        }
        ip_set, dom_set = cfg_mod.resolve_allowed_clients(net)
        self.assertEqual(ip_set, {"1.1.1.1"})
        self.assertEqual(dom_set, {"on.lan"})

    def test_empty_fields_ignored(self):
        net = {
            "allow_clients": [
                {"label": "a", "ip": "1.1.1.1", "domain": "", "enabled": True},
                {"label": "b", "ip": "", "domain": "only-dom.lan", "enabled": True},
            ]
        }
        ip_set, dom_set = cfg_mod.resolve_allowed_clients(net)
        self.assertEqual(ip_set, {"1.1.1.1"})
        self.assertEqual(dom_set, {"only-dom.lan"})

    def test_none_or_missing_returns_empty(self):
        self.assertEqual(cfg_mod.resolve_allowed_clients({}), (set(), set()))
        self.assertEqual(cfg_mod.resolve_allowed_clients(None), (set(), set()))
        self.assertEqual(cfg_mod.resolve_allowed_clients({"allow_clients": None}), (set(), set()))


class GenerateTokenTests(unittest.TestCase):

    def test_token_is_nonempty_string(self):
        t = cfg_mod.generate_token()
        self.assertIsInstance(t, str)
        self.assertGreater(len(t), 20)

    def test_token_is_url_safe(self):
        t = cfg_mod.generate_token()
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        self.assertTrue(all(ch in allowed for ch in t))

    def test_tokens_are_unique(self):
        tokens = {cfg_mod.generate_token() for _ in range(200)}
        self.assertEqual(len(tokens), 200)


class SaveConfigRoundtripTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "config.json")

    def test_save_then_reload_preserves_all_fields(self):
        original = {
            "db_dir": r"D:\some\dir\db_storage",
            "keys_file": "all_keys.json",
            "decrypted_dir": "decrypted",
            "wechat_process": "Weixin.exe",
            "bootstrap_hours": 72,
            "bootstrap_max_count": 300,
            "network": {
                "enabled": True,
                "transport": "sse",
                "bind_host": "0.0.0.0",
                "bind_port": 9000,
                "public_url": "http://foo.lan:9000",
                "auth_token": "opaque-xyz-token-value",
                "tls": {"enabled": False, "cert": "", "key": ""},
                "allow_clients": [
                    {"label": "pc", "ip": "10.0.0.1", "domain": "pc.lan", "enabled": True},
                ],
                "rate_limit_per_min": 240,
            },
        }
        cfg_mod.save_config(original, self.path)

        # 磁盘上是合法 JSON
        with open(self.path, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        self.assertEqual(loaded["bootstrap_hours"], 72)
        self.assertEqual(loaded["network"]["bind_port"], 9000)
        self.assertEqual(loaded["network"]["auth_token"], "opaque-xyz-token-value")
        self.assertEqual(
            loaded["network"]["allow_clients"][0]["domain"], "pc.lan"
        )

    def test_save_is_atomic_no_stale_tmp(self):
        cfg_mod.save_config({"a": 1}, self.path)
        # .json.tmp 临时文件不应留下
        files = os.listdir(self.tmp.name)
        self.assertIn("config.json", files)
        leftovers = [f for f in files if f.endswith(".tmp") or f.startswith(".config.")]
        self.assertEqual(leftovers, [])

    def test_save_then_fill_network_defaults_backfills_missing(self):
        # 模拟老格式: 无 network 段
        old = {
            "db_dir": "x",
            "keys_file": "all_keys.json",
        }
        cfg_mod.save_config(old, self.path)
        with open(self.path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertNotIn("network", loaded)  # 保存时不会自动加字段
        # load 时被 _fill_network_defaults 补上
        cfg_mod._fill_network_defaults(loaded)
        self.assertIn("network", loaded)
        self.assertFalse(loaded["network"]["enabled"])


if __name__ == "__main__":
    unittest.main()
