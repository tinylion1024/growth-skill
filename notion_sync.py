#!/usr/bin/env python3
"""
Notion Sync Script
同步 Markdown 文件到 Notion，保持目录结构
"""

import os
import re
import json
import base64
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

import requests

# ============ 配置 ============
NOTION_TOKEN = os.environ.get("NOTION_API_KEY")
NOTION_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"

# 根目录
ROOT_DIR = Path(__file__).parent

# Notion Database ID (可选，用于创建数据库页面)
# 如果不设置，页面会创建在根空间
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")

# ============ Notion API 工具函数 ============

def notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

def create_page(parent_id: str, parent_type: str, title: str, content: str, properties: dict = None) -> dict:
    """创建 Notion 页面"""
    payload = {
        "parent": {
            "type": parent_type,
            parent_type: parent_id
        },
        "properties": properties or {
            "title": {
                "title": [
                    {
                        "text": {"content": title}
                    }
                ]
            }
        },
        "children": content_to_blocks(content)
    }

    response = requests.post(
        f"{BASE_URL}/pages",
        headers=notion_headers(),
        json=payload
    )
    return response.json()

def create_child_page(parent_id: str, title: str, content: str) -> dict:
    """创建子页面"""
    return create_page(parent_id, "page_id", title, content)

def content_to_blocks(content: str) -> list:
    """将 Markdown 内容转换为 Notion blocks"""
    blocks = []
    lines = content.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # 跳过空行
        if not line.strip():
            i += 1
            continue

        # 标题
        if line.startswith("### "):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"type": "text", "text": {"content": line[4:]}}]
                }
            })
        elif line.startswith("## "):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": line[3:]}}]
                }
            })
        elif line.startswith("# "):
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {
                    "rich_text": [{"type": "text", "text": {"content": line[2:]}}]
                }
            })

        # 表格
        elif line.startswith("|") and "---" not in line:
            # 收集整个表格
            table_lines = []
            while i < len(lines) and lines[i].startswith("|"):
                if "---" not in lines[i]:
                    table_lines.append(lines[i])
                i += 1

            if table_lines:
                table_blocks = parse_table_blocks(table_lines)
                blocks.extend(table_blocks)
            continue

        # 代码块
        elif line.startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            blocks.append({
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [{"type": "text", "text": {"content": "\n".join(code_lines)}}],
                    "language": "plain text"
                }
            })

        # 列表
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(lines[i][2:])
                i += 1
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": "\n".join(items)}}]
                }
            })
        elif re.match(r"^\d+\. ", line):
            items = []
            while i < len(lines) and re.match(r"^\d+\. ", lines[i]):
                items.append(re.sub(r"^\d+\. ", "", lines[i]))
                i += 1
            blocks.append({
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": "\n".join(items)}}]
                }
            })

        # 引用
        elif line.startswith(">"):
            quote_lines = []
            while i < len(lines) and lines[i].startswith(">"):
                quote_lines.append(lines[i][1:].strip())
                i += 1
            blocks.append({
                "object": "block",
                "type": "quote",
                "quote": {
                    "rich_text": [{"type": "text", "text": {"content": "\n".join(quote_lines)}}]
                }
            })

        # 分隔线
        elif line.startswith("---"):
            blocks.append({
                "object": "block",
                "type": "divider",
                "divider": {}
            })

        # 普通段落
        else:
            # 清理 Markdown 格式
            clean_line = clean_markdown(line)
            if clean_line.strip():
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": clean_line}}]
                    }
                })

        i += 1

    return blocks

def clean_markdown(text: str) -> str:
    """清理 Markdown 格式，保留基本内容"""
    # 移除粗体/斜体标记
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)

    # 移除链接，保留文字
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)

    # 移除图片
    text = re.sub(r"!\[([^\]]*)\]\([^\)]+\)", "", text)

    # 移除代码标记
    text = re.sub(r"`(.+?)`", r"\1", text)

    return text

def parse_table_blocks(table_lines: list) -> list:
    """解析表格行"""
    if len(table_lines) < 2:
        return []

    # 解析表头
    header_cells = [cell.strip() for cell in table_lines[0].split("|")[1:-1]]

    blocks = []

    # 表头
    blocks.append({
        "object": "block",
        "type": "table_header",
        "table_header": {
            "cells": [[{"type": "text", "text": {"content": cell}}] for cell in header_cells],
            "has_column_header": True,
            "has_row_header": False
        }
    })

    # 数据行
    for row in table_lines[2:]:  # 跳过表头和分隔线
        cells = [cell.strip() for cell in row.split("|")[1:-1]]
        blocks.append({
            "object": "block",
            "type": "table_row",
            "table_row": {
                "cells": [[{"type": "text", "text": {"content": cell}}] for cell in cells]
            }
        })

    return blocks

def get_page_id_by_path(path: str, cache: dict) -> Optional[str]:
    """根据文件路径查找已创建的页面ID"""
    return cache.get(path)

def generate_idempotency_key(file_path: str) -> str:
    """生成幂等性key用于去重"""
    return hashlib.sha256(file_path.encode()).hexdigest()[:32]

# ============ 同步逻辑 ============

def sync_file_to_notion(file_path: Path, parent_id: str = None, page_cache: dict = None) -> str:
    """同步单个文件到 Notion"""
    if page_cache is None:
        page_cache = {}

    relative_path = file_path.relative_to(ROOT_DIR)
    path_key = str(relative_path)

    # 读取文件内容
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 提取标题（第一个 # 开头的内容）
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    title = title_match.group(1) if title_match else file_path.stem

    # 检查是否已存在
    cache_file = ROOT_DIR / ".notion_cache.json"
    if cache_file.exists():
        with open(cache_file, "r") as f:
            cache = json.load(f)
    else:
        cache = {}

    if path_key in cache:
        print(f"⏭️  跳过（已存在）: {relative_path}")
        return cache[path_key]

    # 创建页面
    print(f"📤 创建: {relative_path}")

    try:
        if parent_id:
            result = create_child_page(parent_id, title, content)
        else:
            # 创建独立页面
            result = create_page(
                parent_id or NOTION_DATABASE_ID or "",
                "database_id" if NOTION_DATABASE_ID else "page_id",
                title,
                content
            )

        if "id" in result:
            cache[path_key] = result["id"]
            with open(cache_file, "w") as f:
                json.dump(cache, f, indent=2)
            return result["id"]
        else:
            print(f"❌ 错误: {result}")
            return None

    except Exception as e:
        print(f"❌ 异常: {e}")
        return None

def sync_directory_to_notion(dir_path: Path, parent_id: str = None) -> dict:
    """同步目录到 Notion"""
    page_cache = {}

    # 获取目录下的所有 md 文件
    md_files = sorted(dir_path.rglob("*.md"))

    for md_file in md_files:
        relative_path = md_file.relative_to(ROOT_DIR)

        # 跳过 README.md 作为目录入口
        if md_file.name == "README.md":
            continue

        page_id = sync_file_to_notion(md_file, parent_id, page_cache)
        if page_id:
            page_cache[str(relative_path)] = page_id

    return page_cache

def get_or_create_root_page() -> str:
    """获取或创建根页面"""
    root_readme = ROOT_DIR / "README.md"

    # 检查缓存
    cache_file = ROOT_DIR / ".notion_cache.json"
    if cache_file.exists():
        with open(cache_file, "r") as f:
            cache = json.load(f)
        if "root" in cache:
            return cache["root"]

    # 读取 README
    with open(root_readme, "r", encoding="utf-8") as f:
        content = f.read()

    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    title = title_match.group(1) if title_match else "Growth-Skill 知识库"

    # 创建根页面
    result = create_page(
        NOTION_DATABASE_ID or "",
        "database_id" if NOTION_DATABASE_ID else "page_id",
        title,
        content
    )

    if "id" in result:
        root_id = result["id"]
        cache = {}
        if cache_file.exists():
            with open(cache_file, "r") as f:
                cache = json.load(f)
        cache["root"] = root_id
        with open(cache_file, "w") as f:
            json.dump(cache, f, indent=2)
        return root_id

    raise Exception(f"无法创建根页面: {result}")

def main():
    if not NOTION_TOKEN:
        print("❌ 错误: 请设置 NOTION_API_KEY 环境变量")
        print("   export NOTION_API_KEY='your_token'")
        return

    print("🚀 开始同步到 Notion...")
    print(f"📁 根目录: {ROOT_DIR}")
    print()

    # 创建根页面
    root_id = get_or_create_root_page()
    print(f"✅ 根页面创建成功: {root_id}")
    print()

    # 定义目录结构和名称
    sections = [
        ("growth-schools", "增长流派体系"),
        ("cases", "案例库"),
        ("weapons", "增长武器库"),
        ("modules", "模块知识"),
        ("guides", "操作指南"),
    ]

    # 同步每个主要目录
    for dir_name, display_name in sections:
        dir_path = ROOT_DIR / dir_name
        if dir_path.exists():
            print(f"\n📂 同步 {display_name}...")

            # 为每个子目录创建父页面
            for subdir in sorted(dir_path.iterdir()):
                if subdir.is_dir():
                    # 创建子目录页面
                    subdir_title = subdir.name.replace("-", " ").replace("_", " ").title()
                    print(f"  📄 创建子目录: {subdir_title}")

                    subdir_md = subdir / "01-overview.md"
                    if subdir_md.exists():
                        sync_file_to_notion(subdir_md, root_id)

                    # 同步目录下的其他 md 文件
                    for md_file in sorted(subdir.glob("*.md")):
                        if md_file.name != "01-overview.md":
                            sync_file_to_notion(md_file, root_id)

                    # 如果是 cases 目录，还有子目录
                    if dir_name == "cases":
                        for subsubdir in sorted(subdir.iterdir()):
                            if subsubdir.is_dir():
                                subsubdir_title = subsubdir.name.replace("-", " ").replace("_", " ").title()
                                print(f"    📄 创建子子目录: {subsubdir_title}")
                                for md_file in sorted(subsubdir.glob("*.md")):
                                    sync_file_to_notion(md_file, root_id)

            # 同步根目录下的 md 文件
            for md_file in sorted(dir_path.glob("*.md")):
                sync_file_to_notion(md_file, root_id)

    print("\n✅ 同步完成!")
    print(f"💡 提示: 已创建的页面ID缓存在 .notion_cache.json 文件中")

if __name__ == "__main__":
    main()
