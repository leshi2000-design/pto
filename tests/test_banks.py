import pytest
from smetagaz.database import DatabaseManager
from smetagaz import banks_domain as bd, contracts_core as cc, legal_tags


@pytest.fixture
def d(tmp_path):
    d = DatabaseManager(tmp_path / 'x.db')
    d.init_db()
    yield d
    d.close()


def test_bank_registry_and_autofill(d):
    bid = bd.save(d, dict(name='ОАО «Банк»', bic='BANKBY2X', address='Минск, пр. 1'))
    with pytest.raises(ValueError):
        bd.save(d, dict(name='ОАО «Банк»', bic='BANKBY2X'))
    with pytest.raises(ValueError):
        bd.save(d, dict(name=''))
    with pytest.raises(ValueError):
        bd.save(d, dict(name='X', bic='12'))
    lid = cc.save_legal(d, dict(name='ООО Ромашка', unp='123456789', account='BY00ALFA'))
    bd.apply_to_client(d, lid, bid)
    p = cc.party(d, 'smr', dict(party_type='legal', legal_id=lid))
    assert (p['bank'], p['bic'], p['bank_address'], p['account']) == ('ОАО «Банк»', 'BANKBY2X', 'Минск, пр. 1', 'BY00ALFA')
    assert bd.listing(d)[0][6] == 1
    # изменение банка обновляет реквизиты юрлиц
    bd.save(d, dict(name='ОАО «Новый банк»', bic='BANKBY2X', address='Гомель'), bid)
    p = cc.party(d, 'smr', dict(party_type='legal', legal_id=lid))
    assert (p['bank'], p['bank_address']) == ('ОАО «Новый банк»', 'Гомель')
    tags = legal_tags.values(d, lid)
    assert tags['БАНК'] == 'ОАО «Новый банк»' and tags['АДРЕС_БАНКА'] == 'Гомель' and tags['УНП'] == '123456789'
    # теги договоров раздела содержат адрес банка
    cid = cc.save_contract(d, 'smr', dict(legal_id=lid, contract_date='2026-05-01'))
    assert cc.tag_map(d, 'smr', cid)['АДРЕС_БАНКА'] == 'Гомель'
    bd.delete(d, bid)
    assert cc.legal(d, lid)['bank'] == 'ОАО «Новый банк»' and cc.legal(d, lid)['bank_id'] is None


def test_save_legal_keeps_bank_link(d):
    bid = bd.save(d, dict(name='Банк', bic='ABCDEFGH'))
    lid = cc.save_legal(d, dict(name='ООО А', bank_id=bid))
    assert cc.legal(d, lid)['bank_id'] == bid
    cc.save_legal(d, dict(name='ООО А', bank_id=''), lid)
    assert cc.legal(d, lid)['bank_id'] is None
