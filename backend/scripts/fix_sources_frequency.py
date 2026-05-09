#!/usr/bin/env python3
"""
一次性数据修复脚本：修复 sources、frequency、question_position 不一致问题（无需全量重建）
修复内容：
1. sources 中重复 URL 去重（保留最具体的 company/round）
2. sources 中移除指向已删除面经的条目
3. 重算 frequency = len(cleaned_sources)
4. 为缺失 question_position 记录的 QB 行补全关联（BUG-008）

用法：
    python fix_sources_frequency.py              # 执行修复
    python fix_sources_frequency.py --dry-run    # 仅预览，不写入
"""
import json
import sqlite3
import sys
import time
import shutil
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "interview-boss.db")


def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("=== DRY RUN 模式（不会修改数据库）===\n")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if not dry_run:
        # 备份
        backup = f"{DB_PATH}.bak.fix-{int(time.time())}"
        shutil.copy2(DB_PATH, backup)
        print(f"已备份: {backup}")

    # 获取已删除面经 URL 集合
    deleted_urls = set()
    for r in conn.execute("SELECT DISTINCT url FROM interview WHERE deleted_at IS NOT NULL"):
        if r['url']:
            deleted_urls.add(r['url'])
    print(f"已删除面经 URL: {len(deleted_urls)} 个")

    fixed_dedup = 0
    fixed_stale = 0
    fixed_freq = 0
    fixed_position = 0

    rows = conn.execute("SELECT id, frequency, sources, job_position FROM question_bank").fetchall()

    # 预加载 job_positions 映射
    pos_map = {}
    for r in conn.execute("SELECT id, name FROM job_positions"):
        pos_map[r['name']] = r['id']

    # 预加载已有 question_position 映射
    existing_qp = set()
    for r in conn.execute("SELECT question_id, position_id FROM question_position"):
        existing_qp.add((r['question_id'], r['position_id']))

    for r in rows:
        try:
            sources = json.loads(r['sources']) if r['sources'] else []
        except Exception:
            sources = []

        changed = False

        # 1. 按 URL 去重，保留最具体的 company/round
        seen_urls = set()
        deduped = []
        for s in sources:
            url = s.get('url', '')
            if url in seen_urls:
                fixed_dedup += 1
                for existing in deduped:
                    if existing['url'] == url:
                        if existing['company'] in ('', '未提供') and s['company'] not in ('', '未提供'):
                            existing['company'] = s['company']
                        if existing['round'] in ('', '未提供') and s['round'] not in ('', '未提供'):
                            existing['round'] = s['round']
                        break
            else:
                seen_urls.add(url)
                deduped.append(s)
        if len(deduped) != len(sources):
            changed = True
        sources = deduped

        # 2. 移除指向已删除面经的条目
        before = len(sources)
        sources = [s for s in sources if s.get('url') not in deleted_urls]
        removed = before - len(sources)
        if removed:
            fixed_stale += removed
            changed = True
            if dry_run and removed > 0:
                print(f"  [DRY] QB#{r['id']}: 移除 {removed} 条过期 source")

        # 3. 重算 frequency
        new_freq = len(sources)
        if r['frequency'] != new_freq:
            fixed_freq += 1
            changed = True
            if dry_run:
                print(f"  [DRY] QB#{r['id']}: frequency {r['frequency']} -> {new_freq}")

        if changed and not dry_run:
            conn.execute(
                "UPDATE question_bank SET frequency = ?, sources = ? WHERE id = ?",
                (new_freq, json.dumps(sources, ensure_ascii=False), r['id'])
            )

        # 4. 补全缺失的 question_position
        jb_pos = r['job_position'] if 'job_position' in r.keys() else ''
        if jb_pos and jb_pos in pos_map:
            pos_id = pos_map[jb_pos]
            if (r['id'], pos_id) not in existing_qp:
                fixed_position += 1
                if dry_run:
                    print(f"  [DRY] QB#{r['id']}: 补全 question_position (position={jb_pos}, pos_id={pos_id})")
                else:
                    conn.execute(
                        "INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)",
                        (r['id'], pos_id)
                    )
                    existing_qp.add((r['id'], pos_id))

    if not dry_run:
        conn.commit()
    conn.close()

    print(f"\n修复完成{'（DRY RUN）' if dry_run else ''}:")
    print(f"  sources URL 去重: {fixed_dedup} 处")
    print(f"  sources 移除已删除面经: {fixed_stale} 条")
    print(f"  frequency 修正: {fixed_freq} 条")
    print(f"  question_position 补全: {fixed_position} 条")


if __name__ == "__main__":
    main()
