from datetime import datetime,timedelta,timezone
import json
import pytest
from backend.quoting import calculate,prepare_quotes
from backend.db import Session,PriceRule
from .conftest import post


def rule(**changes):
    now=datetime.now(timezone.utc)
    return {'level':'L1','sku_ref':'verified-sale-sku','unit_minor':799900,'fees_minor':1000,'currency':'CNY','tax_included':True,
            'source_id':'authorised-source','approval_id':'approval-1','valid_from':(now-timedelta(hours=1)).isoformat(),
            'valid_until':(now+timedelta(hours=1)).isoformat(),'max_quantity':3,**changes}


def test_amounts_are_calculated_in_minor_units_with_explicit_discount_rules():
    r=rule(discounts=[{'id':'d','kind':'rate','basis':'base','basis_points':1000,'rounding':'half_up','cap_minor':50000}])
    assert calculate(r,2)['total_minor']==1550800
    assert calculate(r,2)['steps']==[{'rule_id':'d','deduction_minor':50000}]


@pytest.mark.parametrize('changes',[
 {'tax_included':False},{'valid_until':'2000-01-01T00:00:00+00:00'},
 {'unit_minor':1.2},{'currency':'USD'},{'approval_id':''},
 {'discounts':[{'id':'d','kind':'fixed','amount_minor':10000,'qualification':'education'}]},
 {'discounts':[{'id':'a','kind':'fixed','amount_minor':1000},{'id':'b','kind':'fixed','amount_minor':1000}]},
])
def test_incomplete_expired_or_unverified_rules_cannot_be_quoted(changes):
    with pytest.raises(ValueError):calculate(rule(**changes))


def test_only_independently_approved_exact_variant_can_produce_formal_amount(clients):
    with Session() as s:
        s.add(PriceRule(id='r',product_id='pc',variant_id='v1',author_id='author',approved_by='reviewer',status='approved',payload=json.dumps(rule())));s.commit()
    quotes=prepare_quotes([{'id':'v1','product_id':'pc','variant':'32GB/1TB'},{'id':'v2','product_id':'pc','variant':'16GB/512GB'}])
    assert quotes[0]['state']=='ready_for_review' and quotes[0]['total_minor']==800900
    assert quotes[1]['total_minor'] is None


def test_price_rule_management_requires_admin_and_independent_approval(clients):
    admin,staff,customer,_=clients
    assert staff.get('/api/admin/price-rules').status_code==403
    response=post(admin,'/admin/price-rules',{'product_id':'pc','variant_id':'v','payload':rule()})
    assert response.status_code==200
    rid=response.json()['id']
    assert post(admin,'/admin/price-rules/'+rid+'/approve').status_code==409
    assert admin.get('/api/admin/price-rules').json()[0]['status']=='draft'


def test_different_quote_levels_are_alternatives_not_conflicting_base_prices(clients):
    with Session() as s:
        for code,amount in [('L1',799900),('L2',749900)]:
            s.add(PriceRule(product_id='pc',variant_id='v',author_id='author',approved_by='reviewer',status='approved',payload=json.dumps(rule(level=code,unit_minor=amount))))
        s.commit()
    quotes=prepare_quotes([{'id':'v','product_id':'pc','variant':'32GB/1TB'}])
    assert len(quotes)==2
    assert {q['level'] for q in quotes}=={'L1','L2'}
    assert all(q['state']=='ready_for_review' for q in quotes)


def test_unapproved_special_quote_exposes_status_but_not_pending_amount(clients):
    with Session() as s:
        s.add(PriceRule(product_id='pc',variant_id='v',author_id='author',status='draft',payload=json.dumps(rule(level='L4',unit_minor=123456))));s.commit()
    result=prepare_quotes([{'id':'v','product_id':'pc','variant':'专项配置'}])[0]
    assert result['level']=='L4' and result['state']=='needs_approval'
    assert result['total_minor'] is None and '123456' not in json.dumps(result)


def test_fixed_discount_scope_is_explicit_and_changes_quantity_math():
    discount={'id':'d','kind':'fixed','amount_minor':10000}
    with pytest.raises(ValueError):calculate(rule(discounts=[discount]),2)
    assert calculate(rule(discounts=[{**discount,'scope':'quote'}]),2)['total_minor']==1590800
    assert calculate(rule(discounts=[{**discount,'scope':'unit'}]),2)['total_minor']==1580800


def test_bundle_requires_complete_components_and_matching_unit_total():
    components=[{'sku_ref':'pc','name':'电脑','quantity':1,'unit_minor':700000},
                {'sku_ref':'accessory','name':'配件','quantity':1,'unit_minor':99900}]
    bundle=rule(level='L3',components=components)
    assert calculate(bundle,2)['components']==components
    assert calculate(bundle,2)['total_minor']==1600800
    with pytest.raises(ValueError):calculate(rule(level='L3'))
    with pytest.raises(ValueError):calculate(rule(level='L3',components=components[:-1]))


@pytest.mark.parametrize('discount',[
    {'id':'d','kind':'rate','basis':'base','basis_points':1000,'rounding':'half_up','cap_minor':-1},
    {'id':'d','kind':'fixed','scope':'unit','amount_minor':True},
])
def test_invalid_discount_parameters_cannot_be_approved(discount):
    with pytest.raises(ValueError):calculate(rule(discounts=[discount]))


def test_all_four_quote_types_compute_and_keep_public_bundle_contents(clients):
    with Session() as s:
        for level in ['L1','L2','L3','L4']:
            payload=rule(level=level)
            if level=='L2':payload['discounts']=[{'id':'offer','kind':'fixed','scope':'unit','amount_minor':10000}]
            if level=='L3':payload['components']=[{'sku_ref':'pc','name':'电脑套装','quantity':1,'unit_minor':799900}]
            s.add(PriceRule(product_id='pc',variant_id='v',author_id='a',approved_by='b',status='approved',payload=json.dumps(payload)))
        s.commit()
    quotes=prepare_quotes([{'id':'v','product_id':'pc','variant':'明确销售配置','sku_verified':True}])
    assert len(quotes)==4 and all(q['state']=='ready_for_review' for q in quotes)
    assert next(q for q in quotes if q['level']=='L2')['total_minor']==790900
    assert next(q for q in quotes if q['level']=='L3')['components'][0]['sku_ref']=='pc'
