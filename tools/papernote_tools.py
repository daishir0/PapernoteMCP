"""Papernote tools implementation for MCP Server."""
import re
import requests
from typing import Optional
from datetime import datetime
from urllib.parse import quote
from mcp.types import ImageContent, TextContent
import base64


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


def _split_lines(content: str) -> list[str]:
    """LF 前提で行分割する。末尾の空行も保持する。"""
    return content.split("\n")


def _join_lines(lines: list[str]) -> str:
    """_split_lines の逆変換。"""
    return "\n".join(lines)


def _validate_range(from_line: int, to_line: int, total: int) -> tuple:
    """行番号範囲 [from_line, to_line] を検証する。

    Args:
        from_line: 1-indexed 開始行
        to_line: 1-indexed 終了行（-1 で末尾まで）
        total: 対象メモの総行数

    Returns:
        (True, (from, to)) もしくは (False, error_message)
    """
    if to_line == -1:
        to_line = total
    if not isinstance(from_line, int) or not isinstance(to_line, int):
        return (False, f"from_line/to_line は整数である必要があります (got {from_line}, {to_line})")
    if total == 0:
        return (False, "メモが空です")
    if from_line < 1 or from_line > total:
        return (False, f"from_line {from_line} は範囲外です (有効範囲: 1..{total})")
    if to_line < from_line or to_line > total:
        return (False, f"to_line {to_line} は範囲外です (有効範囲: {from_line}..{total})")
    return (True, (from_line, to_line))


def _format_numbered_lines(lines: list[str], start_line: int) -> str:
    """行番号付きのプレビュー形式に整形する。AI が再パースしやすい固定幅。"""
    out = []
    for i, line in enumerate(lines):
        out.append("{:>5}: {}".format(start_line + i, line))
    return "\n".join(out)


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
            # 画像マークダウンやURLはタイトルに含めない
            if title_text.startswith("[![") or title_text.startswith("![") or title_text.startswith("http"):
                date_heading = f"# {date_str}"
            else:
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

    def download_attachment(self, path: str) -> tuple[bytes, str]:
        """Download an attachment from Papernote.

        Args:
            path: Attachment path (e.g., /attach/HASH.png)

        Returns:
            Tuple of (binary_data, content_type)
        """
        # Build full URL from API URL
        # api_url = https://paper.path-finder.jp/api/posts
        # site_url = https://paper.path-finder.jp
        site_url = self.api_url.split('/api/')[0]
        # Ensure path starts with /
        if not path.startswith('/'):
            path = '/' + path
        url = f"{site_url}{path}"
        response = requests.get(url, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=30)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', 'image/png').split(';')[0].strip()
        return response.content, content_type

    def upload_image(self, file_path: str = None, image_data: str = None,
                     image_url: str = None, svg_content: str = None,
                     filename: str = "image.png") -> dict:
        """Upload an image to Papernote.

        Args:
            file_path: Path to the image file (local MCP server only)
            image_data: Base64-encoded image data (for remote Claude.ai usage)
            image_url: URL to download the image from (avoids base64 context bloat)
            svg_content: Raw SVG XML text (for Claude.ai Web - no base64 overhead)
            filename: Filename to use when uploading via image_data/image_url/svg_content

        Returns:
            API response with markdown_url
        """
        import os
        import base64
        import io

        MAX_SIZE = 10 * 1024 * 1024  # 10MB (server limit)
        COMPRESS_THRESHOLD = 500 * 1024  # 500KB

        base_url = self.api_url.replace("/posts", "")
        url = f"{base_url}/images"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        binary_data = None
        mime_type = None
        ext = None

        if image_url:
            # Mode 3: URL経由ダウンロード
            resp = requests.get(image_url, timeout=30)
            resp.raise_for_status()
            binary_data = resp.content
            content_type = resp.headers.get('Content-Type', 'image/png').split(';')[0].strip()
            mime_type = content_type
            ext = content_type.split('/')[-1].replace('svg+xml', 'svg').replace('jpeg', 'jpg')
            if filename == 'image.png':
                url_path = image_url.split('?')[0].split('/')[-1]
                if '.' in url_path:
                    filename = url_path
                else:
                    filename = f"image.{ext}"

        elif svg_content:
            # Mode 4: SVG XML text directly (Claude.ai Web - no base64 overhead)
            binary_data = svg_content.encode('utf-8')
            mime_type = 'image/svg+xml'
            ext = 'svg'
            if filename == 'image.png':
                filename = 'image.svg'

        elif image_data:
            # Mode 2: Base64文字列をデコード
            # data:image/png;base64,... 形式にも対応
            if "," in image_data:
                header, data = image_data.split(",", 1)
                mime_type = header.split(":")[1].split(";")[0] if ":" in header else "image/png"
                ext = mime_type.split("/")[-1].replace('svg+xml', 'svg').replace('jpeg', 'jpg')
            else:
                data = image_data
                ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'png'
                mime_type = 'image/svg+xml' if ext == 'svg' else f"image/{ext}"
            binary_data = base64.b64decode(data)

        elif file_path:
            # Mode 1: ローカルファイルパス
            ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''
            mime_type = 'image/svg+xml' if ext == 'svg' else f'image/{ext}'
            with open(file_path, 'rb') as f:
                binary_data = f.read()
            if filename == 'image.png':
                filename = os.path.basename(file_path)

        else:
            raise ValueError(
                "One of file_path, image_data, or image_url must be provided.\n"
                "- file_path: local file (Claude Code)\n"
                "- image_data: base64 string (Claude.ai Web)\n"
                "- image_url: URL to download from (recommended for large images)"
            )

        # 大画像の自動圧縮（SVG/GIF除外）
        if (len(binary_data) > COMPRESS_THRESHOLD and
                ext not in ('svg', 'gif')):
            try:
                from PIL import Image as PILImage
                img = PILImage.open(io.BytesIO(binary_data))
                max_dim = 2000
                if max(img.size) > max_dim:
                    img.thumbnail((max_dim, max_dim), PILImage.Resampling.LANCZOS)
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=85, optimize=True)
                binary_data = buf.getvalue()
                filename = filename.rsplit('.', 1)[0] + '.jpg' if '.' in filename else 'image.jpg'
                mime_type = 'image/jpeg'
                ext = 'jpg'
            except Exception:
                pass  # 圧縮失敗時はそのまま送信

        # サイズチェック
        if len(binary_data) > MAX_SIZE:
            raise ValueError(
                f"Image too large ({len(binary_data) / 1024 / 1024:.1f}MB). "
                f"Maximum is 10MB. Try a smaller image or use image_url for URL-based upload."
            )

        files = {'file': (filename, io.BytesIO(binary_data), mime_type)}
        response = requests.post(url, headers=headers, files=files)
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

    # --- Section関連メソッド ---

    def get_sections(self, filename: str, offset: int = 0, count: int = 3) -> dict:
        """セクション単位でノートを取得（ページネーション対応）"""
        encoded_filename = quote(filename, safe='')
        url = f"{self.api_url}/{encoded_filename}/sections"
        params = {"offset": offset, "count": count}
        response = requests.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_section_titles(self, filename: str) -> dict:
        """セクションタイトル一覧を取得"""
        encoded_filename = quote(filename, safe='')
        url = f"{self.api_url}/{encoded_filename}/sections/titles"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def search_note_sections(self, filename: str, query: str) -> dict:
        """セクション名で検索（サーバー側部分一致）"""
        encoded_filename = quote(filename, safe='')
        url = f"{self.api_url}/{encoded_filename}/sections/search"
        params = {"q": query}
        response = requests.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()

    # --- 行ベースランダムアクセス/編集メソッド ---

    def _fetch_lines(self, filename: str) -> list[str]:
        """内部用: ノート全文を取得し行配列にして返す。"""
        current = self.get_note(filename)
        content = current.get("data", {}).get("content", "")
        return _split_lines(content)

    def get_note_info(self, filename: str) -> dict:
        """ノートのメタ情報（総行数・タイトル・セクション開始行）を返す。"""
        current = self.get_note(filename)
        content = current.get("data", {}).get("content", "")
        lines = _split_lines(content)
        total_lines = len(lines)

        # セクション見出し行を行番号付きで収集（# yyyymmdd... のみ）
        pattern = re.compile(r'^# \d{8}')
        section_heads = []
        for i, line in enumerate(lines, start=1):
            if pattern.match(line):
                section_heads.append({"index": len(section_heads), "title": line.strip(), "start_line": i})
        # 各セクションの end_line を決定
        for idx, s in enumerate(section_heads):
            if idx + 1 < len(section_heads):
                s["end_line"] = section_heads[idx + 1]["start_line"] - 1
            else:
                s["end_line"] = total_lines

        title_line = lines[0] if lines else ""
        return {
            "filename": filename,
            "total_lines": total_lines,
            "title": title_line,
            "sections": section_heads,
        }

    def get_note_lines(self, filename: str, from_line: int, to_line: int = -1, around: int = 0) -> dict:
        """指定行範囲の行を返す。1-indexed 両端含む。

        around > 0 の場合は from_line を中心に前後 around 行（to_line は無視）。
        """
        lines = self._fetch_lines(filename)
        total = len(lines)

        if around > 0:
            center = from_line
            f = max(1, center - around)
            t = min(total, center + around)
            valid = (True, (f, t))
        else:
            valid = _validate_range(from_line, to_line, total)

        if not valid[0]:
            return {"error": valid[1], "total_lines": total}

        f, t = valid[1]
        selected = lines[f - 1:t]
        return {
            "filename": filename,
            "from_line": f,
            "to_line": t,
            "total_lines": total,
            "lines": selected,
        }

    def find_note_lines(self, filename: str, pattern: str, is_regex: bool = False,
                        max_results: int = 50, context_lines: int = 0) -> dict:
        """ノート内で pattern にマッチする行番号を返す。

        context_lines > 0 で前後 N 行の文脈も同梱。
        """
        lines = self._fetch_lines(filename)
        total = len(lines)

        if is_regex:
            try:
                regex = re.compile(pattern)
            except re.error as e:
                return {"error": f"invalid regex: {e}", "total_lines": total}
            matcher = lambda s: regex.search(s) is not None
        else:
            needle = pattern
            matcher = lambda s: needle in s

        hits = []
        for i, line in enumerate(lines, start=1):
            if matcher(line):
                hit = {"line_number": i, "text": line}
                if context_lines > 0:
                    bs = max(1, i - context_lines)
                    be = i - 1
                    af_s = i + 1
                    af_e = min(total, i + context_lines)
                    hit["before"] = [{"line_number": n, "text": lines[n - 1]} for n in range(bs, be + 1)] if be >= bs else []
                    hit["after"] = [{"line_number": n, "text": lines[n - 1]} for n in range(af_s, af_e + 1)] if af_e >= af_s else []
                hits.append(hit)
                if len(hits) >= max_results:
                    break

        return {
            "filename": filename,
            "total_lines": total,
            "match_count": len(hits),
            "hits": hits,
        }

    def search_notes_lines(self, query: str, is_regex: bool = False,
                           max_files: int = 20, max_per_file: int = 20) -> dict:
        """グローバル行検索: 複数ノートから行単位ヒットを返す。"""
        search_result = self.search_notes(query, "all")
        candidates = [p['filename'] for p in search_result.get("data", {}).get("posts", [])]
        candidates = candidates[:max_files]

        results = []
        for fname in candidates:
            try:
                r = self.find_note_lines(fname, query, is_regex=is_regex, max_results=max_per_file)
                for hit in r.get("hits", []):
                    results.append({
                        "filename": fname,
                        "line_number": hit["line_number"],
                        "text": hit["text"],
                    })
            except Exception:
                continue
        return {
            "query": query,
            "file_count": len(candidates),
            "match_count": len(results),
            "results": results,
        }

    def replace_note_lines(self, filename: str, from_line: int, to_line: int,
                           content: str, dry_run: bool = False) -> dict:
        """行 [from_line..to_line] を content で置き換え。"""
        lines = self._fetch_lines(filename)
        total = len(lines)
        ok, val = _validate_range(from_line, to_line, total)
        if not ok:
            return {"error": val, "total_lines": total}
        f, t = val

        new_chunk = content.split("\n") if content != "" else []
        new_lines = lines[:f - 1] + new_chunk + lines[t:]
        new_total = len(new_lines)

        if dry_run:
            return {
                "filename": filename,
                "dry_run": True,
                "from_line": f,
                "to_line": t,
                "lines_removed": (t - f + 1),
                "lines_inserted": len(new_chunk),
                "total_lines_before": total,
                "total_lines_after": new_total,
                "preview": _format_numbered_lines(new_lines[max(0, f - 3):f - 1 + len(new_chunk) + 2], max(1, f - 2)),
            }

        self.update_full(filename, _join_lines(new_lines))
        return {
            "filename": filename,
            "from_line": f,
            "to_line": t,
            "lines_removed": (t - f + 1),
            "lines_inserted": len(new_chunk),
            "total_lines_before": total,
            "total_lines_after": new_total,
        }

    def insert_note_lines(self, filename: str, at_line: int, content: str,
                          dry_run: bool = False) -> dict:
        """行 at_line の直前に content を挿入。at_line = total+1 で末尾追記。"""
        lines = self._fetch_lines(filename)
        total = len(lines)
        if not isinstance(at_line, int) or at_line < 1 or at_line > total + 1:
            return {"error": f"at_line {at_line} は範囲外です (有効範囲: 1..{total + 1})", "total_lines": total}

        new_chunk = content.split("\n") if content != "" else [""]
        new_lines = lines[:at_line - 1] + new_chunk + lines[at_line - 1:]
        new_total = len(new_lines)

        if dry_run:
            return {
                "filename": filename,
                "dry_run": True,
                "at_line": at_line,
                "lines_inserted": len(new_chunk),
                "total_lines_before": total,
                "total_lines_after": new_total,
                "preview": _format_numbered_lines(
                    new_lines[max(0, at_line - 3):at_line - 1 + len(new_chunk) + 2],
                    max(1, at_line - 2),
                ),
            }

        self.update_full(filename, _join_lines(new_lines))
        return {
            "filename": filename,
            "at_line": at_line,
            "lines_inserted": len(new_chunk),
            "total_lines_before": total,
            "total_lines_after": new_total,
        }

    def delete_note_lines(self, filename: str, from_line: int, to_line: int,
                          dry_run: bool = False) -> dict:
        """行 [from_line..to_line] を削除。"""
        lines = self._fetch_lines(filename)
        total = len(lines)
        ok, val = _validate_range(from_line, to_line, total)
        if not ok:
            return {"error": val, "total_lines": total}
        f, t = val
        new_lines = lines[:f - 1] + lines[t:]
        new_total = len(new_lines)

        if dry_run:
            return {
                "filename": filename,
                "dry_run": True,
                "from_line": f,
                "to_line": t,
                "lines_removed": (t - f + 1),
                "total_lines_before": total,
                "total_lines_after": new_total,
                "preview": _format_numbered_lines(
                    new_lines[max(0, f - 3):f + 1],
                    max(1, f - 2),
                ) if new_lines else "(empty)",
            }

        self.update_full(filename, _join_lines(new_lines))
        return {
            "filename": filename,
            "from_line": f,
            "to_line": t,
            "lines_removed": (t - f + 1),
            "total_lines_before": total,
            "total_lines_after": new_total,
        }

    def move_note_lines(self, filename: str, from_line: int, to_line: int,
                        dest_line: int, dry_run: bool = False) -> dict:
        """ブロック [from..to] を dest_line の直前に移動。"""
        lines = self._fetch_lines(filename)
        total = len(lines)
        ok, val = _validate_range(from_line, to_line, total)
        if not ok:
            return {"error": val, "total_lines": total}
        f, t = val
        if not isinstance(dest_line, int) or dest_line < 1 or dest_line > total + 1:
            return {"error": f"dest_line {dest_line} は範囲外です (有効範囲: 1..{total + 1})", "total_lines": total}
        if f <= dest_line <= t + 1:
            return {"error": f"dest_line {dest_line} が移動元ブロック [{f}..{t}] 内または直後にあり no-op です", "total_lines": total}

        block = lines[f - 1:t]
        remaining = lines[:f - 1] + lines[t:]
        # dest_line の補正: ブロックより後ろ (dest_line > t) なら削除分だけ左にずらす
        if dest_line > t:
            adj = dest_line - (t - f + 1)
        else:
            adj = dest_line
        new_lines = remaining[:adj - 1] + block + remaining[adj - 1:]
        new_total = len(new_lines)

        if dry_run:
            return {
                "filename": filename,
                "dry_run": True,
                "from_line": f,
                "to_line": t,
                "dest_line": dest_line,
                "block_size": len(block),
                "total_lines_before": total,
                "total_lines_after": new_total,
                "preview": _format_numbered_lines(
                    new_lines[max(0, adj - 3):adj - 1 + len(block) + 2],
                    max(1, adj - 2),
                ),
            }

        self.update_full(filename, _join_lines(new_lines))
        return {
            "filename": filename,
            "from_line": f,
            "to_line": t,
            "dest_line": dest_line,
            "block_size": len(block),
            "total_lines_before": total,
            "total_lines_after": new_total,
        }

    def batch_edit_note(self, filename: str, operations: list, dry_run: bool = False) -> dict:
        """複数の行編集操作を 1 回の PUT で原子的に適用する。

        operations の各要素は以下のいずれか:
          {"op": "replace", "from_line": int, "to_line": int, "content": str}
          {"op": "insert",  "at_line": int, "content": str}
          {"op": "delete",  "from_line": int, "to_line": int}
          {"op": "move",    "from_line": int, "to_line": int, "dest_line": int}

        すべて **元のメモの行番号** を基準に指定すること。
        内部で行番号の大きい順にソートして末尾から適用するため、
        ユーザー側で番号ずれを考慮する必要は無い。
        """
        lines = self._fetch_lines(filename)
        total = len(lines)

        # move を delete+insert に正規化
        normalized = []
        for idx, op in enumerate(operations):
            name = op.get("op")
            if name == "move":
                f = op.get("from_line")
                t = op.get("to_line")
                d = op.get("dest_line")
                ok, val = _validate_range(f, t, total)
                if not ok:
                    return {"error": f"op[{idx}] (move) {val}"}
                if not isinstance(d, int) or d < 1 or d > total + 1:
                    return {"error": f"op[{idx}] (move) dest_line {d} は範囲外"}
                if f <= d <= t + 1:
                    return {"error": f"op[{idx}] (move) dest_line が移動元ブロック内/直後で no-op"}
                block = lines[f - 1:t]
                block_content = _join_lines(block)
                # 削除と挿入に分解（元のインデックス基準のまま）
                normalized.append({"op": "delete", "from_line": f, "to_line": t, "_sort": f})
                normalized.append({"op": "insert", "at_line": d, "content": block_content, "_sort": d - 0.5})
            elif name == "replace":
                f = op.get("from_line")
                t = op.get("to_line")
                c = op.get("content", "")
                ok, val = _validate_range(f, t, total)
                if not ok:
                    return {"error": f"op[{idx}] (replace) {val}"}
                normalized.append({"op": "replace", "from_line": f, "to_line": t, "content": c, "_sort": f})
            elif name == "insert":
                a = op.get("at_line")
                c = op.get("content", "")
                if not isinstance(a, int) or a < 1 or a > total + 1:
                    return {"error": f"op[{idx}] (insert) at_line {a} は範囲外 (1..{total + 1})"}
                normalized.append({"op": "insert", "at_line": a, "content": c, "_sort": a - 0.5})
            elif name == "delete":
                f = op.get("from_line")
                t = op.get("to_line")
                ok, val = _validate_range(f, t, total)
                if not ok:
                    return {"error": f"op[{idx}] (delete) {val}"}
                normalized.append({"op": "delete", "from_line": f, "to_line": t, "_sort": f})
            else:
                return {"error": f"op[{idx}] 不明な op: {name}"}

        # 重なりチェック（単純: 同じ行を複数 replace/delete で触るのは禁止）
        touched_ranges = []
        for n in normalized:
            if n["op"] in ("replace", "delete"):
                touched_ranges.append((n["from_line"], n["to_line"]))
        touched_ranges.sort()
        for i in range(len(touched_ranges) - 1):
            if touched_ranges[i][1] >= touched_ranges[i + 1][0]:
                return {"error": f"重なる範囲を複数の replace/delete で触れません: {touched_ranges[i]} と {touched_ranges[i+1]}"}

        # _sort 降順で適用
        normalized.sort(key=lambda x: x["_sort"], reverse=True)
        buf = list(lines)
        for n in normalized:
            if n["op"] == "replace":
                f, t, c = n["from_line"], n["to_line"], n["content"]
                chunk = c.split("\n") if c != "" else []
                buf = buf[:f - 1] + chunk + buf[t:]
            elif n["op"] == "insert":
                a, c = n["at_line"], n["content"]
                chunk = c.split("\n") if c != "" else [""]
                buf = buf[:a - 1] + chunk + buf[a - 1:]
            elif n["op"] == "delete":
                f, t = n["from_line"], n["to_line"]
                buf = buf[:f - 1] + buf[t:]

        new_total = len(buf)
        if dry_run:
            return {
                "filename": filename,
                "dry_run": True,
                "applied": len(operations),
                "total_lines_before": total,
                "total_lines_after": new_total,
            }

        self.update_full(filename, _join_lines(buf))
        return {
            "filename": filename,
            "applied": len(operations),
            "total_lines_before": total,
            "total_lines_after": new_total,
        }

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
    def get_note(filename: str, with_line_numbers: bool = False) -> str:
        """Get a note from Papernote by filename.

        Args:
            filename: The filename of the note (e.g., '[_]20250121-123456.txt')
            with_line_numbers: True で各行に "   12: text" 形式の行番号を付加する。
                               行ベース編集（replace_note_lines 等）の前段で全文を行番号付きで確認したい時に便利。

        Returns:
            The note content
        """
        try:
            result = client.get_note(filename)
            # API returns {"data": {"content": "..."}, "status": "success"}
            data = result.get("data", {})
            content = data.get("content", "Note content not found")
            if with_line_numbers and content:
                return _format_numbered_lines(_split_lines(content), 1)
            return content
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
            result = client.search_note_sections(filename, section_query)
            data = result.get("data", {})
            sections = data.get("sections", [])
            if sections:
                # 最初のマッチを返す
                return sections[0].get("content", "")
            # マッチなし → タイトル一覧を返す
            titles_result = client.get_section_titles(filename)
            titles_data = titles_result.get("data", {})
            title_list = titles_data.get("titles", [])
            if not title_list:
                return f"'{filename}' にセクションが見つかりません"
            titles = "\n".join(f"- [{t['index']}] {t['title']}" for t in title_list)
            return f"セクション '{section_query}' が見つかりません。利用可能なセクション:\n{titles}"
        except requests.exceptions.RequestException as e:
            return f"Error getting note section: {str(e)}"

    @mcp.tool()
    def list_note_sections(filename: str, with_line_numbers: bool = False) -> str:
        """ノート内のセクション（# 見出し）一覧を取得する。
        内容を取得する前にどのセクションがあるか確認するのに使う。

        with_line_numbers=True を指定すると、各セクションの開始/終了行も併記する
        （内部で get_note_info と同等の処理を行う）。行ベース編集の前準備に便利。
        """
        try:
            if with_line_numbers:
                info = client.get_note_info(filename)
                sections = info.get("sections", [])
                if not sections:
                    return f"'{filename}' にセクションが見つかりません"
                out = [f"{filename} のセクション一覧（全{len(sections)}件, total_lines={info['total_lines']}）:"]
                for s in sections:
                    out.append(f"- [{s['index']}] L{s['start_line']}-L{s['end_line']}: {s['title']}")
                return "\n".join(out)

            result = client.get_section_titles(filename)
            data = result.get("data", {})
            titles = data.get("titles", [])
            total = data.get("total", 0)
            if not titles:
                return f"'{filename}' にセクションが見つかりません"
            output = [f"{filename} のセクション一覧（全{total}件）:"]
            for t in titles:
                output.append(f"- [{t['index']}] {t['title']}")
            return "\n".join(output)
        except requests.exceptions.RequestException as e:
            return f"Error listing sections: {str(e)}"

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
            if search_in == "title":
                # サーバーAPI活用：タイトル検索のみなので全文取得不要
                for fname in candidates:
                    try:
                        result = client.search_note_sections(fname, query)
                        for s in result.get("data", {}).get("sections", []):
                            matches.append({
                                'filename': fname,
                                'section': f"# {s['title']}",
                                'snippet': _get_snippet(s.get('content', ''), query)
                            })
                    except Exception:
                        continue
            else:
                # body/all: 従来通り全文取得+クライアント側分割
                for fname in candidates:
                    try:
                        note_result = client.get_note(fname)
                        content = note_result.get("data", {}).get("content", "")
                        for section in _parse_note_sections(content):
                            hit = False
                            if search_in == "all" and query.lower() in section['title'].lower():
                                hit = True
                            if query.lower() in section['content'].lower():
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
        image_url: str = None,
        svg_content: str = None,
        filename: str = "image.png",
        append_to: str = None
    ) -> str:
        """Upload an image to Papernote.

        Four modes depending on the environment:

        Mode 1 - file_path (local MCP server / Claude Code):
          upload_image(file_path="/path/to/image.png")

        Mode 2 - image_data (for Claude.ai Web / remote usage):
          Base64-encoded image data. Supports raw Base64 or data URI format.
          upload_image(image_data="iVBORw0KGgo...", filename="photo.png")
          Note: Images >500KB are auto-compressed to JPEG to save context.

        Mode 3 - image_url (recommended for large images):
          Download image from URL and upload. Avoids base64 context bloat.
          upload_image(image_url="https://example.com/image.png")

        Mode 4 - svg_content (for Claude.ai Web / SVG charts):
          Pass SVG XML text directly. No base64 encoding needed.
          upload_image(svg_content="<svg>...</svg>", filename="chart.svg")

        Supported formats: jpg, png, gif, webp, svg, heic, heif
        Max file size: 10MB (auto-compression applied for images >500KB)
        HEIC/HEIF images are auto-converted to JPEG on the server.

        Args:
            file_path: Path to the image file
            image_data: Base64-encoded image data string
            image_url: URL to download the image from
            svg_content: Raw SVG XML text string (no base64 needed)
            filename: Filename to use (default: image.png)
            append_to: Optional note filename to append the image markdown URL to

        Returns:
            Markdown URL of the uploaded image
        """
        try:
            result = client.upload_image(
                file_path=file_path,
                image_data=image_data,
                image_url=image_url,
                svg_content=svg_content,
                filename=filename
            )
            markdown_url = result.get("data", {}).get("markdown_url", "")
            if append_to and markdown_url:
                client.append_top(append_to, markdown_url)
                return f"Uploaded and appended to {append_to}: {markdown_url}"
            return f"Uploaded: {markdown_url}"
        except ValueError as e:
            return f"Validation error: {str(e)}"
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 413:
                return "Error: Image too large (server limit is 10MB). Try a smaller image."
            if e.response is not None and e.response.status_code == 400:
                try:
                    body = e.response.json()
                    return f"Error: {body.get('message', str(e))}"
                except Exception:
                    pass
            return f"Error uploading image: {str(e)}"
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

    # --- Phase 5: 添付ファイル取得ツール ---

    @mcp.tool()
    def list_attachments(filename: str) -> str:
        """List all image/attachment URLs referenced in a note's markdown content.

        Parses the note content for markdown image links (![...](/attach/...))
        and returns a numbered list of attachment paths.

        Args:
            filename: The filename of the note

        Returns:
            List of attachment paths found in the note
        """
        try:
            result = client.get_note(filename)
            content = result.get("data", {}).get("content", "")
            # Match markdown image/link patterns: (/attach/HASH.ext) or (/attach/HASH.ext "title")
            pattern = re.compile(r'\(/attach/([^\s)"]+)')
            matches = pattern.findall(content)
            # Deduplicate while preserving order, skip thumbnails (s_ prefix)
            seen = set()
            attachments = []
            for match in matches:
                # Skip thumbnail versions (s_ prefix)
                if match.startswith('s_'):
                    continue
                if match not in seen:
                    seen.add(match)
                    attachments.append(f"/attach/{match}")
            if not attachments:
                return "No attachments found in this note."
            lines = [f"{i+1}. {path}" for i, path in enumerate(attachments)]
            return f"Found {len(attachments)} attachment(s):\n" + "\n".join(lines)
        except requests.exceptions.RequestException as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def get_attachment(path: str) -> list[TextContent | ImageContent]:
        """Download an attachment (image) from Papernote and return it visually.

        Use list_attachments first to find available paths, then pass a path here.
        Returns the image so Claude.ai can see and analyze it directly.

        Args:
            path: Attachment path (e.g., /attach/abc123.png)

        Returns:
            The image content (displayed visually in Claude.ai)
        """
        try:
            binary_data, content_type = client.download_attachment(path)
            if content_type == 'image/svg+xml':
                return [TextContent(
                    type="text",
                    text=f"SVG content:\n```xml\n{binary_data.decode('utf-8')}\n```"
                )]
            b64_data = base64.b64encode(binary_data).decode('utf-8')
            return [ImageContent(
                type="image",
                data=b64_data,
                mimeType=content_type
            )]
        except requests.exceptions.RequestException as e:
            return [TextContent(type="text", text=f"Error downloading attachment: {str(e)}")]

    # --- Phase: 行ベースランダムアクセス/編集ツール ---

    @mcp.tool()
    def get_note_info(filename: str) -> str:
        """ノートのメタ情報（総行数・タイトル・セクション見出しと行番号）を返す。

        行ベース編集（get_note_lines / replace_note_lines 等）を行う前の orient 用。
        ノート全文を取らないので AI のコンテキストを節約できる。

        Args:
            filename: ノートのファイル名

        Returns:
            総行数、タイトル行、各セクションの開始/終了行
        """
        try:
            info = client.get_note_info(filename)
            out = [
                f"File: {info['filename']}",
                f"Total lines: {info['total_lines']}",
                f"Title: {info['title']}",
            ]
            sections = info.get("sections", [])
            if sections:
                out.append(f"Sections ({len(sections)}):")
                for s in sections:
                    out.append(f"  [{s['index']}] L{s['start_line']}-L{s['end_line']}: {s['title']}")
            else:
                out.append("Sections: (none)")
            return "\n".join(out)
        except requests.exceptions.RequestException as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def get_note_lines(filename: str, from_line: int, to_line: int = -1,
                       with_line_numbers: bool = True, around: int = 0) -> str:
        """ノートの指定行範囲を取得する。1-indexed, 両端を含む。

        - to_line=-1 で末尾まで
        - around>0 を指定すると from_line を中心に前後 N 行を返す（to_line は無視）
        - with_line_numbers=True なら "   12: text" 形式で行番号付きで返す

        Args:
            filename: ノートのファイル名
            from_line: 開始行（1-indexed）。around 指定時は中心行。
            to_line: 終了行（1-indexed, 両端含む）。-1 で末尾まで。
            with_line_numbers: 行番号を付加するか（デフォルト True）
            around: >0 で from_line の前後 N 行を返す

        Returns:
            行範囲のテキスト
        """
        try:
            result = client.get_note_lines(filename, from_line, to_line, around=around)
            if "error" in result:
                return f"Error: {result['error']} (total_lines={result.get('total_lines')})"
            lines = result["lines"]
            header = f"# {result['filename']} L{result['from_line']}-L{result['to_line']} (total={result['total_lines']})"
            if with_line_numbers:
                body = _format_numbered_lines(lines, result["from_line"])
            else:
                body = _join_lines(lines)
            return f"{header}\n{body}"
        except requests.exceptions.RequestException as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def find_note_lines(filename: str, pattern: str, is_regex: bool = False,
                        max_results: int = 50, context_lines: int = 0) -> str:
        """ノート内で pattern にマッチする行を検索し、行番号を返す。

        編集前に座標を取得する用途を想定。context_lines>0 で grep -C 相当の前後文脈付き。

        Args:
            filename: ノートのファイル名
            pattern: 検索文字列（または is_regex=True なら正規表現）
            is_regex: True で正規表現、False で部分文字列マッチ
            max_results: 返すヒットの最大数
            context_lines: ヒット行の前後 N 行を併記する

        Returns:
            行番号とテキスト（必要に応じて前後文脈）
        """
        try:
            result = client.find_note_lines(filename, pattern, is_regex=is_regex,
                                            max_results=max_results, context_lines=context_lines)
            if "error" in result:
                return f"Error: {result['error']}"
            hits = result["hits"]
            if not hits:
                return f"No matches for '{pattern}' in {filename} (total_lines={result['total_lines']})"
            out = [f"# {filename}: {result['match_count']} hit(s) (total_lines={result['total_lines']})"]
            for h in hits:
                if context_lines > 0 and (h.get("before") or h.get("after")):
                    for b in h.get("before", []):
                        out.append("{:>5}  {}".format(b["line_number"], b["text"]))
                    out.append("{:>5}> {}".format(h["line_number"], h["text"]))
                    for a in h.get("after", []):
                        out.append("{:>5}  {}".format(a["line_number"], a["text"]))
                    out.append("--")
                else:
                    out.append("{:>5}: {}".format(h["line_number"], h["text"]))
            return "\n".join(out)
        except requests.exceptions.RequestException as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def search_notes_lines(query: str, is_regex: bool = False,
                           max_files: int = 20, max_per_file: int = 20) -> str:
        """複数ノートを横断して行単位で検索する（グローバル行検索）。

        search_notes でヒットしたファイルを find_note_lines で行単位に絞り込み、
        {filename, line_number, text} のフラットリストで返す。

        Args:
            query: 検索クエリ
            is_regex: True で正規表現
            max_files: 検索対象にする最大ファイル数
            max_per_file: 1 ファイルあたりの最大ヒット数

        Returns:
            ヒット一覧（ファイル名・行番号・行テキスト）
        """
        try:
            result = client.search_notes_lines(query, is_regex=is_regex,
                                               max_files=max_files, max_per_file=max_per_file)
            results = result["results"]
            if not results:
                return f"No line-level matches for '{query}'"
            out = [f"{result['match_count']} line(s) in {result['file_count']} file(s):"]
            for r in results:
                out.append(f"[{r['filename']}] L{r['line_number']}: {r['text']}")
            return "\n".join(out)
        except requests.exceptions.RequestException as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def replace_note_lines(filename: str, from_line: int, to_line: int,
                           content: str, dry_run: bool = False) -> str:
        """指定した行範囲 [from_line..to_line] を content で置き換える。

        - 1-indexed, 両端を含む
        - content は複数行可（\\n 区切り）、空文字で削除と等価
        - dry_run=True で PUT せずに編集プレビューだけ返す

        Args:
            filename: ノートのファイル名
            from_line: 置換開始行（1-indexed）
            to_line: 置換終了行（1-indexed, 両端含む）
            content: 置き換え内容（複数行可）
            dry_run: True で適用せずプレビューのみ
        """
        try:
            result = client.replace_note_lines(filename, from_line, to_line, content, dry_run=dry_run)
            if "error" in result:
                return f"Error: {result['error']}"
            if dry_run:
                return (f"[DRY-RUN] {filename}: L{result['from_line']}-L{result['to_line']} "
                        f"({result['lines_removed']}行削除, {result['lines_inserted']}行挿入). "
                        f"Total: {result['total_lines_before']} -> {result['total_lines_after']}\n"
                        f"Preview:\n{result['preview']}")
            return (f"Updated {filename}: replaced L{result['from_line']}-L{result['to_line']} "
                    f"({result['lines_removed']} lines) with {result['lines_inserted']} new lines. "
                    f"Total lines now: {result['total_lines_after']}.")
        except requests.exceptions.RequestException as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def insert_note_lines(filename: str, at_line: int, content: str, dry_run: bool = False) -> str:
        """指定した行の直前に content を挿入する。

        at_line = total_lines + 1 を指定すると末尾追記になる。
        content は複数行可（\\n 区切り）。

        Args:
            filename: ノートのファイル名
            at_line: 挿入位置（この行の直前に入る, 1-indexed）
            content: 挿入内容
            dry_run: True で適用せずプレビューのみ
        """
        try:
            result = client.insert_note_lines(filename, at_line, content, dry_run=dry_run)
            if "error" in result:
                return f"Error: {result['error']}"
            if dry_run:
                return (f"[DRY-RUN] {filename}: L{result['at_line']} に {result['lines_inserted']} 行挿入. "
                        f"Total: {result['total_lines_before']} -> {result['total_lines_after']}\n"
                        f"Preview:\n{result['preview']}")
            return (f"Inserted {result['lines_inserted']} line(s) at L{result['at_line']} in {filename}. "
                    f"Total lines now: {result['total_lines_after']}.")
        except requests.exceptions.RequestException as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def delete_note_lines(filename: str, from_line: int, to_line: int, dry_run: bool = False) -> str:
        """指定した行範囲 [from_line..to_line] を削除する。1-indexed, 両端を含む。

        Args:
            filename: ノートのファイル名
            from_line: 削除開始行
            to_line: 削除終了行（両端含む, -1 で末尾まで）
            dry_run: True で適用せずプレビューのみ
        """
        try:
            result = client.delete_note_lines(filename, from_line, to_line, dry_run=dry_run)
            if "error" in result:
                return f"Error: {result['error']}"
            if dry_run:
                return (f"[DRY-RUN] {filename}: L{result['from_line']}-L{result['to_line']} "
                        f"({result['lines_removed']}行) を削除予定. "
                        f"Total: {result['total_lines_before']} -> {result['total_lines_after']}\n"
                        f"Preview:\n{result['preview']}")
            return (f"Deleted L{result['from_line']}-L{result['to_line']} ({result['lines_removed']} lines) "
                    f"from {filename}. Total lines now: {result['total_lines_after']}.")
        except requests.exceptions.RequestException as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def move_note_lines(filename: str, from_line: int, to_line: int,
                        dest_line: int, dry_run: bool = False) -> str:
        """行ブロック [from_line..to_line] を dest_line の直前に移動する。

        delete+insert を AI 側で連続実行すると行番号がずれるため、それを回避する原子操作。
        dest_line は **元の行番号** を指定すること（内部で座標補正する）。

        Args:
            filename: ノートのファイル名
            from_line: 移動元ブロック開始行
            to_line: 移動元ブロック終了行（両端含む）
            dest_line: 移動先（この行の直前にブロックが入る）
            dry_run: True で適用せずプレビューのみ
        """
        try:
            result = client.move_note_lines(filename, from_line, to_line, dest_line, dry_run=dry_run)
            if "error" in result:
                return f"Error: {result['error']}"
            if dry_run:
                return (f"[DRY-RUN] {filename}: L{result['from_line']}-L{result['to_line']} "
                        f"({result['block_size']}行) を L{result['dest_line']} の直前に移動予定.\n"
                        f"Preview:\n{result['preview']}")
            return (f"Moved L{result['from_line']}-L{result['to_line']} ({result['block_size']} lines) "
                    f"to before L{result['dest_line']} in {filename}. "
                    f"Total lines: {result['total_lines_after']}.")
        except requests.exceptions.RequestException as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def batch_edit_note(filename: str, operations: list, dry_run: bool = False) -> str:
        """複数の行編集を 1 回の PUT で原子的に適用する（★最重要）。

        行番号はすべて **元のメモの行番号** を基準に指定。内部で降順適用するので
        クライアント側で番号ずれを考慮する必要は無い。1 件でもバリデーション失敗なら
        メモは無変更で全体 reject される（原子性）。

        operations の各要素（op の種類）:
          {"op": "replace", "from_line": 10, "to_line": 12, "content": "new text"}
          {"op": "insert",  "at_line": 20, "content": "new line"}
          {"op": "delete",  "from_line": 30, "to_line": 30}
          {"op": "move",    "from_line": 40, "to_line": 42, "dest_line": 5}

        同じ行範囲に対して複数の replace/delete を掛けることはできない（重なりエラー）。
        content は複数行可（\\n 区切り）。

        Args:
            filename: ノートのファイル名
            operations: 上記の dict のリスト
            dry_run: True で適用せずプレビューのみ
        """
        try:
            result = client.batch_edit_note(filename, operations, dry_run=dry_run)
            if "error" in result:
                return f"Error: {result['error']}"
            prefix = "[DRY-RUN] " if dry_run else ""
            return (f"{prefix}{filename}: {result['applied']} operations applied. "
                    f"Total lines: {result['total_lines_before']} -> {result['total_lines_after']}.")
        except requests.exceptions.RequestException as e:
            return f"Error: {str(e)}"
