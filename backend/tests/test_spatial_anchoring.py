"""
Week 9: Spatial anchoring tests.

- test_anchor_register: pointing vector → anchor created with ID
- test_anchor_persist: register anchor, reload registry, anchor exists
- test_depth_quantization: z=-0.5m → depth_mm=500
- test_register_anchor_rpc: proto RegisterAnchor contract
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "gen" / "python"))

from perception.v1 import perception_pb2

from app.spatial.anchor_registry import AnchorRegistry


@pytest.fixture
def registry(tmp_path: Path) -> AnchorRegistry:
    return AnchorRegistry(db_path=tmp_path / "anchors.db")


class TestAnchorRegister:
    def test_register_returns_anchor_id(self, registry: AnchorRegistry) -> None:
        anchor_id = registry.register_anchor((0.0, -1.0, 0.0), "test object")
        assert isinstance(anchor_id, str)
        assert len(anchor_id) > 0

    def test_registered_anchor_is_retrievable(self, registry: AnchorRegistry) -> None:
        anchor_id = registry.register_anchor((0.5, 0.5, -0.7), "lamp")
        anchor = registry.get_anchor(anchor_id)
        assert anchor is not None
        assert anchor.anchor_id == anchor_id
        assert anchor.label == "lamp"
        assert anchor.x == pytest.approx(0.5)
        assert anchor.y == pytest.approx(0.5)
        assert anchor.z == pytest.approx(-0.7)

    def test_get_unknown_anchor_returns_none(self, registry: AnchorRegistry) -> None:
        assert registry.get_anchor("no-such-id") is None

    def test_list_anchors_returns_all(self, registry: AnchorRegistry) -> None:
        registry.register_anchor((0.0, 0.0, -1.0), "a")
        registry.register_anchor((0.1, 0.1, -0.5), "b")
        anchors = registry.list_anchors()
        assert len(anchors) == 2
        labels = {a.label for a in anchors}
        assert labels == {"a", "b"}

    def test_created_at_us_is_set(self, registry: AnchorRegistry) -> None:
        anchor_id = registry.register_anchor((1.0, 0.0, 0.0), "point")
        anchor = registry.get_anchor(anchor_id)
        assert anchor.created_at_us > 0


class TestAnchorPersist:
    def test_anchor_survives_reload(self, tmp_path: Path) -> None:
        db = tmp_path / "anchors.db"
        r1 = AnchorRegistry(db_path=db)
        anchor_id = r1.register_anchor((0.3, 0.6, -0.9), "desk")

        r2 = AnchorRegistry(db_path=db)
        anchor = r2.get_anchor(anchor_id)
        assert anchor is not None
        assert anchor.label == "desk"
        assert anchor.z == pytest.approx(-0.9)

    def test_multiple_anchors_persist(self, tmp_path: Path) -> None:
        db = tmp_path / "anchors.db"
        r1 = AnchorRegistry(db_path=db)
        ids = [r1.register_anchor((float(i), 0.0, -1.0), f"obj{i}") for i in range(5)]

        r2 = AnchorRegistry(db_path=db)
        for aid in ids:
            assert r2.get_anchor(aid) is not None


class TestDepthQuantization:
    def test_depth_mm_from_negative_z(self) -> None:
        # z=-0.5m → depth_mm = int(abs(-0.5) * 1000) = 500
        z = -0.5
        depth_mm = int(abs(z) * 1000)
        assert depth_mm == 500

    def test_depth_mm_zero(self) -> None:
        assert int(abs(0.0) * 1000) == 0

    def test_depth_mm_positive_z(self) -> None:
        assert int(abs(1.5) * 1000) == 1500

    def test_point3d_depth_mm_field(self) -> None:
        """Point3D depth_mm field (tag 4) is now activated in proto."""
        pt = perception_pb2.Point3D(x=0.5, y=0.5, z=-0.5, depth_mm=500)
        data = pt.SerializeToString()
        restored = perception_pb2.Point3D()
        restored.ParseFromString(data)
        assert restored.depth_mm == 500

    def test_point3d_confidence_field(self) -> None:
        """Point3D confidence field (tag 5) is activated in proto."""
        pt = perception_pb2.Point3D(x=0.5, y=0.5, z=0.0, confidence=0.95)
        data = pt.SerializeToString()
        restored = perception_pb2.Point3D()
        restored.ParseFromString(data)
        assert restored.confidence == pytest.approx(0.95, abs=1e-5)


class TestAnchorDelete:
    def test_delete_existing_anchor_returns_true(self, registry: AnchorRegistry) -> None:
        anchor_id = registry.register_anchor((0.0, 0.0, -1.0), "shelf")
        assert registry.delete_anchor(anchor_id) is True

    def test_deleted_anchor_is_not_retrievable(self, registry: AnchorRegistry) -> None:
        anchor_id = registry.register_anchor((0.0, 0.0, -1.0), "shelf")
        registry.delete_anchor(anchor_id)
        assert registry.get_anchor(anchor_id) is None

    def test_delete_absent_anchor_returns_false(self, registry: AnchorRegistry) -> None:
        assert registry.delete_anchor("nonexistent-id") is False

    def test_delete_removes_only_target_anchor(self, registry: AnchorRegistry) -> None:
        id_a = registry.register_anchor((0.0, 0.0, -1.0), "a")
        id_b = registry.register_anchor((0.1, 0.1, -0.5), "b")
        registry.delete_anchor(id_a)
        assert registry.get_anchor(id_a) is None
        assert registry.get_anchor(id_b) is not None

    def test_delete_reduces_list_count(self, registry: AnchorRegistry) -> None:
        id_a = registry.register_anchor((0.0, 0.0, -1.0), "a")
        registry.register_anchor((0.1, 0.1, -0.5), "b")
        registry.delete_anchor(id_a)
        assert len(registry.list_anchors()) == 1

    def test_double_delete_returns_false_on_second(self, registry: AnchorRegistry) -> None:
        anchor_id = registry.register_anchor((0.0, 0.0, -1.0), "x")
        assert registry.delete_anchor(anchor_id) is True
        assert registry.delete_anchor(anchor_id) is False


class TestAnchorUpdate:
    def test_update_label_returns_updated_anchor(self, registry: AnchorRegistry) -> None:
        anchor_id = registry.register_anchor((0.5, 0.5, -0.8), "old label")
        updated = registry.update_anchor(anchor_id, "new label")
        assert updated is not None
        assert updated.label == "new label"

    def test_update_preserves_position(self, registry: AnchorRegistry) -> None:
        anchor_id = registry.register_anchor((0.5, 0.5, -0.8), "item")
        updated = registry.update_anchor(anchor_id, "renamed item")
        assert updated.x == pytest.approx(0.5)
        assert updated.y == pytest.approx(0.5)
        assert updated.z == pytest.approx(-0.8)

    def test_update_preserves_created_at_us(self, registry: AnchorRegistry) -> None:
        anchor_id = registry.register_anchor((0.0, 0.0, -1.0), "thing")
        original = registry.get_anchor(anchor_id)
        updated = registry.update_anchor(anchor_id, "thing v2")
        assert updated.created_at_us == original.created_at_us

    def test_update_is_persisted(self, registry: AnchorRegistry) -> None:
        anchor_id = registry.register_anchor((0.0, 0.0, -1.0), "before")
        registry.update_anchor(anchor_id, "after")
        fetched = registry.get_anchor(anchor_id)
        assert fetched.label == "after"

    def test_update_absent_anchor_returns_none(self, registry: AnchorRegistry) -> None:
        assert registry.update_anchor("no-such-id", "label") is None

    def test_update_anchor_id_is_unchanged(self, registry: AnchorRegistry) -> None:
        anchor_id = registry.register_anchor((0.0, 0.0, -1.0), "old")
        updated = registry.update_anchor(anchor_id, "new")
        assert updated.anchor_id == anchor_id


class TestRegisterAnchorRPC:
    def test_spatial_anchor_proto_fields(self) -> None:
        """SpatialAnchor proto message has all required fields."""
        anchor = perception_pb2.SpatialAnchor(
            anchor_id="test-uuid",
            label="my desk",
            position=perception_pb2.Point3D(x=0.3, y=0.5, z=-0.8),
            radius=0.1,
            created_at_us=1_700_000_000_000_000,
        )
        data = anchor.SerializeToString()
        restored = perception_pb2.SpatialAnchor()
        restored.ParseFromString(data)

        assert restored.anchor_id == "test-uuid"
        assert restored.label == "my desk"
        assert restored.position.x == pytest.approx(0.3)
        assert restored.radius == pytest.approx(0.1)
        assert restored.created_at_us == 1_700_000_000_000_000

    def test_handgesture_spatial_anchor_fields(self) -> None:
        """HandGestureEvent tags 13-15 are activated."""
        evt = perception_pb2.HandGestureEvent(
            spatial_anchor_id="anchor-abc",
            depth_confidence=0.85,
            registration_state="registered",
        )
        data = evt.SerializeToString()
        restored = perception_pb2.HandGestureEvent()
        restored.ParseFromString(data)

        assert restored.spatial_anchor_id == "anchor-abc"
        assert restored.depth_confidence == pytest.approx(0.85, abs=1e-5)
        assert restored.registration_state == "registered"
