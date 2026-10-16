"""Теги юрлица-заказчика для договоров, актов и справок проектов и монтажа ГСВ (реквизиты берутся из «Справочника юрлиц»)."""
FIELDS = [   # (ключ, тег, подпись)
    ('full_name', 'ЮРЛИЦО', 'Юрлицо: полное наименование'), ('name', 'ЮРЛИЦО_КРАТКО', 'Юрлицо: краткое наименование'), ('unp', 'УНП', 'Юрлицо: УНП'),
    ('okpo', 'ОКПО', 'Юрлицо: ОКПО'), ('legal_address', 'АДРЕС_ЮРИДИЧЕСКИЙ', 'Юрлицо: юридический адрес'), ('postal_address', 'АДРЕС_ПОЧТОВЫЙ', 'Юрлицо: почтовый адрес'),
    ('bank', 'БАНК', 'Юрлицо: банк'), ('bic', 'БИК', 'Юрлицо: БИК банка'), ('bank_address', 'АДРЕС_БАНКА', 'Юрлицо: адрес банка'), ('account', 'РАСЧЕТНЫЙ_СЧЕТ', 'Юрлицо: расчётный счёт'),
    ('head_position', 'ДОЛЖНОСТЬ_РУКОВОДИТЕЛЯ', 'Юрлицо: должность руководителя'), ('head_name', 'ФИО_РУКОВОДИТЕЛЯ', 'Юрлицо: ФИО руководителя'),
    ('head_position_gen', 'ДОЛЖНОСТЬ_РУКОВОДИТЕЛЯ_РОД', 'Юрлицо: должность руководителя (родительный падеж)'), ('head_name_gen', 'ФИО_РУКОВОДИТЕЛЯ_РОД', 'Юрлицо: ФИО руководителя (родительный падеж)'),
    ('head_short', 'ФИО_РУКОВОДИТЕЛЯ_СОКР', 'Юрлицо: инициалы и фамилия руководителя'), ('basis', 'ОСНОВАНИЕ', 'Юрлицо: действует на основании'),
    ('contact', 'КОНТАКТНОЕ_ЛИЦО', 'Юрлицо: контактное лицо'), ('phone', 'ТЕЛЕФОН_ЮРЛИЦА', 'Юрлицо: телефон'), ('email', 'EMAIL_ЮРЛИЦА', 'Юрлицо: e-mail'),
]
TAGS = [tag for _k, tag, _l in FIELDS]


def raw(db, legal_id):
    """{ключ: значение} реквизитов юрлица; пустые строки, если юрлица нет."""
    from .agenda_domain import short_name
    out = {k: '' for k, _t, _l in FIELDS}
    if not legal_id:
        return out
    cur = db.execute('SELECT * FROM le_clients WHERE id=?', (legal_id,))
    row = cur.fetchone()
    if not row:
        return out
    l = dict(zip([c[0] for c in cur.description], row))
    for k in out:
        out[k] = str(l.get(k) or '')
    out['full_name'] = out['full_name'] or out['name']
    out['postal_address'] = out['postal_address'] or out['legal_address'] or str(l.get('address') or '')
    out['legal_address'] = out['legal_address'] or str(l.get('address') or '')
    out['head_short'] = short_name(out['head_name']) if out['head_name'] else ''
    contact = db.fetchone('SELECT name,phone,email FROM le_contacts WHERE client_id=? ORDER BY id LIMIT 1', (legal_id,))
    out['contact'] = (contact[0] if contact and contact[0] else str(l.get('contact_person') or ''))
    if contact and contact[1]:
        out['phone'] = contact[1]
    if contact and contact[2]:
        out['email'] = contact[2]
    return out


def values(db, legal_id):
    """{ТЕГ: значение}."""
    data = raw(db, legal_id)
    return {tag: data[k] for k, tag, _l in FIELDS}
