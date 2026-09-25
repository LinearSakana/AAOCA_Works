"""Tests for platform-neutral JSON configuration path handling."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aaoca_pipeline.__main__ import _resolve_config_path


class ConfigPathTests(unittest.TestCase):
    def test_environment_path_is_expanded_relative_to_neither_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            config_dir = Path(directory) / "config"
            external_root = Path(directory) / "external-pdfs"
            with patch.dict(os.environ, {"AAOCA_PDF_ROOT": str(external_root)}):
                resolved = _resolve_config_path("${AAOCA_PDF_ROOT}", config_dir)
            self.assertEqual(Path(resolved), external_root.resolve())

    def test_relative_path_is_based_at_config_directory(self):
        config_dir = Path("/tmp/aaoaca-config")
        self.assertEqual(
            Path(_resolve_config_path("../data/sample_raw", config_dir)),
            (config_dir / "../data/sample_raw").resolve(),
        )

if __name__ == "__main__":
    unittest.main()
