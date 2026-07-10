from __future__ import annotations

from astrbot_plugin_companion_lite.core import Storage


def test_completed_rounds_require_user_then_assistant(tmp_path):
    storage = Storage(str(tmp_path / "rounds.db"))
    try:
        storage.append_message("u", "assistant", "orphan")
        storage.append_message("u", "user", "one")
        storage.append_message("u", "user", "two")
        storage.append_message("u", "assistant", "reply")
        storage.append_message("u", "assistant", "duplicate")
        storage.append_message("u", "user", "three")
        assert storage.count_completed_rounds("u") == 1
        storage.append_message("u", "assistant", "reply three")
        assert storage.count_completed_rounds("u") == 2
    finally:
        storage.close()


def test_reflection_snapshot_cleanup_preserves_new_messages(tmp_path):
    storage = Storage(str(tmp_path / "snapshot.db"))
    try:
        storage.append_message("u", "user", "old user")
        storage.append_message("u", "assistant", "old assistant")
        snapshot = storage.get_messages_for_reflection("u", limit=40)
        snapshot_max_id = max(message["id"] for message in snapshot)

        storage.append_message("u", "user", "new user")
        storage.append_message("u", "assistant", "new assistant")
        storage.delete_messages_through("u", snapshot_max_id)

        remaining = storage.get_recent_messages("u", limit=10)
        assert [message["content"] for message in remaining] == ["new user", "new assistant"]
        assert storage.count_completed_rounds("u") == 1
    finally:
        storage.close()


def test_reflection_reads_oldest_pending_messages(tmp_path):
    storage = Storage(str(tmp_path / "oldest.db"))
    try:
        for index in range(5):
            storage.append_message("u", "user", str(index))
        snapshot = storage.get_messages_for_reflection("u", limit=2)
        assert [message["content"] for message in snapshot] == ["0", "1"]
    finally:
        storage.close()


def test_latest_user_message_id_ignores_assistant_rows(tmp_path):
    storage = Storage(str(tmp_path / "latest-user.db"))
    try:
        storage.append_message("u", "user", "first")
        first_id = storage.get_latest_user_message_id("u")
        storage.append_message("u", "assistant", "reply")
        assert storage.get_latest_user_message_id("u") == first_id
        storage.append_message("u", "user", "second")
        assert storage.get_latest_user_message_id("u") > first_id
    finally:
        storage.close()
