"""Tests for zoho_cli.mail helper behavior."""

from __future__ import annotations

from zoho_cli import mail


class _PagedClient:
    def __init__(self, pages: dict[int, list[dict]]) -> None:
        self.pages = pages
        self.starts: list[int] = []

    def get_folders(self, account_id: str) -> dict:
        return {"data": [{"folderId": "F1"}]}

    def get_messages(
        self, account_id: str, folder_id: str, limit: int = 50, start: int = 0
    ) -> dict:
        self.starts.append(start)
        return {"data": self.pages.get(start, [])}


def test_find_folder_for_message_paginates_until_found() -> None:
    """Search continues past the first page when needed."""
    first_page = [{"messageId": str(i)} for i in range(50)]
    second_page = [{"messageId": "target-id"}]
    client = _PagedClient({0: first_page, 50: second_page})

    folder_id = mail.find_folder_for_message(client, "ACC1", "target-id")

    assert folder_id == "F1"
    assert client.starts == [0, 50]


def test_find_folder_for_message_returns_none_after_all_pages() -> None:
    """Returns None when a message is not present in any scanned page."""
    first_page = [{"messageId": str(i)} for i in range(50)]
    last_page = [{"messageId": "x1"}, {"messageId": "x2"}]
    client = _PagedClient({0: first_page, 50: last_page})

    folder_id = mail.find_folder_for_message(client, "ACC1", "missing-id")

    assert folder_id is None
    assert client.starts == [0, 50, 52]
