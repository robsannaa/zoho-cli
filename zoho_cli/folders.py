"""Folder formatting helpers."""


def format_folder(folder: dict) -> dict:
    name = folder.get("folderName", "")
    return {
        "folderId": str(folder.get("folderId", "")),
        "folderName": name,
        "folderType": folder.get("folderType", ""),
        "path": folder.get("path", f"/{name}"),
        "isArchived": int(folder.get("isArchived", 0)),
        "unreadCount": int(folder.get("unreadCount", 0)),
        "messageCount": int(folder.get("messageCount", 0)),
    }
