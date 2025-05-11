import pytest
from unittest.mock import MagicMock, patch
from daebus import Daebus
from daebus.modules.context import get_daemon


def test_daebus_initialization(daebus_app):
    """Test basic initialization of Daebus"""
    assert daebus_app.name == "test_app"
    assert daebus_app.action_handlers == {}
    assert daebus_app.listen_handlers == {}
    assert daebus_app.background_tasks == []
    assert daebus_app._running is False


def test_action_registration(daebus_app):
    """Test registering action handlers"""
    @daebus_app.action("test_action")
    def handle_test_action():
        pass

    assert "test_action" in daebus_app.action_handlers
    assert daebus_app.action_handlers["test_action"] is handle_test_action


def test_listen_registration(daebus_app):
    """Test registering channel listeners"""
    @daebus_app.listen("test_channel")
    def handle_test_channel(data):
        pass

    assert "test_channel" in daebus_app.listen_handlers
    assert daebus_app.listen_handlers["test_channel"] is handle_test_channel


def test_background_registration(daebus_app):
    """Test registering background tasks"""
    @daebus_app.background("test_background", 60)
    def handle_background():
        pass

    assert len(daebus_app.background_tasks) == 1
    name, interval, func = daebus_app.background_tasks[0]
    assert name == "test_background"
    assert interval == 60
    assert func is handle_background


def test_thread_registration(daebus_app):
    """Test registering thread tasks"""
    @daebus_app.thread("test_thread")
    def handle_thread(running):
        pass

    assert "test_thread" in daebus_app.thread_tasks
    assert daebus_app.thread_tasks["test_thread"]["func"] is handle_thread
    assert daebus_app.thread_tasks["test_thread"]["auto_start"] is True

    @daebus_app.thread("manual_thread", auto_start=False)
    def handle_manual_thread(running):
        pass

    assert "manual_thread" in daebus_app.thread_tasks
    assert daebus_app.thread_tasks["manual_thread"]["auto_start"] is False


def test_on_start_registration(daebus_app):
    """Test registering on_start handlers"""
    @daebus_app.on_start()
    def handle_on_start():
        pass

    assert len(daebus_app._on_start_handlers) == 1
    assert daebus_app._on_start_handlers[0] is handle_on_start


# Skip this test for now as it requires complex mocking of redis_client module
@pytest.mark.skip(reason="Requires complex mocking of multiple components including Redis, threading, and scheduling")
def test_run_initialization():
    """Test that run method initializes components correctly"""
    pass 