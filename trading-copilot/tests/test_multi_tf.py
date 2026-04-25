"""Tests for copilot/detectors/multi_tf.py"""

from copilot.detectors.multi_tf import check_multi_tf_alignment


def test_bullish_pullback_is_rto():
    result = check_multi_tf_alignment("bullish", "bearish", "4h", "15m")
    assert result["aligned"] is True
    assert result["ltf_role"] == "pullback"
    assert result["htf_bias"] == "bullish"
    assert result["sync_quality"] in ("strong", "weak")


def test_both_bullish_is_continuation():
    result = check_multi_tf_alignment("bullish", "bullish", "1h", "3m")
    assert result["ltf_role"] == "continuation"
    assert result["aligned"] is True
    assert result["sync_quality"] == "strong"


def test_both_bearish_is_continuation():
    result = check_multi_tf_alignment("bearish", "bearish", "4h", "15m")
    assert result["ltf_role"] == "continuation"
    assert result["aligned"] is True


def test_htf_ranging_is_desync():
    result = check_multi_tf_alignment("ranging", "bullish", "1d", "1h")
    assert result["aligned"] is False
    assert result["sync_quality"] == "desync"


def test_note_is_present():
    result = check_multi_tf_alignment("bullish", "bearish", "4h", "15m")
    assert "note" in result
    assert len(result["note"]) > 0
