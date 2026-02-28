"""Papernote tools implementation for MCP Server."""
import re
import requests
from typing import Optional
from datetime import datetime
from urllib.parse import quote


def _parse_note_sections(content: str) -> list[dict]:
    """# yyyymmdd... 見出しでノートをセクションに分割する"""
    pattern = re.compile(r'^(# \d{8}[^\n]*)', re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return []
    sections = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i+1].start() if i+1 < len(matches) else len(content)
        sections.append({
            'title': match.group(1).strip(),
            'content': content[start:end].rstrip()
        })
    return sections


def _get_snippet(text: str, query: str, context_chars: int = 120) -> str:
    """クエリ周辺のスニペットを抽出する"""
    lower = text.lower()
    idx = lower.find(query.lower())
    if idx == -1:
        return text[:context_chars].replace('\n', ' ')
    start = max(0, idx - 40)
    end = min(len(text), idx + len(query) + 80)
    return text[start:end].replace('\n', ' ')


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

        # 1行目の ## とタイトルの間のスペースを除去（## Title → ##Title）
        lines = content.split("\n") if content else [""]
        if lines[0].startswith("## "):
            lines[0] = "##" + lines[0][3:]
        content = "\n".join(lines)

        # 1行目が##で始まらない場合は##を付与（非公開にする）
        first_line = lines[0]
        if not first_line.startswith("##"):
            if first_line.startswith("#"):
                content = "#" + content
            else:
                content = "##" + content
            lines = content.split("\n")

        # # yyyymmdd 見出しの存在チェック・自動挿入
        has_date_heading = any(
            line.startswith("# ") and not line.startswith("##")
            for line in lines
        )
        if not has_date_heading:
            title_text = lines[0].lstrip("#").strip()
            date_str = datetime.now().strftime("%Y%m%d")
            date_heading = f"# {date_str}{title_text}"
            # 1行目の後: 空行 → date_heading → 空行 → 残り本文
            rest = lines[1:] if len(lines) > 1 else []
            if rest and rest[0] == "":
                rest = [rest[0], date_heading, ""] + rest[1:]
            else:
                rest = ["", date_heading, ""] + rest
            lines = [lines[0]] + rest
            content = "\n".join(lines)

        # 正規化済みコンテンツをそのまま使用
        full_content = content

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

        Auto-inserts a # yyyymmddTitle date heading if the content
        doesn't already contain one.

        Args:
            filename: The filename of the note
            content: Content to append

        Returns:
            Updated note info
        """
        # 追加コンテンツに # yyyymmdd 日付見出しがなければ自動挿入
        content_lines = content.split("\n")
        has_date_heading = any(
            line.startswith("# ") and not line.startswith("##")
            and re.match(r'^# \d{8}', line)
            for line in content_lines
        )
        if not has_date_heading:
            # 最初の見出し行からタイトルテキストを抽出
            first_line = content_lines[0]
            title_text = first_line.lstrip("#").strip()
            date_str = datetime.now().strftime("%Y%m%d")
            date_heading = f"# {date_str}{title_text}"
            content = f"{date_heading}\n\n{content}"

        # Get current content
        current = self.get_note(filename)
        # API returns {"data": {"content": "..."}, "status": "success"}
        current_content = current.get("data", {}).get("content", "")

        # title(1行目) + empty(2行目) の後に挿入
        lines = current_content.split("\n")
        title_line = lines[0] if len(lines) > 0 else ""
        empty_line = lines[1] if len(lines) > 1 else ""
        body = "\n".join(lines[2:]) if len(lines) > 2 else ""
        new_content = f"{title_line}\n{empty_line}\n{content}\n\n{body}"

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

    def upload_image(self, file_path: str = None, image_data: str = None, filename: str = "image.png") -> dict:
        """Upload an image to Papernote.

        Args:
            file_path: Path to the image file (local MCP server only)
            image_data: Base64-encoded image data (for remote Claude.ai usage)
            filename: Filename to use when uploading via image_data

        Returns:
            API response with markdown_url
        """
        import os
        import base64
        import io

        base_url = self.api_url.replace("/posts", "")
        url = f"{base_url}/images"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        if image_data:
            # Base64文字列をデコードしてバイナリとして送信
            # data:image/png;base64,... 形式にも対応
            if "," in image_data:
                header, data = image_data.split(",", 1)
                mime_type = header.split(":")[1].split(";")[0] if ":" in header else "image/png"
                ext = mime_type.split("/")[-1]
            else:
                data = image_data
                ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'png'
                mime_type = f"image/{ext}"
            binary_data = base64.b64decode(data)
            files = {'file': (filename, io.BytesIO(binary_data), mime_type)}
            response = requests.post(url, headers=headers, files=files)
        elif file_path:
            ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''
            with open(file_path, 'rb') as f:
                files = {'file': (os.path.basename(file_path), f, f'image/{ext}')}
                response = requests.post(url, headers=headers, files=files)
        else:
            raise ValueError("Either file_path or image_data must be provided")

        response.raise_for_status()
        return response.json()

    def upload_paper(self, file_path: str = None, file_data: str = None, filename: str = "paper.pdf") -> dict:
        """Upload a paper PDF to Papernote.

        Args:
            file_path: Path to the PDF file (local MCP server only)
            file_data: Base64-encoded PDF data (for remote usage)
            filename: Filename to use when uploading via file_data

        Returns:
            API response with upload result
        """
        import os
        import base64
        import io

        base_url = self.api_url.replace("/posts", "")
        url = f"{base_url}/papers"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        if file_data:
            if "," in file_data:
                header_part, data = file_data.split(",", 1)
            else:
                data = file_data
            binary_data = base64.b64decode(data)
            files = {'file': (filename, io.BytesIO(binary_data), 'application/pdf')}
        elif file_path:
            with open(file_path, 'rb') as f:
                files = {'file': (os.path.basename(file_path), f, 'application/pdf')}
                response = requests.post(url, headers=headers, files=files)
                response.raise_for_status()
                return response.json()
        else:
            raise ValueError("file_path or file_data required")

        response = requests.post(url, headers=headers, files=files)
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

        Content format (auto-corrected if not followed):
          Line 1: ##Title (no space between ## and title)
          Line 2: (empty)
          Line 3: # yyyymmddTitle (single # date heading, unique in document)
          Line 4: (empty)
          Line 5+: Body text (section headers start with ##)

        Example:
          ##ハワイ旅行メモ

          # 20260218旅行計画

          ## 概要
          - 出発日: 7月1日

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
    def get_note_section(filename: str, section_query: str) -> str:
        """ノートの特定日付セクションのみ取得する（コンテキスト節約）。

        1ファイルに複数の # yyyymmdd... セクションがある場合、
        指定したセクションの内容だけを返す。

        Args:
            filename: ノートのファイル名
            section_query: 日付文字列 (例: '20260227') またはタイトルの一部

        Returns:
            マッチしたセクションの内容、または利用可能なセクション一覧
        """
        try:
            result = client.get_note(filename)
            content = result.get("data", {}).get("content", "")
            sections = _parse_note_sections(content)
            if not sections:
                return f"'{filename}' に # yyyymmdd セクションが見つかりません"
            for section in sections:
                if section_query in section['title']:
                    return section['content']
            titles = "\n".join(f"- {s['title']}" for s in sections)
            return f"セクション '{section_query}' が見つかりません。利用可能なセクション:\n{titles}"
        except requests.exceptions.RequestException as e:
            return f"Error getting note section: {str(e)}"

    @mcp.tool()
    def search_sections(query: str, search_in: str = "body") -> str:
        """複数ノートを横断してセクション単位で検索する。

        # yyyymmdd... で区切られたセクションの中からクエリにマッチするものを返す。
        ファイル全体ではなくセクション単位で返すためコンテキスト節約になる。

        Args:
            query: 検索クエリ文字列
            search_in: 'title'（セクション見出しのみ）, 'body'（本文のみ）, 'all'（両方）

        Returns:
            マッチしたセクションの一覧（ファイル名・見出し・スニペット付き）
        """
        try:
            # Step1: 既存APIで候補ファイルを絞り込み
            search_result = client.search_notes(query, "all")
            candidates = [p['filename'] for p in search_result.get("data", {}).get("posts", [])]
            if not candidates:
                return f"'{query}' を含むノートが見つかりません"

            matches = []
            for fname in candidates:
                try:
                    note_result = client.get_note(fname)
                    content = note_result.get("data", {}).get("content", "")
                    for section in _parse_note_sections(content):
                        hit = False
                        if search_in in ("title", "all") and query.lower() in section['title'].lower():
                            hit = True
                        if search_in in ("body", "all") and query.lower() in section['content'].lower():
                            hit = True
                        if hit:
                            matches.append({
                                'filename': fname,
                                'section': section['title'],
                                'snippet': _get_snippet(section['content'], query)
                            })
                except Exception:
                    continue

            if not matches:
                return f"'{query}' を含むセクションが見つかりません"

            output = [f"{len(matches)} 件のセクションが見つかりました:"]
            for m in matches:
                output.append(f"\n[{m['filename']}] {m['section']}")
                output.append(f"  ...{m['snippet']}...")
            return "\n".join(output)
        except requests.exceptions.RequestException as e:
            return f"Error searching sections: {str(e)}"

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

    @mcp.tool()
    def upload_image(
        file_path: str = None,
        image_data: str = None,
        filename: str = "image.png",
        append_to: str = None
    ) -> str:
        """Upload an image to Papernote.

        Two modes depending on the environment:

        Mode 1 - file_path (local MCP server only):
          upload_image(file_path="/path/to/image.png")

        Mode 2 - image_data (for Claude.ai Web / remote usage):
          Read the image file, encode it as Base64, and pass the string.
          Supports raw Base64 or data URI format (data:image/png;base64,...).
          upload_image(image_data="iVBORw0KGgo...", filename="photo.png")

        Args:
            file_path: Path to the image file (jpg/png/gif/webp etc.)
            image_data: Base64-encoded image data string
            filename: Filename to use when uploading via image_data (default: image.png)
            append_to: Optional note filename to append the image markdown URL to

        Returns:
            Markdown URL of the uploaded image
        """
        try:
            result = client.upload_image(
                file_path=file_path,
                image_data=image_data,
                filename=filename
            )
            markdown_url = result.get("data", {}).get("markdown_url", "")
            if append_to and markdown_url:
                client.append_top(append_to, markdown_url)
                return f"Uploaded and appended to {append_to}: {markdown_url}"
            return f"Uploaded: {markdown_url}"
        except Exception as e:
            return f"Error uploading image: {str(e)}"

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

    @mcp.tool()
    def upload_paper(file_path: str = None, file_data: str = None, filename: str = "paper.pdf") -> str:
        """Upload a paper PDF to Papernote.

        Mode 1 - file_path (local): upload_paper(file_path="/path/to/paper.pdf")
        Mode 2 - file_data (remote/Base64): upload_paper(file_data="base64string", filename="paper.pdf")

        Returns: Upload result with pdf_id for future reference.
        """
        try:
            result = client.upload_paper(file_path=file_path, file_data=file_data, filename=filename)
            status = result.get("status", "unknown")
            data = result.get("data", {})
            pdf_id = data.get("pdf_id", "N/A")
            orig = data.get("original_filename", filename)
            return f"Status: {status}\nPDF ID: {pdf_id}\nOriginal: {orig}"
        except requests.exceptions.RequestException as e:
            return f"Error uploading paper: {str(e)}"
