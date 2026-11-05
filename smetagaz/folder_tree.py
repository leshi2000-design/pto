"""Деревья папок любой глубины (разделы справочника, папки смет, папки сертификатов): плоский обход, потомки, удаление ветки. Без зависимости от Qt."""

TABLES = {'categories': ('materials', 'category_id'), 'estimate_folders': ('estimates', 'folder_id'), 'certificate_folders': ('certificates', 'folder_id')}


def _check(table):
    if table not in TABLES:
        raise ValueError('Неизвестное дерево папок')


def children_map(db, table):
    _check(table)
    kids = {}
    for fid, name, parent in db.fetchall(f'SELECT id,name,parent_id FROM {table} ORDER BY name COLLATE NOCASE, id'):
        kids.setdefault(parent, []).append((fid, name or ''))
    return kids


def flatten(db, table):
    """[(id, название, id родителя, глубина)] — обход в глубину, подпапки сразу после своей папки. Записи с несуществующим родителем показываются как корневые; циклы не зацикливают обход."""
    kids = children_map(db, table)
    known = {fid for lst in kids.values() for fid, _n in lst}
    roots = list(kids.get(None, [])) + [(fid, n) for parent, lst in kids.items() if parent is not None and parent not in known for fid, n in lst]
    out, seen = [], set()

    def walk(fid, name, parent, depth):
        if fid in seen:
            return
        seen.add(fid)
        out.append((fid, name, parent, depth))
        for cid, cname in kids.get(fid, []):
            walk(cid, cname, fid, depth + 1)
    for fid, name in roots:
        walk(fid, name, None, 0)
    return out


def descendants(db, table, folder_id):
    """Папка и все её подпапки на любой глубине: список id (первая — сама папка)."""
    kids = children_map(db, table)
    ids, stack = [], [folder_id]
    while stack:
        cur = stack.pop()
        if cur in ids:
            continue
        ids.append(cur)
        stack.extend(cid for cid, _n in kids.get(cur, []))
    return ids


def add_folder(db, table, name, parent_id=None):
    _check(table)
    name = str(name or '').strip()
    if not name:
        raise ValueError('Введите название')
    if parent_id is not None and not db.fetchone(f'SELECT 1 FROM {table} WHERE id=?', (parent_id,)):
        raise ValueError('Родительская папка не найдена')
    return db.execute(f'INSERT INTO {table}(name,parent_id) VALUES(?,?)', (name, parent_id)).lastrowid


def delete_branch(db, table, folder_id):
    """Удаляет папку со всеми подпапками; материалы / сметы / сертификаты из них не удаляются, а остаются «без папки». Возвращает число удалённых папок."""
    _check(table)
    owner, column = TABLES[table]
    ids = descendants(db, table, folder_id)
    marks = ','.join('?' * len(ids))
    with db.transaction():
        db.execute(f'UPDATE {owner} SET {column}=NULL WHERE {column} IN ({marks})', tuple(ids))
        db.execute(f'DELETE FROM {table} WHERE id IN ({marks})', tuple(ids))
    return len(ids)
