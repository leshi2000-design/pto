"""Модули веб-доступа: описание каждого раздела (список, карточка, поля, вложенные строки) поверх тех же доменных функций, что и в окне программы.

Разделы: Услуги — Проекты ГСВ, Монтаж ГСВ, Монтаж ГСН, СМР (ИП), СМР (физлица); Юрлица — Справочник юрлиц, СМР (юрлица), ТО (юрлица), Прочие (юр.лица); Клиенты — Клиенты, Контакты.
Веб-клиент не меняет то, что требует особых правил программы: файлы, папки, сметы, начисления; номера новых договоров назначаются так же, как в программе."""
from datetime import date

from . import contacts_domain as cd
from . import contracts_core as cc
from . import gsn_domain as gn
from . import gsvm_domain as md
from . import section_codes
from . import web_cards as wc
from .gsv_domain import save_client

LIKE = "LOWER({expr}) LIKE ?"


class Field:
    def __init__(self, name, label, kind='text', group='', choices=None, readonly=False, new_only=False, hint='', required=False):
        self.name, self.label, self.kind, self.group = name, label, kind, group
        self.choices, self.readonly, self.new_only, self.hint, self.required = choices, readonly, new_only, hint, required


class Child:
    """Вложенные строки карточки (оборудование, акты, контактные лица): правятся вместе с карточкой."""
    def __init__(self, key, title, fields, rows, save, add_blank=2):
        self.key, self.title, self.fields, self.rows, self.save, self.add_blank = key, title, fields, rows, save, add_blank


class Module:
    def __init__(self, key, title, section, icon, columns, fields, search, load, save, blank=None, children=(), lock=None, copy=None, chips=None, can_create=True):
        self.key, self.title, self.section, self.icon = key, title, section, icon
        self.columns, self.fields, self.search, self.load, self.save = columns, fields, search, load, save
        self.blank, self.children, self.lock, self.copy, self.chips, self.can_create = blank, children, lock, copy, chips, can_create

    def heading(self, values):
        return values.get('_title') or self.title


def _f(text):
    try:
        return float(str(text or '0').replace(',', '.').replace(' ', ''))
    except ValueError:
        raise ValueError(f'«{text}» — не число') from None


def _like(q, *exprs):
    q = str(q or '').strip().casefold()
    if not q:
        return '1=1', []
    clause = ' OR '.join(f"LOWER(coalesce({e},'')) LIKE ?" for e in exprs)
    return f'({clause})', [f'%{q}%'] * len(exprs)


def _rows(db, sql, params, keys):
    return [dict(zip(keys, r)) for r in db.fetchall(sql, tuple(params))]


def _client_fields(prefix='Клиент'):
    return [Field('client_name', 'ФИО', group=prefix, required=True), Field('phones', 'Телефоны (по одному в строке; можно «номер (пояснение)»)', 'phones', prefix),
            Field('client_address', 'Адрес клиента', group=prefix), Field('passport', 'Паспорт: серия, номер', group=prefix), Field('passport_date', 'Дата выдачи', 'date', prefix),
            Field('passport_issuer', 'Кем выдан', group=prefix)]


def _client_values(db, client_id, fallback):
    row = db.fetchone('SELECT name,phone,address,passport,passport_issuer,passport_date FROM crm.clients WHERE id=?', (client_id,)) if client_id else None
    c = dict(zip(('name', 'phone', 'address', 'passport', 'passport_issuer', 'passport_date'), row)) if row else dict(fallback)
    return dict(client_name=c.get('name') or '', phones=wc.phones_to_lines(c.get('phone') or ''), client_address=c.get('address') or '', passport=c.get('passport') or '',
                passport_issuer=c.get('passport_issuer') or '', passport_date=c.get('passport_date') or '')


def _client_from_form(values):
    pdate = str(values.get('passport_date') or '').strip()
    if pdate:
        try:
            date.fromisoformat(pdate)
        except ValueError:
            raise ValueError('Дата выдачи паспорта: формат ГГГГ-ММ-ДД') from None
    name = str(values.get('client_name') or '').strip()
    if not name:
        raise ValueError('Введите ФИО клиента')
    return dict(name=name, phone=wc.phones_from_lines(values.get('phones')), address=str(values.get('client_address') or '').strip(), passport=str(values.get('passport') or '').strip(),
                passport_issuer=str(values.get('passport_issuer') or '').strip(), passport_date=pdate)


# --- МОНТАЖ ГСВ -----------------------------------------------------------------------------------------

def contracts_module():
    eq_fields = [Field('kind', 'Тип', 'select', choices=lambda db: [(k, k) for k in wc.EQUIPMENT_CHOICES]), Field('model', 'Модель'), Field('serial', 'Серийный номер'), Field('note', 'Примечание')]

    def search(db, q, limit=200):
        return [dict(id=c['id'], cols=[c['number'] or 'б/н', c['date'], c['client'], f'{c["object"]} {c["address"]}'.strip()], statuses=[s for s in c['statuses'].split(',') if s.strip()],
                     flags=('✔ договор ' if c['signed'] else '') + ('✔ акт' if c['act_signed'] else ''), phone=c['phone']) for c in wc.search(db, q, limit)]

    def load(db, cid):
        card = wc.get_card(db, cid)
        if not card:
            return None
        v = dict(_title=f'Договор № {card["number"] or "б/н"} от {card["date"]}', number=card['number'], contract_date=card['date'], object=card['object'], object_address=card['object_address'],
                 notes=card['notes'], signed=card['signed'], act_signed=card['act_signed'], _legal=card['legal'], _party=card['party_name'], _statuses=card['statuses'])
        v.update(_client_values(db, card['client_id'], card['client']))
        return v

    def rows(db, cid):
        return [dict(id=e['id'], kind=e['kind'], model=e['model'], serial=e['serial'], note=e['note']) for e in md.equipment(db, cid)]

    def save_rows(db, cid, rows_):
        wc._save_equipment(db, cid, rows_)

    def save(db, cid, values, rows_):
        if not cid:
            cid = create(db, values)
        wc.save_card(db, cid, values, rows_)
        return cid

    def create(db, values):
        client = _client_from_form(values)
        day = str(values.get('contract_date') or date.today().isoformat())
        date.fromisoformat(day)
        seq, yy, number = md.next_number(db, day)
        with db.transaction():
            client_id = save_client(db, client, None)
            return db.execute('INSERT INTO contracts(contract_number,contract_date,client_id,client_name,client_phone,seq_num,year_num,work_start_date) VALUES(?,?,?,?,?,?,?,?)',
                              (number, day, client_id, client['name'], client['phone'], seq, yy, day)).lastrowid

    fields = [Field('contract_date', 'Дата договора', 'date', 'Договор', new_only=True)] + _client_fields() + [
        Field('object', 'Объект', group='Объект'), Field('object_address', 'Адрес объекта', group='Объект'), Field('notes', 'Примечание', 'textarea', 'Объект'),
        Field('signed', 'Договор подписан', 'check', 'Объект'), Field('act_signed', 'Акт подписан', 'check', 'Объект')]
    return Module('contracts', 'Монтаж ГСВ', 'Услуги', 'contracts', ['№', 'Дата', 'Клиент', 'Объект'], fields, search, load, save, children=[Child('equipment', 'Оборудование', eq_fields, rows, save_rows)],
                  lock='gsvm', copy=wc.copy_text)


# --- ПРОЕКТЫ ГСВ ----------------------------------------------------------------------------------------

def gsv_module():
    def search(db, q, limit=200):
        clause, params = _like(q, 'pd_number', 'object_name', 'client_name', 'party_name', 'address', 'contract_number', 'phone')
        rows = db.fetchall(f"SELECT id,pd_number,object_name,coalesce(nullif(client_name,''),party_name,''),contract_number,contract_date,address,coalesce(contract_signed,0),coalesce(act_signed,0),coalesce(cost,0),phone "
                           f"FROM gsv_projects WHERE {clause} AND coalesce(reserved,0)=0 ORDER BY coalesce(year_num,0) DESC, coalesce(seq_num,0) DESC, id DESC LIMIT ?", (*params, limit))
        return [dict(id=r[0], cols=[r[1], r[2] or '', r[3], f'{r[4]} {r[5]}'.strip(), f'{r[9]:,.2f}'.replace(',', ' ')], statuses=[], flags=('✔ договор ' if r[7] else '') + ('✔ акт' if r[8] else ''), phone=r[10] or '') for r in rows]

    def load(db, pid):
        cur = db.execute('SELECT * FROM gsv_projects WHERE id=?', (pid,))
        row = cur.fetchone()
        if not row:
            return None
        p = dict(zip([c[0] for c in cur.description], row))
        v = dict(_title=f'Проект ГСВ {p["pd_number"]} · договор {p["contract_number"] or "б/н"}', object=p['object_name'] or '', address=p['address'] or '', contract_date=p['contract_date'] or '', due_date=p['due_date'] or '',
                 act_date=p['act_date'] or '', cost=p['cost'] or 0, tu_text=p['tu_text'] or '', notes=p['notes'] or '', contract_signed=bool(p['contract_signed']), act_signed=bool(p['act_signed']),
                 _legal=bool(p.get('le_client_id')), _party=p.get('party_name') or '', pd_number=p['pd_number'], contract_number=p['contract_number'])
        v.update(_client_values(db, p['client_id'], dict(name=p['client_name'], phone=p['phone'], address=p['client_address'], passport=p['passport'])))
        return v

    def save(db, pid, values, rows_):
        card = None
        if pid:
            card = db.fetchone('SELECT client_id,le_client_id FROM gsv_projects WHERE id=?', (pid,))
            if not card:
                raise ValueError('Проект не найден')
        legal = bool(card and card[1])
        for k in ('contract_date', 'due_date', 'act_date'):
            if values.get(k):
                try:
                    date.fromisoformat(values[k])
                except ValueError:
                    raise ValueError('Даты вводятся в формате ГГГГ-ММ-ДД') from None
        cost = _f(values.get('cost'))
        if cost < 0:
            raise ValueError('Стоимость не может быть отрицательной')
        with db.transaction():
            fields = dict(object_name=str(values.get('object') or '').strip(), address=str(values.get('address') or '').strip(), contract_date=values.get('contract_date') or '',
                          due_date=values.get('due_date') or '', act_date=values.get('act_date') or None, cost=cost, notes=str(values.get('notes') or '').strip(),
                          tu_text=str(values.get('tu_text') or '').strip(), contract_signed=int(bool(values.get('contract_signed'))), act_signed=int(bool(values.get('act_signed'))))
            if not legal:
                client = _client_from_form(values)
                client_id = save_client(db, client, card[0] if card else None)
                fields.update(client_id=client_id, client_name=client['name'], phone=client['phone'], passport=client['passport'], client_address=client['address'])
            if pid:
                db.execute('UPDATE gsv_projects SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?', (*fields.values(), pid))
                return pid
            raise ValueError('Новые проекты ГСВ создаются в программе (номер ПД назначается там)')

    fields = _client_fields() + [Field('object', 'Объект', group='Проект'), Field('address', 'Адрес объекта', group='Проект'), Field('tu_text', 'Технические условия', group='Проект'),
                                 Field('contract_date', 'Дата договора', 'date', 'Проект'), Field('due_date', 'Срок исполнения', 'date', 'Проект'), Field('act_date', 'Дата акта', 'date', 'Проект'),
                                 Field('cost', 'Стоимость, BYN', 'number', 'Проект'), Field('notes', 'Примечание', 'textarea', 'Проект'),
                                 Field('contract_signed', 'Договор подписан', 'check', 'Проект'), Field('act_signed', 'Акт подписан', 'check', 'Проект')]
    return Module('gsv', 'Проекты ГСВ', 'Услуги', 'gsv', ['Номер ПД', 'Объект', 'Клиент', 'Договор', 'Стоимость'], fields, search, load, save, lock='gsv', can_create=False)


# --- МОНТАЖ ГСН -----------------------------------------------------------------------------------------

def gsn_module():
    def search(db, q, limit=200):
        clause, params = _like(q, 'contract_number', 'title', 'client_name', 'address', 'phone')
        rows = db.fetchall(f"SELECT id,contract_number,contract_date,coalesce(client_name,''),coalesce(title,''),coalesce(address,''),coalesce(contract_signed,0),coalesce(act_signed,0),coalesce(contract_amount,0),phone "
                           f"FROM gsn_projects WHERE {clause} ORDER BY contract_date DESC, id DESC LIMIT ?", (*params, limit))
        return [dict(id=r[0], cols=[r[1] or 'б/н', r[2] or '', r[3], f'{r[4]} {r[5]}'.strip(), f'{r[8]:,.2f}'.replace(',', ' ')], statuses=[], flags=('✔ договор ' if r[6] else '') + ('✔ акт' if r[7] else ''), phone=r[9] or '') for r in rows]

    def load(db, pid):
        try:
            c = gn.get(db, pid)
        except ValueError:
            return None
        v = dict(_title=f'Монтаж ГСН · договор {c.get("contract_number") or "б/н"}', title=c.get('title') or '', address=c.get('address') or '', contract_number=c.get('contract_number') or '',
                 contract_date=c.get('contract_date') or '', work_start_date=c.get('work_start_date') or '', work_end_date=c.get('work_end_date') or '', act_date=c.get('act_date') or '',
                 contract_amount=c.get('contract_amount') or 0, pe_length=c.get('pe_length') or 0, steel_under_length=c.get('steel_under_length') or 0, steel_above_length=c.get('steel_above_length') or 0,
                 pressure_type=c.get('pressure_type') or '', tie_in=c.get('tie_in') or '', couplings=c.get('couplings') or 0, designer_code=c.get('designer_code') or '', designer=c.get('designer') or '',
                 tu_text=c.get('tu_text') or '', notes=c.get('notes') or '', contract_signed=bool(c.get('contract_signed')), act_signed=bool(c.get('act_signed')))
        v.update(_client_values(db, c.get('client_id'), dict(name=c.get('client_name'), phone=c.get('phone'), address=c.get('client_address'), passport=c.get('passport'),
                                                          passport_issuer=c.get('passport_issuer'), passport_date=c.get('passport_issue_date'))))
        return v

    def save(db, pid, values, rows_):
        client = _client_from_form(values)
        fields = dict(title=str(values.get('title') or '').strip(), address=str(values.get('address') or '').strip(), notes=str(values.get('notes') or '').strip(),
                      contract_number=str(values.get('contract_number') or '').strip(), contract_date=values.get('contract_date') or '', work_start_date=values.get('work_start_date') or '',
                      work_end_date=values.get('work_end_date') or '', act_date=values.get('act_date') or '', contract_amount=_f(values.get('contract_amount')), pe_length=_f(values.get('pe_length')),
                      steel_under_length=_f(values.get('steel_under_length')), steel_above_length=_f(values.get('steel_above_length')), pressure_type=values.get('pressure_type') or '',
                      tie_in=values.get('tie_in') or '', couplings=int(_f(values.get('couplings'))), designer_code=str(values.get('designer_code') or '').strip(),
                      designer=str(values.get('designer') or '').strip(), tu_text=str(values.get('tu_text') or '').strip(), contract_signed=int(bool(values.get('contract_signed'))),
                      act_signed=int(bool(values.get('act_signed'))))
        for k in ('contract_date', 'work_start_date', 'work_end_date', 'act_date'):
            if fields[k]:
                try:
                    date.fromisoformat(fields[k])
                except ValueError:
                    raise ValueError('Даты вводятся в формате ГГГГ-ММ-ДД') from None
        if not pid:
            raise ValueError('Новые договоры ГСН создаются в программе')
        client_id = db.fetchone('SELECT client_id FROM gsn_projects WHERE id=?', (pid,))[0]
        return gn.save_card(db, fields, client, client_id, pid)[0]

    fields = [Field('title', 'Наименование объекта', group='Договор', required=True), Field('address', 'Адрес объекта', group='Договор'), Field('contract_number', 'Номер договора', group='Договор'),
              Field('contract_date', 'Дата договора', 'date', 'Договор'), Field('work_start_date', 'Начало работ', 'date', 'Договор'), Field('work_end_date', 'Окончание работ', 'date', 'Договор'),
              Field('act_date', 'Дата акта', 'date', 'Договор'), Field('contract_amount', 'Стоимость, BYN', 'number', 'Договор'), Field('designer_code', 'Шифр проекта', group='Договор'),
              Field('designer', 'Проектировщик', group='Договор'), Field('tu_text', 'Технические условия', group='Договор'), Field('notes', 'Примечание', 'textarea', 'Договор'),
              Field('contract_signed', 'Договор подписан', 'check', 'Договор'), Field('act_signed', 'Акт подписан', 'check', 'Договор')] + _client_fields() + [
        Field('pe_length', 'ПЭ трубопровод, м', 'number', 'Газопровод'), Field('steel_under_length', 'Сталь подземная, м', 'number', 'Газопровод'),
        Field('steel_above_length', 'Сталь надземная, м', 'number', 'Газопровод'), Field('pressure_type', 'Тип газопровода', 'select', 'Газопровод', choices=lambda db: [('', '—')] + list(gn.PRESSURES.items())),
        Field('tie_in', 'Тип врезки', 'select', 'Газопровод', choices=lambda db: [('', '—')] + list(gn.TIE_INS.items())), Field('couplings', 'Муфт, шт', 'number', 'Газопровод')]
    return Module('gsn', 'Монтаж ГСН', 'Услуги', 'gsn', ['Номер', 'Дата', 'Клиент', 'Объект', 'Стоимость'], fields, search, load, save, lock='gsn', can_create=False)


# --- СМР / ТО / ПРОЧИЕ ДОГОВОРЫ КОНТРАГЕНТОВ ----------------------------------------------------------------

def counterparty_module(mod, section, icon):
    c = cc.cfg(mod)
    table, acts_table = c['contracts'], c['acts']
    legal_mode = mod == 'le'
    both = c['party'] == 'both'
    vat = True

    def party_choices(db, kind):
        if kind == 'legal':
            return [('', '— выберите юрлицо —')] + [(str(i), n) for i, n in db.fetchall('SELECT id,name FROM le_clients ORDER BY name')]
        return [('', '— выберите клиента —')] + [(str(i), n) for i, n in db.fetchall('SELECT id,name FROM crm.clients ORDER BY name')]

    def party_sql():
        if legal_mode:
            return "coalesce((SELECT name FROM le_clients WHERE id=c.client_id),'')"
        return "CASE WHEN c.party_type='legal' THEN coalesce((SELECT name FROM le_clients WHERE id=c.legal_id),'') ELSE coalesce((SELECT name FROM crm.clients WHERE id=c.person_id),'') END"

    def search(db, q, limit=200):
        party = party_sql()
        clause, params = _like(q, 'c.contract_number', 'c.object_name', 'c.object_address', 'c.subject', party)
        rows = db.fetchall(f"SELECT c.id,c.contract_number,c.contract_date,{party},coalesce(nullif(c.object_address,''),c.object_name,''),coalesce(c.amount,0),c.status,c.start_date,c.end_date,coalesce(c.annual,0),"
                           f"coalesce(c.status_manual,''),coalesce(c.signed,0) FROM {table} c WHERE {clause} ORDER BY coalesce(c.year_num,99) DESC, coalesce(c.seq_num,0) DESC, c.id DESC LIMIT ?", (*params, limit))
        out = []
        for r in rows:
            key = cc.display_status(dict(status=r[6], start_date=r[7], end_date=r[8], annual=r[9], status_manual=r[10]))
            out.append(dict(id=r[0], cols=[r[1] or 'б/н', r[2] or '', r[3], r[4], f'{r[5]:,.2f}'.replace(',', ' ')], statuses=[key], flags='✔ подписан' if r[11] else '', phone=''))
        return out

    def load(db, cid):
        try:
            r = cc.contract(db, mod, cid)
        except ValueError:
            return None
        kind = 'legal' if legal_mode or r.get('party_type') == 'legal' else 'person'
        v = dict(_title=f'{c["title"]} · договор № {r["contract_number"] or "б/н"}', contract_number=r['contract_number'] or '', contract_date=r['contract_date'] or '', object_name=r['object_name'] or '',
                 object_address=r['object_address'] or '', subject=r['subject'] or '', start_date=r['start_date'] or '', end_date=r['end_date'] or '', amount=r['amount'] or 0,
                 vat_included=bool(r['vat_included']), vat_rate=r['vat_rate'] if r['vat_rate'] is not None else 20, signed=bool(r['signed']), status=r['status'] or 'Действует',
                 status_manual=r.get('status_manual') or '', annual=bool(r.get('annual')), amount_from_acts=bool(r.get('amount_from_acts')), note=r['note'] or '', party_type=kind,
                 person_id=str(r.get('person_id') or ''), legal_id=str((r.get('client_id') if legal_mode else r.get('legal_id')) or ''), direction=r.get('direction') or '')
        v['_party'] = next((n for i, n in party_choices(db, kind) if i == v['legal_id' if kind == 'legal' else 'person_id']), '')
        v['_chip_keys'] = [cc.display_status(dict(status=v['status'], start_date=v['start_date'], end_date=v['end_date'], annual=v['annual'], status_manual=v['status_manual']))]
        return v

    def save(db, cid, values, rows_):
        data = dict(contract_number=str(values.get('contract_number') or '').strip(), contract_date=values.get('contract_date') or '', object_name=str(values.get('object_name') or '').strip(),
                    object_address=str(values.get('object_address') or '').strip(), subject=str(values.get('subject') or '').strip(), start_date=values.get('start_date') or '',
                    end_date=values.get('end_date') or '', amount=_f(values.get('amount')), vat_included=int(bool(values.get('vat_included'))), vat_rate=_f(values.get('vat_rate') or 20),
                    signed=int(bool(values.get('signed'))), status=values.get('status') or 'Действует', note=str(values.get('note') or '').strip(),
                    amount_from_acts=int(bool(values.get('amount_from_acts'))) if vat else 0, annual=int(bool(values.get('annual'))) if vat else 0,
                    status_manual=values.get('status_manual') or '' if vat else '')
        for k in ('contract_date', 'start_date', 'end_date'):
            if data[k]:
                try:
                    date.fromisoformat(data[k])
                except ValueError:
                    raise ValueError('Даты вводятся в формате ГГГГ-ММ-ДД') from None
        if data['status'] not in cc.STATUSES:
            raise ValueError('Неизвестный статус договора')
        if legal_mode:
            data.update(client_id=int(values.get('legal_id') or 0) or None, direction=values.get('direction') or 'Монтажные работы')
        else:
            kind = {'legal': 'legal', 'person': 'person'}.get(c['party']) or values.get('party_type') or 'person'
            data.update(party_type=kind, person_id=int(values.get('person_id') or 0) or None if kind == 'person' else None, legal_id=int(values.get('legal_id') or 0) or None if kind == 'legal' else None)
        new_id = cc.save_contract(db, mod, data, cid)
        _save_acts(db, new_id, rows_)
        return new_id

    def _save_acts(db, cid, rows_):
        for r in rows_:
            rid = r.get('id')
            if rid and r.get('delete'):
                cc.delete_act(db, mod, int(rid))
                continue
            if not rid and not any(str(r.get(k) or '').strip() for k in ('act_number', 'act_date', 'amount', 'description')):
                continue
            cc.save_act(db, mod, dict(contract_id=cid, act_number=r.get('act_number'), act_date=r.get('act_date'), amount=_f(r.get('amount')), description=r.get('description'),
                                      signed=bool(r.get('signed')), vat_included=bool(r.get('vat_included')), vat_rate=_f(r.get('vat_rate') or 0)), int(rid) if rid else None)

    def act_rows(db, cid):
        return [dict(id=a['id'], act_number=a['act_number'], act_date=a['act_date'], amount=a['amount'], description=a['description'], signed=bool(a['signed']),
                     vat_included=bool(a['vat_included']), vat_rate=a['vat_rate']) for a in cc.acts(db, mod, cid)]

    def blank(db):
        return dict(contract_date=date.today().isoformat(), vat_rate=20, status='Действует', party_type=c['party'] if c['party'] != 'both' else 'person', direction='Монтажные работы')

    group = 'Договор'
    fields = [Field('contract_number', 'Номер договора', group=group, hint='Пусто — номер назначится автоматически'), Field('contract_date', 'Дата договора', 'date', group)]
    if legal_mode:
        fields += [Field('direction', 'Направление', 'select', group, choices=lambda db: [(d, d) for d in __import__('smetagaz.legal_entities_domain', fromlist=['x']).DIRECTIONS])]
        fields += [Field('legal_id', 'Юрлицо (справочник юрлиц)', 'select', group, choices=lambda db: party_choices(db, 'legal'), required=True)]
    else:
        if both:
            fields += [Field('party_type', 'Контрагент', 'select', group, choices=lambda db: [('person', 'Физическое лицо (клиент)'), ('legal', 'Юридическое лицо')])]
        if c['party'] in ('person', 'both'):
            fields += [Field('person_id', 'Клиент', 'select', group, choices=lambda db: party_choices(db, 'person'))]
        if c['party'] in ('legal', 'both'):
            fields += [Field('legal_id', 'Юрлицо', 'select', group, choices=lambda db: party_choices(db, 'legal'))]
    fields += [Field('object_name', 'Объект', group=group), Field('object_address', 'Адрес объекта', group=group), Field('subject', 'Предмет договора', group=group),
               Field('start_date', 'Начало работ', 'date', group), Field('end_date', 'Окончание работ', 'date', group), Field('amount', 'Сумма договора, BYN', 'number', group),
               Field('vat_included', 'В сумму включён НДС', 'check', group), Field('vat_rate', 'Ставка НДС, %', 'number', group), Field('signed', 'Договор подписан', 'check', group),
               Field('status', 'Статус', 'select', group, choices=lambda db: [(s, s) for s in cc.STATUSES])]
    if vat:
        fields += [Field('status_manual', 'Визуальный статус вручную', 'select', group, choices=lambda db: [('', 'Определять автоматически')] + [(k, t) for k, t in cc.status_titles()]),
                   Field('annual', 'Годовой договор', 'check', group), Field('amount_from_acts', 'Сумма договора = сумма актов', 'check', group)]
    fields += [Field('note', 'Примечание', 'textarea', group)]
    act_fields = [Field('act_number', '№'), Field('act_date', 'Дата', 'date'), Field('amount', 'Сумма', 'number'), Field('description', 'Описание'), Field('signed', 'Подписан', 'check'),
                  Field('vat_included', 'НДС в сумме', 'check'), Field('vat_rate', 'Ставка НДС', 'number')]
    return Module(mod, c['title'], section, icon, ['№', 'Дата', 'Контрагент', 'Объект', 'Сумма'], fields, search, load, save, blank=blank,
                  children=[Child('acts', 'Акты', act_fields, act_rows, lambda db, cid, rows_: _save_acts(db, cid, rows_))], lock=('lecontract' if mod == 'le' else f'cp:{mod}'), chips='status')


# --- СПРАВОЧНИК ЮРЛИЦ -------------------------------------------------------------------------------------

def legal_module():
    keys = ['name', 'unp', 'full_name', 'legal_address', 'postal_address', 'phone', 'email', 'contact_person', 'okpo', 'bank', 'bic', 'bank_address', 'account', 'head_position', 'head_name',
            'head_position_gen', 'head_name_gen', 'basis', 'note']

    def search(db, q, limit=200):
        clause, params = _like(q, 'name', 'unp', 'contact_person', 'phone', 'legal_address', 'email')
        rows = db.fetchall(f"SELECT id,name,unp,coalesce(head_name,''),coalesce(contact_person,''),coalesce(phone,'') FROM le_clients WHERE {clause} ORDER BY name LIMIT ?", (*params, limit))
        return [dict(id=r[0], cols=[r[1], r[2] or '', r[3], r[4], r[5]], statuses=[], flags='', phone=r[5]) for r in rows]

    def load(db, lid):
        r = cc.legal(db, lid)
        if not r:
            return None
        v = {k: r.get(k) or '' for k in keys}
        v['_title'] = f'Юрлицо: {r["name"]}'
        return v

    def contact_rows(db, lid):
        return cc.contacts(db, lid)

    def save_contacts(db, lid, rows_):
        pass

    def save(db, lid, values, rows_):
        kept = []
        for r in rows_:
            rid = r.get('id')
            if rid and r.get('delete'):
                continue
            kept.append(dict(name=r.get('name'), position=r.get('position'), phone=r.get('phone'), email=r.get('email')))
        data = {k: values.get(k) or '' for k in keys}
        data['contact_person'] = next((r['name'] for r in kept if r.get('name')), data['contact_person'])
        return cc.save_legal(db, data, lid, kept)

    fields = [Field('name', 'Наименование (кратко)', group='Организация', required=True), Field('full_name', 'Полное наименование', group='Организация'), Field('unp', 'УНП', group='Организация'),
              Field('okpo', 'ОКПО', group='Организация'), Field('legal_address', 'Юридический адрес', group='Организация'), Field('postal_address', 'Почтовый адрес', group='Организация'),
              Field('phone', 'Общий телефон', group='Организация'), Field('email', 'Общий e-mail', group='Организация'), Field('bank', 'Банк', group='Банк'), Field('bic', 'БИК', group='Банк'),
              Field('bank_address', 'Адрес банка', group='Банк'), Field('account', 'Расчётный счёт', group='Банк'), Field('head_position', 'Должность руководителя', group='Руководитель'),
              Field('head_name', 'ФИО руководителя', group='Руководитель'), Field('head_position_gen', 'Должность (родительный)', group='Руководитель'),
              Field('head_name_gen', 'ФИО (родительный)', group='Руководитель'), Field('basis', 'Действует на основании', group='Руководитель'), Field('note', 'Примечание', 'textarea', 'Примечание')]
    contact_fields = [Field('name', 'ФИО'), Field('position', 'Должность'), Field('phone', 'Телефон'), Field('email', 'E-mail')]
    return Module('legal_entities', 'Справочник юрлиц', 'Юрлица', 'legal_entities', ['Наименование', 'УНП', 'Руководитель', 'Контактное лицо', 'Телефон'], fields, search, load, save,
                  children=[Child('contacts', 'Контактные лица', contact_fields, contact_rows, save_contacts)])


# --- КЛИЕНТЫ И КОНТАКТЫ -----------------------------------------------------------------------------------

def clients_module():
    def search(db, q, limit=200):
        clause, params = _like(q, 'name', 'phone', 'address', 'passport')
        rows = db.fetchall(f'SELECT id,name,coalesce(phone,\'\'),coalesce(address,\'\') FROM crm.clients WHERE {clause} ORDER BY name LIMIT ?', (*params, limit))
        return [dict(id=r[0], cols=[r[1], r[2], r[3]], statuses=[], flags='', phone=r[2]) for r in rows]

    def load(db, cid):
        row = db.fetchone('SELECT name,phone,address,passport,passport_issuer,passport_date,notes FROM crm.clients WHERE id=?', (cid,))
        if not row:
            return None
        return dict(_title=f'Клиент: {row[0]}', client_name=row[0], phones=wc.phones_to_lines(row[1]), client_address=row[2] or '', passport=row[3] or '', passport_issuer=row[4] or '',
                    passport_date=row[5] or '', notes=row[6] or '')

    def save(db, cid, values, rows_):
        client = _client_from_form(values)
        client['notes'] = str(values.get('notes') or '').strip()
        return save_client(db, client, cid)

    fields = _client_fields('Клиент') + [Field('notes', 'Примечание', 'textarea', 'Клиент')]
    return Module('clients', 'Клиенты', 'Клиенты', 'clients', ['ФИО', 'Телефоны', 'Адрес'], fields, search, load, save)


def contacts_module():
    def search(db, q, limit=200):
        return [dict(id=c['id'], cols=[('★ ' if c['favorite'] else '') + c['name'], c['organization'], c['position'], c['phone'], c['category']], statuses=[], flags='', phone=c['phone'])
                for c in cd.listing(db, q)[:limit]]

    def load(db, cid):
        c = cd.get_contact(db, cid)
        if not c:
            return None
        v = {k: c.get(k) or '' for k in ('name', 'organization', 'position', 'category', 'email', 'address', 'note')}
        v.update(phones=wc.phones_to_lines(c.get('phone') or ''), favorite=bool(c.get('favorite')), _title='Контакт: ' + c['name'])
        return v

    def save(db, cid, values, rows_):
        data = {k: values.get(k) or '' for k in ('name', 'organization', 'position', 'category', 'email', 'address', 'note')}
        data.update(phone=wc.phones_from_lines(values.get('phones')), favorite=bool(values.get('favorite')))
        if cid:
            old = cd.get_contact(db, cid)
            data.update(client_id=old['client_id'], legal_id=old['legal_id'])
        return cd.save_contact(db, data, cid)

    def blank(db):
        return dict(category='Рабочие')

    fields = [Field('name', 'Имя / ФИО', group='Контакт', required=True), Field('organization', 'Организация', group='Контакт'), Field('position', 'Должность', group='Контакт'),
              Field('category', 'Категория', 'select', 'Контакт', choices=lambda db: [(x, x) for x in cd.CATEGORIES]), Field('phones', 'Телефоны (по одному в строке)', 'phones', 'Контакт'),
              Field('email', 'E-mail', group='Контакт'), Field('address', 'Адрес', group='Контакт'), Field('note', 'Примечание', 'textarea', 'Контакт'), Field('favorite', 'Избранный', 'check', 'Контакт')]
    return Module('contacts', 'Контакты', 'Клиенты', 'contacts', ['Имя', 'Организация', 'Должность', 'Телефон', 'Категория'], fields, search, load, save, blank=blank)


def all_modules():
    mods = [gsv_module(), contracts_module(), gsn_module(), counterparty_module('ip', 'Услуги', 'ip'), counterparty_module('fl', 'Услуги', 'fl'),
            legal_module(), counterparty_module('smr', 'Юрлица', 'smr'), counterparty_module('to', 'Юрлица', 'to'), counterparty_module('le', 'Юрлица', 'le_other'),
            clients_module(), contacts_module()]
    for m in mods:
        if m.key == 'le':
            m.key = 'le_other'
    return {m.key: m for m in mods}
