"""Papernote tools implementation for MCP Server."""
import requests
from typing import Optional
from datetime import datetime
from urllib.parse import quote


class PapernoteClient:
    """Client for interacting with Papernote API."""

    def __init__(self, api_url: str, api_key: str):
        """Initialize Papernote client.

        Args:
            api_url: Papernote API base URL
            api_key: Papernote API key
        """
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def create_note(self, content: str) -> dict:
        """Create a new note.

        Args:
            content: The content of the note

        Returns:
            API response with created note info
        """
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"[_]{timestamp}.txt"

        # Add header lines (title and date)
        title = content.split("\n")[0][:50] if content else "New Note"
        date_line = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_content = f"{title}\n{date_line}\n\n{content}"

        payload = {
            "filename": filename,
            "content": full_content
        }

        response = requests.post(self.api_url, json=payload, headers=self.headers)
        response.raise_for_status()
        return {"filename": filename, "message": "Note created successfully", "data": response.json()}

    def get_note(self, filename: str) -> dict:
        """Get a note by filename.

        Args:
            filename: The filename of the note

        Returns:
            Note content and metadata
        """
        # URL encode the filename to handle special characters like [ and ]
        encoded_filename = quote(filename, safe='')
        url = f"{self.api_url}/{encoded_filename}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def append_top(self, filename: str, content: str) -> dict:
        """Append content to the top of a note (after line 2).

        Args:
            filename: The filename of the note
            content: Content to append

        Returns:
            Updated note info
        """
        # Get current content
        current = self.get_note(filename)
        # API returns {"data": {"content": "..."}, "status": "success"}
        current_content = current.get("data", {}).get("content", "")

        # Split into lines
        lines = current_content.split("\n")

        # Insert after line 2 (title and date)
        if len(lines) >= 2:
            new_lines = lines[:2] + [content] + lines[2:]
        else:
            new_lines = lines + [content]

        new_content = "\n".join(new_lines)

        return self.update_full(filename, new_content)

    def append_bottom(self, filename: str, content: str) -> dict:
        """Append content to the bottom of a note.

        Args:
            filename: The filename of the note
            content: Content to append

        Returns:
            Updated note info
        """
        # Get current content
        current = self.get_note(filename)
        # API returns {"data": {"content": "..."}, "status": "success"}
        current_content = current.get("data", {}).get("content", "")

        # Append to bottom
        new_content = f"{current_content}\n{content}"

        return self.update_full(filename, new_content)

    def replace_text(self, filename: str, search: str, replace: str) -> dict:
        """Replace text in a note.

        Args:
            filename: The filename of the note
            search: Text to search for
            replace: Replacement text

        Returns:
            Updated note info
        """
        # Get current content
        current = self.get_note(filename)
        # API returns {"data": {"content": "..."}, "status": "success"}
        current_content = current.get("data", {}).get("content", "")

        # Replace text
        new_content = current_content.replace(search, replace)

        if new_content == current_content:
            return {"filename": filename, "message": "No changes made - search text not found"}

        return self.update_full(filename, new_content)

    def update_full(self, filename: str, content: str) -> dict:
        """Update entire note content.

        Args:
            filename: The filename of the note
            content: New content for the note

        Returns:
            Updated note info
        """
        # URL encode the filename to handle special characters like [ and ]
        encoded_filename = quote(filename, safe='')
        url = f"{self.api_url}/{encoded_filename}"
        payload = {"content": content}

        response = requests.put(url, json=payload, headers=self.headers)
        response.raise_for_status()
        return {"filename": filename, "message": "Note updated successfully", "data": response.json()}


def register_tools(mcp, config: dict):
    """Register Papernote tools with the MCP server.

    Args:
        mcp: FastMCP server instance
        config: Configuration dictionary
    """
    papernote_config = config.get("papernote", {})
    client = PapernoteClient(
        api_url=papernote_config.get("api_url", ""),
        api_key=papernote_config.get("api_key", "")
    )

    @mcp.tool()
    def create_note(content: str) -> str:
        """Create a new note in Papernote.

        Args:
            content: The content of the note to create

        Returns:
            JSON string with created note filename and status
        """
        try:
            result = client.create_note(content)
            return f"Created note: {result['filename']}"
        except requests.exceptions.RequestException as e:
            return f"Error creating note: {str(e)}"

    @mcp.tool()
    def get_note(filename: str) -> str:
        """Get a note from Papernote by filename.

        Args:
            filename: The filename of the note (e.g., '[_]20250121-123456.txt')

        Returns:
            The note content
        """
        try:
            result = client.get_note(filename)
            # API returns {"data": {"content": "..."}, "status": "success"}
            data = result.get("data", {})
            return data.get("content", "Note content not found")
        except requests.exceptions.RequestException as e:
            return f"Error getting note: {str(e)}"

    @mcp.tool()
    def append_top(filename: str, content: str) -> str:
        """Append content to the top of a note (after the header lines).

        Args:
            filename: The filename of the note
            content: Content to append at the top

        Returns:
            Status message
        """
        try:
            result = client.append_top(filename, content)
            return f"Updated note: {result['filename']}"
        except requests.exceptions.RequestException as e:
            return f"Error updating note: {str(e)}"

    @mcp.tool()
    def append_bottom(filename: str, content: str) -> str:
        """Append content to the bottom of a note.

        Args:
            filename: The filename of the note
            content: Content to append at the bottom

        Returns:
            Status message
        """
        try:
            result = client.append_bottom(filename, content)
            return f"Updated note: {result['filename']}"
        except requests.exceptions.RequestException as e:
            return f"Error updating note: {str(e)}"

    @mcp.tool()
    def replace_text(filename: str, search: str, replace: str) -> str:
        """Replace text in a note.

        Args:
            filename: The filename of the note
            search: Text to search for
            replace: Replacement text

        Returns:
            Status message
        """
        try:
            result = client.replace_text(filename, search, replace)
            return result.get("message", "Text replaced successfully")
        except requests.exceptions.RequestException as e:
            return f"Error replacing text: {str(e)}"

    @mcp.tool()
    def update_full(filename: str, content: str) -> str:
        """Update the entire content of a note.

        Args:
            filename: The filename of the note
            content: New content for the note

        Returns:
            Status message
        """
        try:
            result = client.update_full(filename, content)
            return f"Updated note: {result['filename']}"
        except requests.exceptions.RequestException as e:
            return f"Error updating note: {str(e)}"
