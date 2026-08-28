import sqlite3
import unittest

from services.importer import import_video_rows


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(
            """
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                name TEXT NOT NULL,
                handle TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(platform, name)
            );
            CREATE TABLE creators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                nickname TEXT NOT NULL DEFAULT '',
                region TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                follower_count INTEGER NOT NULL DEFAULT 0,
                sample_received_count INTEGER NOT NULL DEFAULT 0,
                posted_video_count INTEGER NOT NULL DEFAULT 0,
                order_count INTEGER NOT NULL DEFAULT 0,
                gmv REAL NOT NULL DEFAULT 0,
                free_sample_score REAL NOT NULL DEFAULT 0,
                free_sample_reasons TEXT NOT NULL DEFAULT '[]',
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sku TEXT NOT NULL DEFAULT '',
                image_path TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(name, sku)
            );
            CREATE TABLE videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                product_id INTEGER,
                platform TEXT NOT NULL,
                video_url TEXT NOT NULL,
                original_video_path TEXT NOT NULL DEFAULT '',
                cover_path TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                duration_seconds REAL NOT NULL DEFAULT 0,
                views INTEGER NOT NULL DEFAULT 0,
                likes INTEGER NOT NULL DEFAULT 0,
                comments INTEGER NOT NULL DEFAULT 0,
                shares INTEGER NOT NULL DEFAULT 0,
                orders INTEGER NOT NULL DEFAULT 0,
                gmv REAL NOT NULL DEFAULT 0,
                commission_rate REAL NOT NULL DEFAULT 0,
                hot_score REAL NOT NULL DEFAULT 0,
                hot_reason TEXT NOT NULL DEFAULT '',
                collected_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_duplicate_video_updates_existing_row(self):
        first = import_video_rows(
            self.conn,
            [
                {
                    "account_name": "shop_a",
                    "username": "demo",
                    "video_url": "https://www.tiktok.com/@demo/video/100?lang=en",
                    "title": "old",
                    "views": "100",
                }
            ],
        )
        second = import_video_rows(
            self.conn,
            [
                {
                    "account_name": "shop_a",
                    "username": "demo",
                    "video_url": "https://www.tiktok.com/@demo/video/100",
                    "title": "new",
                    "play_count": "250",
                    "like_count": "10",
                }
            ],
        )
        rows = self.conn.execute("SELECT * FROM videos").fetchall()
        self.assertEqual(first["imported"], 1)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["video_url"], "https://www.tiktok.com/@demo/video/100")
        self.assertEqual(rows[0]["title"], "new")
        self.assertEqual(rows[0]["views"], 250)
        self.assertEqual(rows[0]["likes"], 10)


if __name__ == "__main__":
    unittest.main()
