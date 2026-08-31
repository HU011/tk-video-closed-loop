import os
import tempfile
import unittest

from collection.collector import CollectionService
from collection.tiktok_oembed import row_from_oembed
from downloading.video_downloader import VideoDownloader, safe_filename


class CollectionDownloaderTests(unittest.TestCase):
    def test_row_from_oembed_extracts_creator(self):
        row = row_from_oembed(
            "https://www.tiktok.com/@demo/video/123",
            {
                "title": "demo title",
                "author_name": "Demo Creator",
                "author_url": "https://www.tiktok.com/@demo_creator",
                "thumbnail_url": "https://example.com/thumb.jpg",
            },
            account_name="shop_a",
        )
        self.assertEqual(row["account_name"], "shop_a")
        self.assertEqual(row["username"], "demo_creator")
        self.assertEqual(row["cover_path"], "https://example.com/thumb.jpg")

    def test_downloader_reports_missing_ytdlp_for_page_url(self):
        result = VideoDownloader(ytdlp_bin="definitely_missing_yt_dlp").download("https://www.tiktok.com/@demo/video/123")
        self.assertEqual(result.status, "skipped")

    def test_safe_filename(self):
        self.assertEqual(safe_filename("https://example.com/a/b/c.mp4"), "c.mp4")

    def test_collection_file_path_resolves_from_project_root(self):
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                rows = CollectionService()._extract_rows({"file_path": "examples/sample_videos.csv"})
            finally:
                os.chdir(old_cwd)
        self.assertGreater(len(rows), 0)
        self.assertIn("video_url", rows[0])


if __name__ == "__main__":
    unittest.main()
