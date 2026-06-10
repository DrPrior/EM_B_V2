"""Tests for the schema constraints initialization module."""

from unittest.mock import MagicMock

from src.database.schema import setup_constraints


def test_setup_constraints() -> None:
    """Test that all database constraints and indexes are executed."""
    mock_driver = MagicMock()
    mock_session = MagicMock()

    # Mock the context manager for driver.session()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    # Execute constraints setup
    setup_constraints(mock_driver)

    # Ensure session was created and queries were run
    mock_driver.session.assert_called_once()

    # We expect 9 queries to be run (8 constraints + 1 vector index)
    assert mock_session.run.call_count == 9
