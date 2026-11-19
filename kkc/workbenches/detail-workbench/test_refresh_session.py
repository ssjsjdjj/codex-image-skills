"""Refresh protocol tests use plain Python objects; no Tk or Photoshop."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import refresh_session as session


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class RefreshSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.root = self.folder / "sessions"
        self.patcher = patch.object(session, "SESSIONS_ROOT", self.root)
        self.patcher.start()
        self.package_root = self.folder / "package"
        self.package_root.mkdir()
        self.image = self.package_root / "scene.jpg"
        self.image.write_bytes(b"original image bytes")
        self.stamp = [self.image.stat().st_size, self.image.stat().st_mtime_ns]
        self.data = {"info": {"名称": "尚未保存的名称", "货号": "KQ_TEST", "材质": "原值/50.5%"},
                     "colors": ["蓝色", "缺图色"],
                     "size_table": {"headers": ["尺码", "衣长"], "rows": [["100", "41.5"]]},
                     "quick_size": {"axis_label": "身高/体重", "columns": ["12--15"], "rows": ["90-100"], "data": [["/"]]},
                     "assets": {"products": {"缺图色": "missing.png"}, "scenes": ["scene.jpg"]}}
        self.calls = []
        self.workbench = SimpleNamespace(
            source="飞书第35行 · 当前草稿", source_json=self.package_root / "product_data.json",
            package_root=self.package_root, package=SimpleNamespace(origin=self.folder / "原资料.zip"),
            products={"蓝色": self.image, "缺图色": None, "旧色": self.package_root / "old.png"},
            scenes=[self.image, None, None, None], extra_images={"hero": None, "brand": None},
            views={"builtin": {"scene_1": {"source": self.image, "source_stamp": self.stamp,
                                           "source_sha256": "old-portable-hash", "zoom": .5, "focus": [.2, .7]}}},
            template=SimpleNamespace(id="builtin"), unsaved=True,
            output=Value(self.folder / "交付"), tabs=SimpleNamespace(select=lambda: "images", index=lambda _: 1),
            preview=SimpleNamespace(mode="original", canvas=SimpleNamespace(yview=lambda: (.42, .8))),
            selected_slot=lambda: ("scene", 0), result=(self.folder / "a.psb", self.folder / "record.json", self.folder / "preview.jpg"),
            attachments=[{"name": "尺码表.png", "field": "尺码表"}], rename_origins={"蓝色": "原蓝色"},
            current_data=lambda: self.data, finish_cell=lambda commit: self.calls.append(("finish", commit)),
            flush_pending_sync=lambda: self.calls.append(("flush",)),
        )

    def tearDown(self):
        self.patcher.stop()
        self.temporary.cleanup()

    def test_snapshot_preserves_draft_and_absolute_references_without_copying_images(self):
        before = copy.deepcopy(self.data)
        path = session.save_refresh_session(self.workbench)
        product, metadata = session.read_refresh_session(path)
        data = json.loads(product.read_text(encoding="utf-8"))
        self.assertEqual(self.calls, [("finish", True), ("flush",)])
        self.assertEqual(self.data, before)
        self.assertTrue(self.workbench.unsaved)
        self.assertEqual(data["info"]["名称"], "尚未保存的名称")
        self.assertEqual(data["assets"]["products"]["蓝色"], str(self.image.resolve()))
        self.assertEqual(data["assets"]["products"]["缺图色"], str((self.package_root / "missing.png").resolve()))
        self.assertEqual(data["selected_template"], "builtin")
        view = data["views"]["builtin"]["scene_1"]
        self.assertEqual(view["source_stamp"], self.stamp)
        self.assertEqual(view["zoom"], .5)
        self.assertNotIn("source_sha256", view)
        self.assertEqual(metadata["selected_slot"], ["scene", 0])
        self.assertEqual(metadata["preview_scroll"], .42)
        self.assertEqual(metadata["preview_mode"], "original")
        self.assertEqual(metadata["tab"], 1)
        self.assertTrue(metadata["unsaved"])
        self.assertEqual(metadata["origin"], str((self.folder / "原资料.zip").resolve()))
        self.assertIn("旧色", metadata["bindings"]["products"])
        self.assertEqual({p.name for p in path.parent.iterdir()}, {"session.json", "product_data.json"})
        self.assertEqual(self.image.read_bytes(), b"original image bytes")

    def test_changed_source_cannot_be_blessed_as_a_current_crop(self):
        stale = [1, 2]
        self.workbench.views["builtin"]["scene_1"]["source_stamp"] = stale
        path = session.save_refresh_session(self.workbench)
        product, _ = session.read_refresh_session(path)
        state = json.loads(product.read_text(encoding="utf-8"))["views"]["builtin"]["scene_1"]
        self.assertEqual(state["source_stamp"], stale)
        self.assertEqual(state["snapshot_source_stamp"], self.stamp)

    def test_empty_window_can_refresh_without_inventing_a_product(self):
        self.workbench.source = ""
        self.workbench.unsaved = False
        path = session.save_refresh_session(self.workbench)
        product, metadata = session.read_refresh_session(path)
        self.assertIsNone(product)
        self.assertEqual(metadata["selected_template"], "builtin")
        self.assertEqual([p.name for p in path.parent.iterdir()], ["session.json"])

    def test_ready_marker_is_written_only_on_explicit_child_commit(self):
        path = session.save_refresh_session(self.workbench)
        marker = session.session_ready_path(path)
        self.assertFalse(marker.exists())
        self.assertEqual(session.mark_refresh_session_ready(path), marker)
        ready = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(ready["session_id"], path.parent.name)
        self.assertTrue(path.is_file())

    def test_outside_paths_and_traversing_product_reference_are_rejected(self):
        with self.assertRaises(session.RefreshSessionError):
            session.read_refresh_session(self.folder / "session.json")
        with self.assertRaises(session.RefreshSessionError):
            session.session_ready_path(self.folder / "session.json")
        path = session.save_refresh_session(self.workbench)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["product_data"] = "../../other.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(session.RefreshSessionError):
            session.read_refresh_session(path)
        self.assertFalse(session.session_ready_path(path).exists())

    def test_corrupt_product_does_not_mark_ready_or_remove_snapshot(self):
        path = session.save_refresh_session(self.workbench)
        product = path.parent / "product_data.json"
        product.write_text('{"info": {}}', encoding="utf-8")
        with self.assertRaises(session.RefreshSessionError):
            session.mark_refresh_session_ready(path)
        self.assertFalse(session.session_ready_path(path).exists())
        self.assertTrue(path.exists())
        self.assertTrue(product.exists())

    def test_existing_product_loader_can_restore_the_snapshot(self):
        from package_io import load_package

        path = session.save_refresh_session(self.workbench)
        product, _ = session.read_refresh_session(path)
        package = load_package(product, cache_root=self.folder / "unused-cache")
        self.assertEqual(package.selected_template, "builtin")
        self.assertEqual(package.products["蓝色"], self.image.resolve())
        self.assertEqual(package.views["builtin"]["scene_1"]["zoom"], .5)
        self.assertEqual(package.data["quick_size"]["data"], [["/"]])
        self.assertEqual(package.data["size_table"]["rows"], [["100", "41.5"]])
        self.assertTrue(package.missing)


if __name__ == "__main__":
    unittest.main()
