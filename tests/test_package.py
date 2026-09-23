"""Tests for DevDoctor package."""

from devdoctor import __version__


def test_version() -> None:
    """Test that version is set."""
    assert __version__ == "0.1.0"
    assert isinstance(__version__, str)
    assert len(__version__) > 0