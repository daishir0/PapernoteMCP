# Papernote MCP Server

日本語のREADMEは、英語のREADMEの後に記載されています。

## Overview
Papernote MCP Server is a Model Context Protocol (MCP) server that enables Claude.ai Web to interact with Papernote, a cloud-based note management system. This server provides tools for creating, reading, updating, and managing notes through natural language commands in Claude.ai.

## Features
- **Create Notes**: Create new notes with automatic timestamp-based filenames
- **Read Notes**: Retrieve note content by filename
- **Append Content**: Add content to the top or bottom of existing notes
- **Replace Text**: Search and replace text within notes
- **Full Update**: Completely overwrite note content
- **OAuth Authentication**: Secure access control with Client ID/Secret

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/daishir0/paper_mcp
   ```
2. Change to the project directory:
   ```bash
   cd paper_mcp
   ```
3. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `config.yaml.example` to `config.yaml` and configure:
   ```bash
   cp config.yaml.example config.yaml
   ```
5. Edit `config.yaml` with your settings:
   - `server.port`: Server port (default: 8000)
   - `papernote.api_url`: Your Papernote API endpoint
   - `papernote.api_key`: Your Papernote API key
   - `oauth.client_id`: OAuth Client ID for MCP authentication
   - `oauth.client_secret`: OAuth Client Secret for MCP authentication

## Usage
### Starting the Server
```bash
python main.py
```
The server will start on `http://127.0.0.1:8000` with SSE transport (port configurable in config.yaml).

### Production Deployment (systemd)
Create a systemd service file at `/etc/systemd/system/papermcp.service`:
```ini
[Unit]
Description=Papernote MCP Server for Claude.ai
After=network.target

[Service]
User=your-user
WorkingDirectory=/path/to/paper_mcp
ExecStart=/bin/bash -c 'source /path/to/python/env && python main.py'
Type=simple
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable papermcp
sudo systemctl start papermcp
```

### Connecting to Claude.ai
1. Go to Claude.ai **Settings > Integrations**
2. Click **Add custom connector**
3. Enter the following:
   - **URL**: `https://your-domain.com/sse`
   - **Client ID**: Your `oauth.client_id` from config.yaml
   - **Client Secret**: Your `oauth.client_secret` from config.yaml

## Available MCP Tools

### Note Management Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `create_note` | Create a new note | `content: str` |
| `get_note` | Get note by filename | `filename: str` |
| `append_top` | Add content after header | `filename, content` |
| `append_bottom` | Add content at end | `filename, content` |
| `replace_text` | Search and replace | `filename, search, replace` |
| `update_full` | Overwrite entire note | `filename, content` |
| `search_notes` | Search notes by content | `query, search_type` |
| `list_notes` | List all notes | `category, limit` |
| `list_categories` | List all categories | - |
| `delete_note` | Delete a note (backup auto-created) | `filename` |

### Paper Management Tools (for Research)

| Tool | Description | Parameters |
|------|-------------|------------|
| `search_papers` | Search papers by title/memo/summary | `query` |
| `list_papers` | List all papers | `category, limit` |
| `get_paper` | Get paper details with memo/summary | `pdf_id` |
| `get_paper_summary` | Get paper summary only | `pdf_id` |

## Example Commands in Claude.ai
Once connected, you can use natural language:

### Note Operations
- "Create a new note about today's meeting"
- "Show me the content of [_]20250121-123456.txt"
- "Append 'Task completed' to the bottom of my note"
- "Replace 'draft' with 'final' in the document"
- "Search for notes about 'meeting'"
- "List all my notes"
- "Show me all categories"

### Paper Operations (Research)
- "Search for papers about 'machine learning'"
- "List all my papers"
- "Show me the details of this paper"
- "What's the summary of paper X?"
- "Compare papers A and B"

## Notes
- Ensure `config.yaml` is properly configured before starting
- The server requires a running Papernote API backend
- Use HTTPS in production with a reverse proxy (Apache/Nginx)
- OAuth credentials protect access to the MCP server

## License
This project is licensed under the MIT License - see the LICENSE file for details.

---

# Papernote MCP Server

## 概要
Papernote MCP Serverは、Claude.ai WebがPapernote（クラウドベースのノート管理システム）と連携するためのModel Context Protocol（MCP）サーバーです。Claude.aiで自然言語のコマンドを使用して、ノートの作成、読み取り、更新、管理を行うためのツールを提供します。

## 機能
- **ノート作成**: タイムスタンプベースのファイル名で新規ノートを自動作成
- **ノート読み取り**: ファイル名でノートの内容を取得
- **コンテンツ追加**: 既存ノートの上部または下部にコンテンツを追加
- **テキスト置換**: ノート内のテキストを検索して置換
- **全体更新**: ノートの内容を完全に上書き
- **OAuth認証**: Client ID/Secretによる安全なアクセス制御

## インストール方法
1. リポジトリをクローン:
   ```bash
   git clone https://github.com/daishir0/paper_mcp
   ```
2. プロジェクトディレクトリに移動:
   ```bash
   cd paper_mcp
   ```
3. 必要なパッケージをインストール:
   ```bash
   pip install -r requirements.txt
   ```
4. `config.yaml.example`を`config.yaml`にコピーして設定:
   ```bash
   cp config.yaml.example config.yaml
   ```
5. `config.yaml`を編集:
   - `server.port`: サーバーポート（デフォルト: 8000）
   - `papernote.api_url`: Papernote APIのエンドポイント
   - `papernote.api_key`: Papernote APIキー
   - `oauth.client_id`: MCP認証用OAuth Client ID
   - `oauth.client_secret`: MCP認証用OAuth Client Secret

## 使い方
### サーバーの起動
```bash
python main.py
```
サーバーは`http://127.0.0.1:8000`でSSEトランスポートで起動します（ポートはconfig.yamlで変更可能）。

### 本番環境へのデプロイ（systemd）
`/etc/systemd/system/papermcp.service`にsystemdサービスファイルを作成:
```ini
[Unit]
Description=Papernote MCP Server for Claude.ai
After=network.target

[Service]
User=your-user
WorkingDirectory=/path/to/paper_mcp
ExecStart=/bin/bash -c 'source /path/to/python/env && python main.py'
Type=simple
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

有効化と起動:
```bash
sudo systemctl daemon-reload
sudo systemctl enable papermcp
sudo systemctl start papermcp
```

### Claude.aiへの接続
1. Claude.aiの**Settings > Integrations**に移動
2. **Add custom connector**をクリック
3. 以下を入力:
   - **URL**: `https://your-domain.com/sse`
   - **Client ID**: config.yamlの`oauth.client_id`
   - **Client Secret**: config.yamlの`oauth.client_secret`

## 利用可能なMCPツール

### ノート管理ツール

| ツール | 説明 | パラメータ |
|--------|------|-----------|
| `create_note` | 新規ノート作成 | `content: str` |
| `get_note` | ファイル名でノート取得 | `filename: str` |
| `append_top` | ヘッダー後にコンテンツ追加 | `filename, content` |
| `append_bottom` | 末尾にコンテンツ追加 | `filename, content` |
| `replace_text` | 検索と置換 | `filename, search, replace` |
| `update_full` | ノート全体を上書き | `filename, content` |
| `search_notes` | ノートを検索 | `query, search_type` |
| `list_notes` | ノート一覧取得 | `category, limit` |
| `list_categories` | カテゴリ一覧取得 | - |
| `delete_note` | ノート削除（バックアップ自動作成） | `filename` |

### 論文管理ツール（研究用）

| ツール | 説明 | パラメータ |
|--------|------|-----------|
| `search_papers` | タイトル/メモ/サマリーで論文検索 | `query` |
| `list_papers` | 論文一覧取得 | `category, limit` |
| `get_paper` | 論文詳細取得（メモ/サマリー含む） | `pdf_id` |
| `get_paper_summary` | 論文サマリーのみ取得 | `pdf_id` |

## Claude.aiでの使用例
接続後、自然言語で指示できます:

### ノート操作
- 「今日の会議についてのノートを作成して」
- 「[_]20250121-123456.txtの内容を見せて」
- 「ノートの末尾に『タスク完了』と追加して」
- 「ドキュメント内の『下書き』を『最終版』に置き換えて」
- 「会議についてのノートを検索して」
- 「ノート一覧を見せて」
- 「カテゴリ一覧を表示して」

### 論文操作（研究）
- 「機械学習に関する論文を検索して」
- 「論文一覧を見せて」
- 「この論文の詳細を見せて」
- 「論文Xのサマリーを教えて」
- 「論文AとBを比較して」

## 注意点
- 起動前に`config.yaml`が正しく設定されていることを確認してください
- サーバーにはPapernote APIバックエンドが必要です
- 本番環境ではリバースプロキシ（Apache/Nginx）でHTTPSを使用してください
- OAuth認証情報がMCPサーバーへのアクセスを保護します

## ライセンス
このプロジェクトはMITライセンスの下でライセンスされています。詳細はLICENSEファイルを参照してください。
