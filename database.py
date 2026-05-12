"""
数据库层 - SQLite 本地历史记录存储
"""
import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'storyboard_history.db')


def get_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """初始化数据库表"""
    conn = get_connection()
    cursor = conn.cursor()

    # 创建主表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            product_name TEXT,
            anchor_prompt TEXT,
            storyboard_content TEXT,
            aspect_ratio TEXT DEFAULT '16:9',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 迁移旧数据：添加 aspect_ratio 列（如果不存在）
    try:
        cursor.execute("ALTER TABLE projects ADD COLUMN aspect_ratio TEXT DEFAULT '16:9'")
    except sqlite3.OperationalError:
        pass  # 列已存在

    conn.commit()
    conn.close()


def create_project(
    project_name: str,
    product_name: str = None,
    anchor_prompt: str = None,
    storyboard_content: str = None,
    aspect_ratio: str = '16:9'
) -> int:
    """创建新项目"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO projects (project_name, product_name, anchor_prompt, storyboard_content, aspect_ratio)
        VALUES (?, ?, ?, ?, ?)
    ''', (project_name, product_name, anchor_prompt, storyboard_content, aspect_ratio))

    project_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return project_id


def update_project(
    project_id: int,
    anchor_prompt: str = None,
    storyboard_content: str = None,
    aspect_ratio: str = None
):
    """更新项目内容"""
    conn = get_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if anchor_prompt is not None:
        updates.append("anchor_prompt = ?")
        params.append(anchor_prompt)

    if storyboard_content is not None:
        updates.append("storyboard_content = ?")
        params.append(storyboard_content)

    if aspect_ratio is not None:
        updates.append("aspect_ratio = ?")
        params.append(aspect_ratio)

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(project_id)
        cursor.execute(f'''
            UPDATE projects
            SET {', '.join(updates)}
            WHERE id = ?
        ''', params)

    conn.commit()
    conn.close()


def get_all_projects() -> List[Dict[str, Any]]:
    """获取所有项目列表"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, project_name, product_name, aspect_ratio, created_at, updated_at
        FROM projects
        ORDER BY updated_at DESC
    ''')

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_project(project_id: int) -> Optional[Dict[str, Any]]:
    """获取单个项目详情"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM projects WHERE id = ?', (project_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return dict(row)
    return None


def delete_project(project_id: int) -> bool:
    """删除项目"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()

    return deleted


# 初始化数据库
init_database()
