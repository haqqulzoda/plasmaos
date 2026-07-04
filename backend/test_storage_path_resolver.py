"""Regression checks for persisted document storage path resolution."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.core.storage_paths import normalize_storage_path, storage_file_exists


KNOWN_481480_FILE = Path(
    "/mnt/d/projects/plasmaos/data/documents/"
    "47c6f8cc-a2d3-4686-898e-4d26a74b1d94/"
    "ff1cca8034784f21a7902ca0a3b0bea0_pdf"
)


class StoragePathResolverTests(unittest.TestCase):
    def test_windows_storage_path_normalizes_to_wsl_mount(self) -> None:
        resolved = normalize_storage_path(
            r"D:\projects\plasmaos\data\documents\tender\file.pdf"
        )

        self.assertEqual(
            resolved,
            Path("/mnt/d/projects/plasmaos/data/documents/tender/file.pdf"),
        )

    def test_empty_storage_path_is_missing(self) -> None:
        self.assertIsNone(normalize_storage_path(""))
        self.assertFalse(storage_file_exists(""))

    @unittest.skipUnless(
        KNOWN_481480_FILE.is_file(),
        "Known 481480 local storage fixture is not present",
    )
    def test_known_481480_windows_path_is_recognized_in_wsl(self) -> None:
        windows_path = str(KNOWN_481480_FILE).replace("/mnt/d/", "D:\\").replace("/", "\\")

        self.assertTrue(storage_file_exists(windows_path))


if __name__ == "__main__":
    unittest.main()
