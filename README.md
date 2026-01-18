# Notion to Markdown Exporter

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg?style=for-the-badge)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge)](LICENSE)

A powerful Python tool to export Notion pages and databases to Markdown files with automatic link resolution and recursive page discovery.

## ✨ Features

- **Complete Notion Export**: Export entire Notion pages including all content blocks
- **Recursive Link Following**: Automatically discovers and exports linked pages
- **Database Support**: Export all pages from Notion databases
- **Smart Link Rewriting**: Converts Notion page links to relative Markdown links
- **Rich Block Support**: Handles headings, lists, code blocks, tables, images, and more
- **Automatic Retry**: Built-in exponential backoff for API rate limits
- **SEO-Friendly Output**: Generates clean, readable Markdown files
- **Index Generation**: Creates an index file with links to all exported pages

## 🚀 Installation

### Prerequisites

- Python 3.8 or higher
- A Notion integration token (get one at https://www.notion.so/my-integrations)
- `uv` package manager (recommended) or pip

### Quick Start

1. Clone this repository:

```bash
git clone https://github.com/yourusername/notion-to-markdown.git
cd notion-to-markdown
```

2. Install dependencies:

```bash
# Using uv (recommended)
uv sync
```

3. Configure your Notion token:

```bash
cp .env.example .env
# Edit .env and add your NOTION_TOKEN
```

## 📖 Usage

### Database Export

Export a Notion database to Markdown:

```bash
uv run main.py \
  --root-url "https://www.notion.so/your-page-id" \
  --out "./export"
```

### Advanced Options

Keep original Notion links (disable link rewriting):

```bash
uv run main.py \
  --root-url "https://www.notion.so/your-page-id" \
  --out "./export" \
  --no-rewrite-links
```

Specify a custom Notion API version:

```bash
NOTION_VERSION="2022-06-28" uv run main.py \
  --root-url "https://www.notion.so/your-page-id" \
  --out "./export"
```

### Command Line Arguments

| Argument             | Required | Description                                              |
| -------------------- | -------- | -------------------------------------------------------- |
| `--root-url`         | Yes      | Notion page URL or ID (supports pages and databases)     |
| `--out`              | No       | Output directory (default: `./notion_export`)            |
| `--token`            | No       | Notion integration token (or set `NOTION_TOKEN` env var) |
| `--notion-version`   | No       | Notion API version (default: `2022-06-28`)               |
| `--no-rewrite-links` | No       | Disable automatic link rewriting                         |

## 🔧 Setting Up Notion Integration

### How to Obtain a Notion Integration Token

To use this tool, you need to create a Notion integration and obtain an API token:

1. **Create a Notion Integration**:
    - Go to https://www.notion.so/my-integrations
    - Click "New integration" or "Add new integration"
    - Give it a descriptive name (e.g., "Notion to Markdown Exporter")
    - Select your workspace from the dropdown
    - Choose the relevant workspace type (e.g., "Individual" or "Team")
    - Click "Submit" to create the integration

2. **Copy Your Integration Token**:
    - After creating the integration, you'll see an "Internal Integration Token"
    - Click "Show" to reveal the token (it starts with `ntn_`)
    - Copy this token - you'll need it for configuration
    - ⚠️ **Important**: Keep this token secure and never share it publicly

3. **Add Integration Token to Environment**:
    - Create a `.env` file in the project root (copy from `.env.example`)
    - Add your token: `NOTION_TOKEN=your_copied_token_here`
    - The tool will automatically read this token from the environment

### Share Your Page or Database

1. Open the page or database you want to export
2. Click "..." (more options) in the top right
3. Select "Connections" → "Add connections"
4. Choose your integration from the list

## 📝 Supported Notion Blocks

This tool supports a wide variety of Notion block types:

- **Text Content**: Paragraphs, headings (H1-H3), quotes, callouts
- **Lists**: Bulleted lists, numbered lists, to-do lists, toggles
- **Code**: Code blocks with language syntax highlighting
- **Media**: Images, files, PDFs, videos, audio
- **Tables**: HTML table output for compatibility
- **Links**: Bookmarks, page mentions, link_to_page blocks
- **Other**: Dividers, child pages, and more

## 🌟 Key Features Explained

### Recursive Link Discovery

The tool automatically:

- Finds all page links in rich text mentions
- Discovers `link_to_page` blocks
- Follows child page references
- Exports all discovered pages recursively

### Smart Link Rewriting

Notion page links are automatically converted to relative Markdown links:

- **Before**: `https://www.notion.so/page-id`
- **After**: `./page-title--abc123.md`

Unexported pages fall back to their original Notion URLs.

### Error Handling

Built-in resilience with:

- Automatic retry with exponential backoff
- Graceful handling of inaccessible pages
- Skips 403/404 errors while continuing exports

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🔗 Related Resources

- [Notion API Documentation](https://developers.notion.com/)
- [Notion Integration Guide](https://www.notion.so/help/integrations)
- [Markdown Specification](https://commonmark.org/)

## 💡 Use Cases

- **Documentation**: Convert Notion docs to static site generators
- **Backup**: Archive Notion content in Markdown format
- **Migration**: Move content from Notion to other platforms
- **Version Control**: Track changes with Git
- **Publishing**: Generate static documentation sites

## 🐛 Troubleshooting

### "Missing Notion token" Error

Make sure you've set the `NOTION_TOKEN` environment variable or passed it via `--token`.

### Page Not Accessible

Ensure your integration has been added to the page/database connections in Notion.

### Rate Limiting

The tool includes automatic retry logic. If you encounter persistent issues, add delays between operations or contact Notion about API limits.

## 📞 Support

For issues, questions, or suggestions, please open an issue on GitHub.
