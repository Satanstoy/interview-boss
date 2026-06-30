"""
业务查询函数 — 从 connection.py 拆分而来

包含岗位管理、动态频率计算、分类体系等跨领域查询。
"""
import json
import logging

from app.core.prompts import DEFAULT_TAXONOMY

logger = logging.getLogger("interview-boss")


def get_current_job_position() -> str:
    """从 user_profile 读取当前岗位（全局 fallback），fallback 到默认值"""
    from app.db.connection import get_db_connection
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT value FROM user_profile WHERE key = 'current_job_position'").fetchone()
            if row and row['value']:
                return row['value']
    except Exception:
        pass
    return DEFAULT_TAXONOMY["job_position"]


def get_user_job_position(user_id: int) -> tuple[int | None, str]:
    """获取用户的当前岗位：返回 (position_id, position_name)

    优先级：users.personal_position → users.current_position_id → 全局 fallback
    """
    from app.db.connection import get_db_connection
    default_name = DEFAULT_TAXONOMY["job_position"]
    try:
        with get_db_connection() as conn:
            # 最高优先：用户个人岗位（不关联 job_positions 表）
            row = conn.execute(
                "SELECT personal_position FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row and row['personal_position']:
                return None, row['personal_position']

            # 次优先：users.current_position_id → job_positions.name
            row = conn.execute(
                "SELECT u.current_position_id, jp.name FROM users u "
                "LEFT JOIN job_positions jp ON u.current_position_id = jp.id "
                "WHERE u.id = ?", (user_id,)
            ).fetchone()
            if row and row['current_position_id'] and row['name']:
                return row['current_position_id'], row['name']

            # fallback: 全局设置
            pos_row = conn.execute("SELECT value FROM user_profile WHERE key = 'current_job_position'").fetchone()
            if pos_row and pos_row[0]:
                jp_row = conn.execute("SELECT id FROM job_positions WHERE name = ?", (pos_row[0],)).fetchone()
                return (jp_row[0] if jp_row else None), pos_row[0]
    except Exception:
        pass
    return None, default_name


def get_dynamic_frequency_sql(bank_mode: str, user_id: int, table_alias: str = "qb") -> str:
    """根据 bank_mode 返回动态计算频率的 SQL 子查询片段。

    频率 = question_sources 表中匹配当前模式的面试记录数量。
    - public:   只统计 owner_id IS NULL 的面试
    - personal: 统计 owner_id IS NULL 或 owner_id = user_id 的面试
    - mixed:    统计 owner_id IS NULL 或 owner_id = user_id 的面试
    """
    prefix = f"{table_alias}." if table_alias else ""
    owner_filter = {
        'personal': f"AND (i.owner_id IS NULL OR i.owner_id = {user_id})",
        'mixed': f"AND (i.owner_id IS NULL OR i.owner_id = {user_id})",
        'public': "AND i.owner_id IS NULL",
    }[bank_mode]

    return (
        f"(SELECT COUNT(*) FROM question_sources qs "
        f"JOIN interview i ON qs.url = i.url "
        f"WHERE qs.question_bank_id = {prefix}id "
        f"AND i.deleted_at IS NULL {owner_filter})"
    )


def get_taxonomy_for_position(position: str = None, user_id: int = None) -> dict:
    """从 taxonomy 表读取岗位分类配置，fallback 链: 用户个人分类 → 系统默认分类 → 常量

    Args:
        position: 岗位名称
        user_id: 用户ID（用于获取个人分类）
    """
    from app.db.connection import get_db_connection
    if position is None:
        position = get_current_job_position()
    try:
        with get_db_connection() as conn:
            # 1. 优先查找用户个人分类
            if user_id:
                row = conn.execute(
                    "SELECT categories_json FROM taxonomy WHERE position_name = ? AND source = 'user' AND owner_id = ?",
                    (position, user_id)
                ).fetchone()
                if row and row['categories_json']:
                    return {"job_position": position, "categories": json.loads(row['categories_json'])}

            # 2. 查找系统默认分类
            row = conn.execute(
                "SELECT categories_json FROM taxonomy WHERE position_name = ? AND source = 'system'",
                (position,)
            ).fetchone()
            if row and row['categories_json']:
                return {"job_position": position, "categories": json.loads(row['categories_json'])}

            # 3. fallback 到默认行
            row2 = conn.execute(
                "SELECT position_name, categories_json FROM taxonomy WHERE is_default = 1"
            ).fetchone()
            if row2 and row2['categories_json']:
                return {"job_position": row2['position_name'], "categories": json.loads(row2['categories_json'])}
    except Exception:
        pass
    # 4. 最终 fallback 到代码常量
    return DEFAULT_TAXONOMY


def save_taxonomy_for_position(position_name: str, categories: list, source: str = 'system', owner_id: int = None):
    """UPSERT taxonomy 到 taxonomy 表

    Args:
        position_name: 岗位名称
        categories: 分类列表
        source: 来源 ('system' 或 'user')
        owner_id: 用户ID (仅 user 来源时需要)
    """
    from app.db.connection import get_db_connection
    with get_db_connection() as conn:
        categories_json = json.dumps(categories, ensure_ascii=False)
        if owner_id is not None:
            # owner_id 不为 NULL 时，ON CONFLICT 正常工作
            conn.execute(
                "INSERT INTO taxonomy (position_name, categories_json, source, owner_id, updated_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(position_name, source, owner_id) DO UPDATE SET "
                "categories_json = excluded.categories_json, updated_at = CURRENT_TIMESTAMP",
                (position_name, categories_json, source, owner_id)
            )
        else:
            # owner_id 为 NULL 时，SQLite 的 ON CONFLICT 不匹配 NULL，需要先 UPDATE 再 INSERT
            cur = conn.execute(
                "UPDATE taxonomy SET categories_json = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE position_name = ? AND source = ? AND owner_id IS NULL",
                (categories_json, position_name, source)
            )
            if cur.rowcount == 0:
                conn.execute(
                    "INSERT INTO taxonomy (position_name, categories_json, source, owner_id, updated_at) "
                    "VALUES (?, ?, ?, NULL, CURRENT_TIMESTAMP)",
                    (position_name, categories_json, source)
                )
        conn.commit()


def filter_sources_by_mode(sources_list: list, bank_mode: str, user_id: int) -> list:
    """根据 bank_mode 过滤 sources 列表，只保留当前模式可见的来源。

    Deprecated: 使用 question_bank_sources.get_sources_filtered() 代替（SQL 级过滤）。
    """
    from app.db.connection import get_db_connection
    if not sources_list:
        return []
    urls = [s.get('url') for s in sources_list if s.get('url')]
    if not urls:
        return sources_list
    with get_db_connection() as conn:
        placeholders = ','.join(['?'] * len(urls))
        rows = conn.execute(
            f"SELECT url, owner_id FROM interview WHERE url IN ({placeholders}) AND deleted_at IS NULL",
            urls
        ).fetchall()
    url_owner = {r['url']: r['owner_id'] for r in rows}
    result = []
    for s in sources_list:
        owner = url_owner.get(s.get('url'))
        if bank_mode == 'personal' and owner == user_id:
            result.append(s)
        elif bank_mode == 'public' and owner is None:
            result.append(s)
        elif bank_mode == 'mixed' and (owner is None or owner == user_id):
            result.append(s)
    return result


def filter_original_question_sources_by_mode(oqs_list: list, bank_mode: str, user_id: int) -> list:
    """根据 bank_mode 过滤 original_question_sources 中每条记录的 sources 子列表。

    Deprecated: 使用 question_bank_sources.get_original_question_sources_filtered() 代替。
    """
    from app.db.connection import get_db_connection
    if not oqs_list:
        return []
    all_urls = set()
    for item in oqs_list:
        for s in item.get('sources', []):
            if s.get('url'):
                all_urls.add(s['url'])
    if not all_urls:
        return oqs_list
    with get_db_connection() as conn:
        placeholders = ','.join(['?'] * len(all_urls))
        rows = conn.execute(
            f"SELECT url, owner_id FROM interview WHERE url IN ({placeholders}) AND deleted_at IS NULL",
            list(all_urls)
        ).fetchall()
    url_owner = {r['url']: r['owner_id'] for r in rows}
    result = []
    for item in oqs_list:
        filtered_sources = []
        for s in item.get('sources', []):
            owner = url_owner.get(s.get('url'))
            if bank_mode == 'personal' and owner == user_id:
                filtered_sources.append(s)
            elif bank_mode == 'public' and owner is None:
                filtered_sources.append(s)
            elif bank_mode == 'mixed' and (owner is None or owner == user_id):
                filtered_sources.append(s)
        if filtered_sources:
            result.append({**item, 'sources': filtered_sources})
    return result
