"""Fail closed when a merge history cannot prove every participant's scope."""

import json


def register_history_visibility(conn, user_id):
    # Read-only lookups are cached for the duration of the enclosing transaction.
    owners = {}

    def allowed(owner):
        return owner is None or (type(owner) is int and owner == user_id)

    def visible(survivor, merged_json, pre_json, post_json):
        try:
            merged = json.loads(merged_json or '[]')
            snapshots = [json.loads(value or '{}') for value in (pre_json, post_json)]
            if not isinstance(merged, list) or not all(type(qid) is int for qid in merged):
                return 0
            if not all(isinstance(snapshot, dict) for snapshot in snapshots):
                return 0
            participants = {survivor, *merged}
            recorded = {}
            for snapshot in snapshots:
                if 'owner_id' in snapshot and not allowed(snapshot['owner_id']):
                    return 0
                manifest = snapshot.get('participant_owners', {})
                if snapshot and 'owner_id' not in snapshot:
                    if not isinstance(manifest, dict) or not {str(qid) for qid in participants}.issubset(manifest):
                        return 0
                if not isinstance(manifest, dict):
                    return 0
                for key, owner in manifest.items():
                    if not allowed(owner):
                        return 0
                    if key in recorded and recorded[key] != owner:
                        return 0
                    recorded[key] = owner
            for qid in participants:
                if qid not in owners:
                    owners[qid] = conn.execute('SELECT owner_id FROM question_bank WHERE id=?', (qid,)).fetchone()
                current = owners[qid]
                if current is not None:
                    if not allowed(current['owner_id']):
                        return 0
                elif str(qid) not in recorded:
                    return 0
            return 1
        except (TypeError, ValueError):
            return 0

    conn.create_function('merge_history_visible', 4, visible)
