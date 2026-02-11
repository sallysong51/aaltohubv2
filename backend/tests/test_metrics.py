"""Tests for app.metrics — MessageMetrics class."""
import pytest
from app.metrics import MessageMetrics


def _title_fn(group_id: int) -> str:
    return f"Group {group_id}"


class TestMessageMetrics:
    def setup_method(self):
        self.metrics = MessageMetrics(_title_fn)

    def test_track_handled_increments(self):
        self.metrics.track_handled(100)
        self.metrics.track_handled(100)
        self.metrics.track_handled(200)
        assert self.metrics._messages_handled[100] == 2
        assert self.metrics._messages_handled[200] == 1

    def test_track_skipped_increments_and_tracks_reason(self):
        self.metrics.track_skipped(100, "not_assigned")
        self.metrics.track_skipped(100, "not_assigned")
        self.metrics.track_skipped(100, "not_enabled")
        assert self.metrics._messages_skipped[100] == 3
        assert self.metrics._skip_reasons[100]["not_assigned"] == 2
        assert self.metrics._skip_reasons[100]["not_enabled"] == 1

    def test_get_summary_aggregates(self):
        self.metrics.track_handled(100)
        self.metrics.track_handled(200)
        self.metrics.track_skipped(100, "not_in_map")
        self.metrics.track_skipped(200, "not_in_map")
        self.metrics.track_skipped(200, "not_enabled")

        summary = self.metrics.get_summary()
        assert summary["messages_handled"] == 2
        assert summary["messages_skipped"] == 3
        assert summary["skip_reasons"]["not_in_map"] == 2
        assert summary["skip_reasons"]["not_enabled"] == 1

    def test_get_per_group_metrics(self):
        self.metrics.track_handled(100)
        self.metrics.track_skipped(100, "not_assigned")
        result = self.metrics.get_per_group_metrics(100)
        assert result["group_id"] == 100
        assert result["group_title"] == "Group 100"
        assert result["handled"] == 1
        assert result["skipped"] == 1

    def test_get_per_group_metrics_empty(self):
        result = self.metrics.get_per_group_metrics(999)
        assert result["handled"] == 0
        assert result["skipped"] == 0

    def test_clear_resets_all(self):
        self.metrics.track_handled(100)
        self.metrics.track_skipped(100, "x")
        self.metrics.clear()
        assert self.metrics._messages_handled == {}
        assert self.metrics._messages_skipped == {}
        assert self.metrics._skip_reasons == {}

    def test_sampling_resets_on_handle(self):
        """track_handled resets skipped_since_last_log for that group."""
        self.metrics.track_skipped(100, "x")
        assert self.metrics._skipped_since_last_log[100] == 1
        self.metrics.track_handled(100)
        assert self.metrics._skipped_since_last_log[100] == 0

    def test_summary_empty(self):
        summary = self.metrics.get_summary()
        assert summary["messages_handled"] == 0
        assert summary["messages_skipped"] == 0
        assert summary["skip_reasons"] == {}
