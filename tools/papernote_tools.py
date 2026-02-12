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

        # 1行目が##で始まらない場合は##を付与（非公開にする）
        first_line = content.split("\n")[0] if content else ""
        if not first_line.startswith("##"):
            if first_line.startswith("#"):
                content = "#" + content
            else:
                content = "##" + content

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

    def search_notes(self, query: str, search_type: str = "all") -> dict:
        """Search notes by content.

        Args:
            query: Search query string
            search_type: 'title', 'body', or 'all' (default: 'all')

        Returns:
            Search results
        """
        url = f"{self.api_url}/search"
        params = {"q": query, "type": search_type}
        response = requests.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def list_notes(self) -> dict:
        """List all notes.

        Returns:
            List of all notes
        """
        response = requests.get(self.api_url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def list_categories(self) -> dict:
        """List all categories.

        Returns:
            List of all categories with counts
        """
        base_url = self.api_url.replace("/posts", "")
        url = f"{base_url}/categories"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def delete_note(self, filename: str) -> dict:
        """Delete a note.

        Args:
            filename: The filename of the note to delete

        Returns:
            Deletion result
        """
        encoded_filename = quote(filename, safe='')
        url = f"{self.api_url}/{encoded_filename}"
        response = requests.delete(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    # --- Paper関連メソッド ---

    def search_papers(self, query: str) -> dict:
        """Search papers.

        Args:
            query: Search query string

        Returns:
            Search results
        """
        base_url = self.api_url.replace("/posts", "")
        url = f"{base_url}/papers/search"
        params = {"q": query}
        response = requests.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def list_papers(self) -> dict:
        """List all papers.

        Returns:
            List of all papers
        """
        base_url = self.api_url.replace("/posts", "")
        url = f"{base_url}/papers"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_paper(self, pdf_id: str) -> dict:
        """Get paper details.

        Args:
            pdf_id: The paper ID (filename without .pdf)

        Returns:
            Paper details including memo and summaries
        """
        base_url = self.api_url.replace("/posts", "")
        url = f"{base_url}/papers/{pdf_id}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()


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

    # --- Phase 1: 検索・一覧ツール ---

    @mcp.tool()
    def search_notes(query: str, search_type: str = "all") -> str:
        """Search notes by content.

        Args:
            query: Search query string
            search_type: 'title', 'body', or 'all' (default: 'all')

        Returns:
            List of matching notes
        """
        try:
            result = client.search_notes(query, search_type)
            posts = result.get("data", {}).get("posts", [])
            if not posts:
                return f"No notes found for '{query}'"
            output = [f"Found {len(posts)} notes:"]
            for p in posts[:20]:
                output.append(f"- {p['filename']}: {p['title']}")
            return "\n".join(output)
        except requests.exceptions.RequestException as e:
            return f"Error searching notes: {str(e)}"

    @mcp.tool()
    def list_notes(category: str = None, limit: int = 20) -> str:
        """List all notes.

        Args:
            category: Optional category filter
            limit: Maximum notes to return (default: 20)

        Returns:
            List of notes
        """
        try:
            result = client.list_notes()
            posts = result.get("data", {}).get("posts", [])
            if category:
                posts = [p for p in posts if p.get("category") == category]
            posts = posts[:limit]
            output = [f"Notes ({len(posts)}):"]
            for p in posts:
                output.append(f"- {p['filename']}: {p['title']}")
            return "\n".join(output)
        except requests.exceptions.RequestException as e:
            return f"Error listing notes: {str(e)}"

    # --- Phase 2: 利便性向上ツール ---

    @mcp.tool()
    def list_categories() -> str:
        """List all note categories with counts.

        Returns:
            List of categories with note counts
        """
        try:
            result = client.list_categories()
            cats = result.get("data", {}).get("categories", [])
            output = ["Categories:"]
            for c in cats:
                output.append(f"- {c['category']}: {c['count']} notes")
            return "\n".join(output)
        except requests.exceptions.RequestException as e:
            return f"Error listing categories: {str(e)}"

    @mcp.tool()
    def delete_note(filename: str) -> str:
        """Delete a note (backup created automatically).

        Args:
            filename: The filename of the note to delete

        Returns:
            Deletion status message
        """
        try:
            client.delete_note(filename)
            return f"Deleted: {filename}"
        except requests.exceptions.RequestException as e:
            return f"Error deleting note: {str(e)}"

    # --- Phase 3: Paper関連ツール（研究議論用） ---

    @mcp.tool()
    def search_papers(query: str) -> str:
        """Search papers by title, memo, and summary content.

        Args:
            query: Search query (supports multiple terms)

        Returns:
            List of matching papers
        """
        try:
            result = client.search_papers(query)
            papers = result.get("data", {}).get("results", [])
            if not papers:
                return f"No papers found for '{query}'"
            output = [f"Found {len(papers)} papers:"]
            for p in papers[:20]:
                output.append(f"- [{p['pdf_id']}] {p['title']} ({p.get('category', 'N/A')})")
            return "\n".join(output)
        except requests.exceptions.RequestException as e:
            return f"Error searching papers: {str(e)}"

    @mcp.tool()
    def list_papers(category: str = None, limit: int = 20) -> str:
        """List all papers.

        Args:
            category: Optional category filter
            limit: Maximum papers to return (default: 20)

        Returns:
            List of papers
        """
        try:
            result = client.list_papers()
            papers = result.get("data", {}).get("papers", [])
            if category:
                papers = [p for p in papers if p.get("category") == category]
            papers = papers[:limit]
            output = [f"Papers ({len(papers)}):"]
            for p in papers:
                flags = []
                if p.get("has_memo"):
                    flags.append("memo")
                if p.get("has_summary"):
                    flags.append("summary")
                flag_str = f" [{','.join(flags)}]" if flags else ""
                output.append(f"- [{p['pdf_id']}] {p['title']}{flag_str}")
            return "\n".join(output)
        except requests.exceptions.RequestException as e:
            return f"Error listing papers: {str(e)}"

    @mcp.tool()
    def get_paper(pdf_id: str) -> str:
        """Get paper details including memo and summaries.

        Args:
            pdf_id: The paper ID (filename without .pdf)

        Returns:
            Paper details with memo and summaries
        """
        try:
            result = client.get_paper(pdf_id)
            data = result.get("data", {})
            output = [
                f"# {data.get('title', pdf_id)}",
                f"Category: {data.get('category', 'N/A')}",
                f"Date: {data.get('date', 'N/A')}",
                "",
                "## Memo",
                data.get("memo", "(No memo)") or "(No memo)",
                "",
                "## Summary",
                data.get("summary", "(No summary)") or "(No summary)",
            ]
            if data.get("summary2"):
                output.extend(["", "## Summary 2", data.get("summary2")])
            return "\n".join(output)
        except requests.exceptions.RequestException as e:
            return f"Error getting paper: {str(e)}"

    @mcp.tool()
    def get_paper_summary(pdf_id: str) -> str:
        """Get paper summary only (for quick research discussions).

        Args:
            pdf_id: The paper ID (filename without .pdf)

        Returns:
            Paper title and summary
        """
        try:
            result = client.get_paper(pdf_id)
            data = result.get("data", {})
            summary = data.get("summary", "")
            if not summary:
                return f"No summary available for {pdf_id}"
            return f"# {data.get('title', pdf_id)}\n\n{summary}"
        except requests.exceptions.RequestException as e:
            return f"Error getting paper summary: {str(e)}"
