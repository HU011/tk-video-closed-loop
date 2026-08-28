from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.paths import ROOT_DIR
from media import ffmpeg_tools


class FFmpegToolsTests(unittest.TestCase):
    def test_split_video_transcodes_seedance_reference_segments_to_720p_portrait(self):
        runtime_dir = ROOT_DIR / "runtime"
        runtime_dir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime_dir) as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            output_dir = Path(temp_dir) / "segments"
            with patch.object(ffmpeg_tools, "probe_duration", return_value=16), patch.object(ffmpeg_tools, "_run") as run:
                segments = ffmpeg_tools.split_video(source, output_dir, max_duration=60, segment_seconds=15)

        self.assertEqual(len(segments), 2)
        first_args = run.call_args_list[0].args[0]
        self.assertIn("-vf", first_args)
        self.assertIn(ffmpeg_tools.SEEDANCE_REFERENCE_VIDEO_FILTER, first_args)


if __name__ == "__main__":
    unittest.main()
