"""
A1 同步机制的单元测试

覆盖的代码路径 (全部在 monitor_web.py):
  - full_decrypt              : 按页解密主库, 写入整库副本 ('wb' 模式)
  - decrypt_wal_full          : 按 frame 解密 WAL, 带 salt/pgno 过滤
  - should_skip_username      : 折叠伪会话过滤规则
  - load_contact_names        : 从 contact.db 加载 username → 显示名
  - load_muted_chats          : 加载免打扰群集合
  - load_gh_types             : 按 verify_flag 区分订阅号 / 服务号
  - _load_persisted_messages  : 启动时恢复 messages_log 的持久化文件

为了和底层加密解耦, 本测试通过 patch decrypt_page 为"恒等函数"来验证
循环和 bookkeeping 逻辑. 真实加密已被 monitor_web 生产路径多次验证过。

运行:
    python -m unittest tests.test_a1_sync
    python -m unittest tests.test_a1_sync.WalSaltFilterTests -v
"""
import json
import os
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch

import monitor_web as mw


PAGE_SZ = mw.PAGE_SZ
WAL_HEADER_SZ = mw.WAL_HEADER_SZ
WAL_FRAME_HEADER_SZ = mw.WAL_FRAME_HEADER_SZ


def _identity_decrypt_page(enc_key, page_data, pgno):
    """测试专用: 原样返回 page, 隔离加密细节, 只验证循环/bookkeeping"""
    return page_data


# ---------------------------------------------------------------------------
# full_decrypt: 全量重写、幂等、截断残留
# ---------------------------------------------------------------------------

class FullDecryptPageLoopTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _make_input(self, n_pages, tag='in'):
        path = os.path.join(self.tmp.name, f"{tag}.db")
        with open(path, 'wb') as f:
            for pgno in range(1, n_pages + 1):
                # 每页写 pgno 字节, 便于定位哪一页出问题
                f.write(bytes([pgno % 256]) * PAGE_SZ)
        return path

    def test_writes_exactly_N_pages(self):
        src = self._make_input(8)
        out = os.path.join(self.tmp.name, "out.db")
        with patch.object(mw, 'decrypt_page', _identity_decrypt_page):
            pages, _ = mw.full_decrypt(src, out, b'\x00' * 32)
        self.assertEqual(pages, 8)
        self.assertEqual(os.path.getsize(out), 8 * PAGE_SZ)

    def test_output_equals_input_with_identity_decrypt(self):
        src = self._make_input(5)
        out = os.path.join(self.tmp.name, "out.db")
        with patch.object(mw, 'decrypt_page', _identity_decrypt_page):
            mw.full_decrypt(src, out, b'\x00' * 32)
        with open(src, 'rb') as f:
            src_bytes = f.read()
        with open(out, 'rb') as f:
            out_bytes = f.read()
        self.assertEqual(src_bytes, out_bytes)

    def test_idempotent_second_run(self):
        src = self._make_input(3)
        out = os.path.join(self.tmp.name, "out.db")
        with patch.object(mw, 'decrypt_page', _identity_decrypt_page):
            mw.full_decrypt(src, out, b'\x00' * 32)
            with open(out, 'rb') as f:
                first = f.read()
            mw.full_decrypt(src, out, b'\x00' * 32)
            with open(out, 'rb') as f:
                second = f.read()
        self.assertEqual(first, second)

    def test_rewrite_truncates_previous_content(self):
        """'wb' 模式的关键语义: 新 A1 不能继承旧 A1 尾部字节"""
        big = self._make_input(5, tag='big')
        small = self._make_input(2, tag='small')
        out = os.path.join(self.tmp.name, "out.db")
        with patch.object(mw, 'decrypt_page', _identity_decrypt_page):
            mw.full_decrypt(big, out, b'\x00' * 32)
            self.assertEqual(os.path.getsize(out), 5 * PAGE_SZ)
            mw.full_decrypt(small, out, b'\x00' * 32)
        # 新副本必须严格等于小输入的大小, 没有残留
        self.assertEqual(os.path.getsize(out), 2 * PAGE_SZ)

    def test_empty_input_produces_empty_output(self):
        src = os.path.join(self.tmp.name, "empty.db")
        open(src, 'wb').close()
        out = os.path.join(self.tmp.name, "out.db")
        with patch.object(mw, 'decrypt_page', _identity_decrypt_page):
            pages, _ = mw.full_decrypt(src, out, b'\x00' * 32)
        self.assertEqual(pages, 0)
        self.assertEqual(os.path.getsize(out), 0)


# ---------------------------------------------------------------------------
# decrypt_wal_full: salt 过滤 / 非法 pgno 过滤 / 多 frame 应用
# ---------------------------------------------------------------------------

def _build_fake_wal(salt1, salt2, frames):
    """
    frames: [(pgno, frame_salt1, frame_salt2, page_bytes), ...]
    """
    buf = bytearray(WAL_HEADER_SZ)
    struct.pack_into('>I', buf, 16, salt1)
    struct.pack_into('>I', buf, 20, salt2)
    for pgno, fs1, fs2, page in frames:
        fh = bytearray(WAL_FRAME_HEADER_SZ)
        struct.pack_into('>I', fh, 0, pgno)
        struct.pack_into('>I', fh, 8, fs1)
        struct.pack_into('>I', fh, 12, fs2)
        buf.extend(fh)
        buf.extend(page)
    return bytes(buf)


class WalSaltFilterTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _make_main_db(self, n_pages=4, fill=0x00):
        path = os.path.join(self.tmp.name, "main.db")
        with open(path, 'wb') as f:
            f.write(bytes([fill]) * (PAGE_SZ * n_pages))
        return path

    def _write_wal(self, main_path, salt1, salt2, frames):
        wal_bytes = _build_fake_wal(salt1, salt2, frames)
        wal_path = main_path + "-wal"
        with open(wal_path, 'wb') as f:
            f.write(wal_bytes)
        return wal_path

    def test_stale_frame_does_not_overwrite_valid_frame(self):
        """同一页同时有 valid + stale 两个 frame, stale 必须被跳过"""
        main = self._make_main_db(n_pages=4)
        valid = (2, 0xAA, 0xBB, bytes([0x11]) * PAGE_SZ)
        stale = (2, 0x99, 0x88, bytes([0xFF]) * PAGE_SZ)
        wal = self._write_wal(main, 0xAA, 0xBB, [valid, stale])

        with patch.object(mw, 'decrypt_page', _identity_decrypt_page):
            patched, _ = mw.decrypt_wal_full(wal, main, b'\x00' * 32)

        self.assertEqual(patched, 1)
        with open(main, 'rb') as f:
            f.seek(PAGE_SZ)  # page 2 在 offset 4096
            page2 = f.read(PAGE_SZ)
        self.assertEqual(page2, bytes([0x11]) * PAGE_SZ)

    def test_stale_first_then_valid_same_page(self):
        """顺序颠倒: stale 在前, valid 在后, 最终 A1 里应当是 valid 的值"""
        main = self._make_main_db(n_pages=4)
        stale = (3, 0x99, 0x88, bytes([0xFF]) * PAGE_SZ)
        valid = (3, 0xAA, 0xBB, bytes([0x22]) * PAGE_SZ)
        wal = self._write_wal(main, 0xAA, 0xBB, [stale, valid])

        with patch.object(mw, 'decrypt_page', _identity_decrypt_page):
            patched, _ = mw.decrypt_wal_full(wal, main, b'\x00' * 32)

        self.assertEqual(patched, 1)
        with open(main, 'rb') as f:
            f.seek(2 * PAGE_SZ)
            page3 = f.read(PAGE_SZ)
        self.assertEqual(page3, bytes([0x22]) * PAGE_SZ)

    def test_pgno_zero_skipped(self):
        main = self._make_main_db()
        wal = self._write_wal(
            main, 0xAA, 0xBB,
            [(0, 0xAA, 0xBB, bytes([0x11]) * PAGE_SZ)],
        )
        with patch.object(mw, 'decrypt_page', _identity_decrypt_page):
            patched, _ = mw.decrypt_wal_full(wal, main, b'\x00' * 32)
        self.assertEqual(patched, 0)

    def test_pgno_too_large_skipped(self):
        main = self._make_main_db()
        wal = self._write_wal(
            main, 0xAA, 0xBB,
            [(2_000_001, 0xAA, 0xBB, bytes([0x11]) * PAGE_SZ)],
        )
        with patch.object(mw, 'decrypt_page', _identity_decrypt_page):
            patched, _ = mw.decrypt_wal_full(wal, main, b'\x00' * 32)
        self.assertEqual(patched, 0)

    def test_multiple_valid_frames_all_applied_correctly(self):
        """三个不相邻的 valid frame 都应 apply 到正确的页偏移"""
        main = self._make_main_db(n_pages=5)
        frames = [
            (1, 0xAA, 0xBB, bytes([0xA1]) * PAGE_SZ),
            (3, 0xAA, 0xBB, bytes([0xA3]) * PAGE_SZ),
            (5, 0xAA, 0xBB, bytes([0xA5]) * PAGE_SZ),
        ]
        wal = self._write_wal(main, 0xAA, 0xBB, frames)
        with patch.object(mw, 'decrypt_page', _identity_decrypt_page):
            patched, _ = mw.decrypt_wal_full(wal, main, b'\x00' * 32)
        self.assertEqual(patched, 3)
        with open(main, 'rb') as f:
            data = f.read()
        self.assertEqual(data[0 * PAGE_SZ:1 * PAGE_SZ], bytes([0xA1]) * PAGE_SZ)
        self.assertEqual(data[1 * PAGE_SZ:2 * PAGE_SZ], b'\x00' * PAGE_SZ)  # 未被 patch
        self.assertEqual(data[2 * PAGE_SZ:3 * PAGE_SZ], bytes([0xA3]) * PAGE_SZ)
        self.assertEqual(data[3 * PAGE_SZ:4 * PAGE_SZ], b'\x00' * PAGE_SZ)
        self.assertEqual(data[4 * PAGE_SZ:5 * PAGE_SZ], bytes([0xA5]) * PAGE_SZ)

    def test_tiny_wal_returns_zero(self):
        main = self._make_main_db()
        wal = main + "-wal"
        with open(wal, 'wb') as f:
            f.write(b'\x00' * 8)  # 小于 WAL_HEADER_SZ
        patched, _ = mw.decrypt_wal_full(wal, main, b'\x00' * 32)
        self.assertEqual(patched, 0)

    def test_missing_wal_returns_zero(self):
        main = self._make_main_db()
        patched, _ = mw.decrypt_wal_full(main + "-wal", main, b'\x00' * 32)
        self.assertEqual(patched, 0)


# ---------------------------------------------------------------------------
# should_skip_username: 折叠伪会话 / 占位符
# ---------------------------------------------------------------------------

class SkipUsernameTests(unittest.TestCase):

    def test_empty_or_none_skipped(self):
        self.assertTrue(mw.should_skip_username(''))
        self.assertTrue(mw.should_skip_username(None))

    def test_brand_session_holders_skipped(self):
        self.assertTrue(mw.should_skip_username('brandsessionholder'))
        self.assertTrue(mw.should_skip_username('brandservicesessionholder'))

    def test_notification_placeholder_skipped(self):
        self.assertTrue(mw.should_skip_username('notification_messages'))
        self.assertTrue(mw.should_skip_username('notifymessage'))

    def test_placeholder_prefix_skipped(self):
        self.assertTrue(mw.should_skip_username('@placeholder_foldgroup'))
        self.assertTrue(mw.should_skip_username('@placeholder_xyz'))

    def test_real_username_not_skipped(self):
        self.assertFalse(mw.should_skip_username('wxid_alice'))
        self.assertFalse(mw.should_skip_username('1234@chatroom'))
        self.assertFalse(mw.should_skip_username('gh_be38ef7d65a4'))
        # 前缀碰巧是 'brand' 但不等于 brandsessionholder
        self.assertFalse(mw.should_skip_username('brandcowherd'))


# ---------------------------------------------------------------------------
# contact.db 加载器: 名字 / 静音群 / gh_ 类型
# ---------------------------------------------------------------------------

class ContactLoaderTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "contact.db")
        self._build_fake_contact_db(self.db_path)

    def _build_fake_contact_db(self, path):
        conn = sqlite3.connect(path)
        conn.execute("""
            CREATE TABLE contact (
                username TEXT PRIMARY KEY,
                nick_name TEXT,
                remark TEXT,
                chat_room_notify INTEGER,
                verify_flag INTEGER
            )
        """)
        rows = [
            # (username, nick, remark, chat_room_notify, verify_flag)
            ('wxid_alice',    'Alice',  'A-remark', 0, 0),
            ('wxid_bob',      'Bob',    '',         0, 0),
            ('wxid_carol',    '',       '',         0, 0),
            ('1111@chatroom', 'Group1', '',         1, 0),   # 未静音
            ('2222@chatroom', 'Group2', '',         0, 0),   # 静音
            ('gh_sub01',      'Sub1',   '',         0, 8),   # 订阅号
            ('gh_sub02',      'Sub2',   '',         0, 520), # 订阅号 (bit 4 未置)
            ('gh_svc01',      'Svc1',   '',         0, 24),  # 服务号
            ('gh_svc02',      'Svc2',   '',         0, 1048),# 服务号 (bit 4 置)
        ]
        conn.executemany(
            "INSERT INTO contact VALUES (?,?,?,?,?)", rows
        )
        conn.commit()
        conn.close()

    def test_load_contact_names_prefers_remark_then_nick(self):
        with patch.object(mw, 'CONTACT_CACHE', self.db_path):
            names = mw.load_contact_names()
        self.assertEqual(names['wxid_alice'], 'A-remark')
        self.assertEqual(names['wxid_bob'], 'Bob')
        # remark 和 nick 都空, 返回 username
        self.assertEqual(names['wxid_carol'], 'wxid_carol')
        self.assertEqual(names['1111@chatroom'], 'Group1')

    def test_load_muted_chats_only_includes_muted_chatrooms(self):
        with patch.object(mw, 'CONTACT_CACHE', self.db_path):
            muted = mw.load_muted_chats()
        self.assertIn('2222@chatroom', muted)
        self.assertNotIn('1111@chatroom', muted)     # notify=1 (正常推送)
        self.assertNotIn('wxid_alice', muted)         # 非群
        self.assertNotIn('gh_sub01', muted)           # 非群

    def test_load_gh_types_splits_sub_vs_svc_correctly(self):
        with patch.object(mw, 'CONTACT_CACHE', self.db_path):
            types = mw.load_gh_types()
        # 订阅号 (verify_flag & 24 != 24)
        self.assertEqual(types['gh_sub01'], 'sub')    # 8     = 0b01000
        self.assertEqual(types['gh_sub02'], 'sub')    # 520   = 0b1000001000
        # 服务号 (verify_flag & 24 == 24)
        self.assertEqual(types['gh_svc01'], 'svc')    # 24    = 0b11000
        self.assertEqual(types['gh_svc02'], 'svc')    # 1048  = 0b10000011000
        # 非 gh_ 的都不在结果里
        self.assertNotIn('wxid_alice', types)
        self.assertNotIn('1111@chatroom', types)

    def test_loaders_return_empty_when_contact_table_missing(self):
        """db 文件存在但没有 contact 表时, 三个 loader 都应返回空, 不抛异常"""
        empty_db = os.path.join(self.tmp.name, "empty.db")
        conn = sqlite3.connect(empty_db)
        conn.execute("CREATE TABLE unrelated (x INTEGER)")
        conn.commit()
        conn.close()
        with patch.object(mw, 'CONTACT_CACHE', empty_db):
            self.assertEqual(mw.load_contact_names(), {})
            self.assertEqual(mw.load_muted_chats(), set())
            self.assertEqual(mw.load_gh_types(), {})


# ---------------------------------------------------------------------------
# messages_log 持久化 roundtrip
# ---------------------------------------------------------------------------

class PersistenceTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log_path = os.path.join(self.tmp.name, "_messages_log.jsonl")

    def test_load_returns_empty_when_file_missing(self):
        with patch.object(mw, 'MESSAGES_LOG_FILE', self.log_path):
            self.assertEqual(mw._load_persisted_messages(), [])

    def test_load_parses_valid_and_skips_corrupt_lines(self):
        lines = [
            json.dumps({'timestamp': 100, 'chat': 'A', 'content': 'hi'}),
            'not-json',
            json.dumps({'timestamp': 200, 'chat': 'B'}),
            '',
        ]
        with open(self.log_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        with patch.object(mw, 'MESSAGES_LOG_FILE', self.log_path):
            loaded = mw._load_persisted_messages()
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]['timestamp'], 100)
        self.assertEqual(loaded[1]['chat'], 'B')

    def test_load_truncates_to_max_log(self):
        extra = 50
        with open(self.log_path, 'w', encoding='utf-8') as f:
            for i in range(mw.MAX_LOG + extra):
                f.write(json.dumps({'timestamp': i, 'chat': str(i)}) + '\n')
        with patch.object(mw, 'MESSAGES_LOG_FILE', self.log_path):
            loaded = mw._load_persisted_messages()
        self.assertEqual(len(loaded), mw.MAX_LOG)
        # 只保留最后 MAX_LOG 条
        self.assertEqual(loaded[0]['timestamp'], extra)
        self.assertEqual(loaded[-1]['timestamp'], mw.MAX_LOG + extra - 1)


if __name__ == '__main__':
    unittest.main()
