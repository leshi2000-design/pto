"""Веб-доступ (прототип): чтение и правка карточки «Монтаж ГСВ» для веб-клиента — клиент, объект, оборудование, подписи.
Работает с теми же таблицами, что и окно программы; номер договора, смета, папка, статусы и суммы веб-клиентом не меняются."""
from datetime import date

from . import gsvm_domain as md
from . import gsvm_statuses
from .gsv_domain import EQUIPMENT_KINDS, save_client
from .gsv_project_domain import join_phones, parse_phones

LOCK_PREFIX = 'gsvm'


def search(db, query='', limit=100):
    """Договоры для списка: [{id, number, date, client, phone, object, address, statuses, signed}], свежие сверху."""
    where, params = ['1=1'], []
    q = str(query or '').strip().casefold()
    if q:
        where.append("LOWER(coalesce(c.contract_number,'')||' '||coalesce(c.client_name,'')||' '||coalesce(c.party_name,'')||' '||coalesce(c.object_name,'')||' '||coalesce(c.object_address,'')||' '||coalesce(c.client_phone,'')) LIKE ?")
        params.append(f'%{q}%')
    cur = db.execute(f"""SELECT c.id,c.contract_number,c.contract_date,coalesce(nullif(c.client_name,''),c.party_name,''),coalesce(c.client_phone,''),coalesce(c.object_name,''),
        coalesce(c.object_address,''),coalesce(c.statuses_text,''),coalesce(c.contract_signed,0),coalesce(c.act_signed,0) FROM contracts c WHERE {' AND '.join(where)}
        ORDER BY coalesce(c.year_num,0) DESC, coalesce(c.seq_num,0) DESC, c.id DESC LIMIT ?""", (*params, int(limit)))
    keys = ('id', 'number', 'date', 'client', 'phone', 'object', 'address', 'statuses', 'signed', 'act_signed')
    return [dict(zip(keys, r)) for r in cur.fetchall() if not (r[1] or '').startswith('Резерв')]


def get_card(db, cid):
    cur = db.execute('SELECT * FROM contracts WHERE id=?', (cid,))
    row = cur.fetchone()
    if not row:
        return None
    c = dict(zip([x[0] for x in cur.description], row))
    client = None
    if c.get('client_id'):
        cur = db.execute('SELECT name,phone,address,passport,passport_issuer,passport_date FROM crm.clients WHERE id=?', (c['client_id'],))
        r = cur.fetchone()
        client = dict(zip(('name', 'phone', 'address', 'passport', 'passport_issuer', 'passport_date'), r)) if r else None
    legal = bool(c.get('le_client_id'))
    if client is None:
        client = dict(name=c.get('client_name') or c.get('party_name') or '', phone=c.get('client_phone') or '', address=c.get('client_address') or '',
                      passport=c.get('passport_series_number') or '', passport_issuer=c.get('passport_issued_by') or '', passport_date=c.get('passport_issue_date') or '')
    return dict(id=c['id'], number=c.get('contract_number') or '', date=c.get('contract_date') or '', object=c.get('object_name') or '', object_address=c.get('object_address') or '',
                notes=c.get('notes') or '', signed=bool(c.get('contract_signed')), act_signed=bool(c.get('act_signed')), amount=c.get('contract_amount') or 0, client=client,
                client_id=c.get('client_id'), legal=legal, party_name=c.get('party_name') or '', statuses=gsvm_statuses.contract_statuses(db, cid), equipment=md.equipment(db, cid),
                work_start=c.get('work_start_date') or '', work_end=c.get('work_end_date') or '')


def copy_text(db, cid):
    """Текст «Скопировать данные клиента» (как кнопка в окне программы)."""
    card = get_card(db, cid)
    if not card:
        return ''
    client = dict(card['client'])
    if card['legal']:
        row = db.fetchone('SELECT name,legal_address,phone FROM le_clients WHERE id=(SELECT le_client_id FROM contracts WHERE id=?)', (cid,))
        if row:
            client.update(name=row[0], address=row[1] or '', phone=row[2] or '', passport='', passport_issuer='', passport_date='')
    return md.client_copy_text(client, card['equipment'], card['object_address'])


def phones_from_lines(text):
    """Телефоны из многострочного поля (по одному в строке; можно «номер (пояснение)») → строка договора «номер (пояснение); номер»."""
    return join_phones(parse_phones('\n'.join(line for line in str(text or '').splitlines() if line.strip())))


def phones_to_lines(text):
    return '\n'.join(f'{p} ({n})' if n else p for p, n in parse_phones(text))


def save_card(db, cid, values, equipment_rows=()):
    """Сохраняет разрешённые поля. values: client_name, phones (многострочно), client_address, passport, passport_issuer, passport_date, object, object_address, notes, signed, act_signed.
    equipment_rows: [{id|None, kind, model, serial, note, delete}]. Возвращает карточку после сохранения. Бросает ValueError с понятным текстом."""
    card = get_card(db, cid)
    if not card:
        raise ValueError('Договор не найден')
    pdate = str(values.get('passport_date') or '').strip()
    if pdate:
        try:
            date.fromisoformat(pdate)
        except ValueError:
            raise ValueError('Дата выдачи паспорта: формат ГГГГ-ММ-ДД') from None
    with db.transaction():
        fields = dict(object_name=str(values.get('object') or '').strip(), object_address=str(values.get('object_address') or '').strip(), notes=str(values.get('notes') or '').strip(),
                      contract_signed=int(bool(values.get('signed'))), act_signed=int(bool(values.get('act_signed'))))
        if not card['legal']:
            name = str(values.get('client_name') or '').strip()
            if not name:
                raise ValueError('Введите ФИО клиента')
            client = dict(name=name, phone=phones_from_lines(values.get('phones')), address=str(values.get('client_address') or '').strip(), passport=str(values.get('passport') or '').strip(),
                          passport_issuer=str(values.get('passport_issuer') or '').strip(), passport_date=pdate)
            client_id = save_client(db, client, card['client_id'])
            fields.update(client_id=client_id, client_name=client['name'], client_phone=client['phone'], client_address=client['address'], passport_series_number=client['passport'],
                          passport_issued_by=client['passport_issuer'], passport_issue_date=client['passport_date'])
        db.execute('UPDATE contracts SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?', (*fields.values(), cid))
        _save_equipment(db, cid, equipment_rows)
    return get_card(db, cid)


def _save_equipment(db, cid, rows):
    """Правка оборудования по id: существующее обновляется (файл паспорта сохраняется), новое добавляется, отмеченное — удаляется."""
    existing = {r['id'] for r in md.equipment(db, cid)}
    for r in rows:
        kind, model, serial, note = (str(r.get(k) or '').strip() for k in ('kind', 'model', 'serial', 'note'))
        rid = r.get('id')
        if rid:
            if int(rid) not in existing:
                raise ValueError('Оборудование не относится к этому договору')
            if r.get('delete'):
                db.execute('DELETE FROM gsvm_equipment WHERE id=? AND contract_id=?', (int(rid), cid))
            else:
                if not kind:
                    raise ValueError('Укажите тип оборудования')
                db.execute('UPDATE gsvm_equipment SET kind=?,model=?,serial=?,note=? WHERE id=? AND contract_id=?', (kind, model, serial, note, int(rid), cid))
        elif kind or model or serial or note:
            if not kind:
                raise ValueError('Укажите тип оборудования (в строке «' + (model or serial or note) + '»)')
            db.execute('INSERT INTO gsvm_equipment(contract_id,kind,model,serial,note,file_path) VALUES(?,?,?,?,?,?)', (cid, kind, model, serial, note, ''))


EQUIPMENT_CHOICES = list(EQUIPMENT_KINDS)
