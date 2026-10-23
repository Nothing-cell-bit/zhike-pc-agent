"""Deterministic quote preparation; model/chat numbers are never price authority."""
import json
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
from sqlalchemy import select
from .db import Session,PriceRule,QuoteQualification

class QualificationRequired(ValueError):
    def __init__(self,codes):
        self.codes=sorted(codes)
        super().__init__('优惠资格尚未核验')


def calculate(rule,quantity=1,qualifications=()):
    required={'unit_minor','currency','tax_included','fees_minor','source_id','valid_from','valid_until','approval_id','sku_ref'}
    if not required<=rule.keys():raise ValueError('报价规则缺少必需的金额口径或来源')
    if rule['currency']!='CNY' or rule['tax_included'] is not True:raise ValueError('币种或含税口径未确认')
    current=datetime.now(timezone.utc)
    start=datetime.fromisoformat(rule['valid_from']);end=datetime.fromisoformat(rule['valid_until'])
    if start.tzinfo is None or end.tzinfo is None or not start<=current<end:raise ValueError('报价规则未生效或已过期')
    for key in ('unit_minor','fees_minor'):
        if type(rule[key]) is not int or rule[key]<0:raise ValueError('金额必须为非负整数分')
    if not rule['unit_minor'] or not rule['source_id'] or not rule['approval_id'] or not str(rule['sku_ref']).strip():raise ValueError('报价销售SKU、来源或批准记录不完整')
    configuration_label=rule.get('configuration_label','')
    if not isinstance(configuration_label,str) or len(configuration_label)>180:raise ValueError('销售配置说明格式无效')
    if type(quantity) is not int or not 1<=quantity<=rule.get('max_quantity',1):raise ValueError('数量超出授权范围')
    components=rule.get('components',[])
    if rule.get('level')=='L3':
        if not isinstance(components,list) or not 1<=len(components)<=20:raise ValueError('套装须有完整商品与服务明细')
        for item in components:
            if not isinstance(item,dict) or not str(item.get('sku_ref','')).strip() or not str(item.get('name','')).strip():raise ValueError('套装组件须有名称和SKU或服务编号')
            if type(item.get('quantity')) is not int or not 1<=item['quantity']<=1000 or type(item.get('unit_minor')) is not int or item['unit_minor']<0:raise ValueError('套装组件数量或金额无效')
        if sum(item['quantity']*item['unit_minor'] for item in components)!=rule['unit_minor']:raise ValueError('套装明细合计与套装单价不一致')
    if not set(rule.get('qualifications_required',[]))<=set(qualifications):raise QualificationRequired(set(rule['qualifications_required'])-set(qualifications))
    base=rule['unit_minor']*quantity;total=base+rule['fees_minor'];steps=[]
    discounts=rule.get('discounts',[])
    if len(discounts)>1 and rule.get('stacking_confirmed') is not True:raise ValueError('优惠叠加规则未确认')
    for discount in discounts:
        if discount.get('qualification') and discount['qualification'] not in qualifications:raise QualificationRequired({discount['qualification']})
        if discount.get('kind')=='fixed':
            if discount.get('scope') not in {'quote','unit'}:raise ValueError('固定优惠按台或按单的口径未确认')
            if type(discount.get('amount_minor')) is not int or discount['amount_minor']<0:raise ValueError('优惠金额须为非负整数分')
            amount=discount['amount_minor']*(quantity if discount['scope']=='unit' else 1)
        elif discount.get('kind')=='rate':
            if discount.get('basis') not in {'base','remaining'} or discount.get('rounding')!='half_up':raise ValueError('优惠基数或取整规则未确认')
            bps=discount['basis_points']
            if type(bps) is not int or not 0<=bps<=10000:raise ValueError('优惠比例无效')
            basis=base if discount['basis']=='base' else total
            amount=int((Decimal(basis)*Decimal(bps)/10000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            if 'cap_minor' in discount:
                if type(discount['cap_minor']) is not int or discount['cap_minor']<0:raise ValueError('优惠上限须为非负整数分')
                amount=min(amount,discount['cap_minor'])
        else:raise ValueError('不支持的优惠计算方式')
        if type(amount) is not int or amount<0 or amount>total:raise ValueError('优惠金额超出有效范围')
        total-=amount;steps.append({'rule_id':discount['id'],'deduction_minor':amount})
    return {'unit_minor':rule['unit_minor'],'quantity':quantity,'fees_minor':rule['fees_minor'],'total_minor':total,
            'currency':'CNY','steps':steps,'valid_until':rule['valid_until'],'source_id':rule['source_id'],'approval_id':rule['approval_id'],'sku_ref':rule['sku_ref'],
            **({'is_demo':True} if rule.get('is_demo') is True else {}),
            **({'configuration_label':configuration_label.strip()} if configuration_label.strip() else {}),
            **({'components':[{k:item[k] for k in ('sku_ref','name','quantity','unit_minor')} for item in components]} if rule.get('level')=='L3' else {})}


def prepare_quotes(options,quantity=1,customer_id=''):
    output=[]
    with Session() as s:
        qualifications=[q.qualification for q in s.scalars(select(QuoteQualification).where(QuoteQualification.customer_id==customer_id)) if datetime.fromisoformat(q.valid_until)>datetime.now(timezone.utc)] if customer_id else []
        for option in options:
            rules=list(s.scalars(select(PriceRule).where(PriceRule.product_id==option['product_id'],PriceRule.variant_id==option['id'],PriceRule.status.in_(['draft','approved']))))
            groups={}
            for stored in rules:
                payload=json.loads(stored.payload)
                groups.setdefault(payload.get('level','L1'),[]).append((stored,payload))
            for level,entries in (groups or {'L1':[]}).items():
                eligible=[];blockers=[];missing_qualifications=set()
                for stored,payload in entries:
                    if stored.status!='approved':
                        blockers.append('该类报价规则仍待复核批准');continue
                    if not stored.approved_by or stored.approved_by==stored.author_id:
                        blockers.append('报价规则尚未经独立复核');continue
                    try:eligible.append((stored,calculate(payload,quantity,qualifications)))
                    except QualificationRequired as error:
                        blockers.append(str(error));missing_qualifications.update(error.codes)
                    except (ValueError,KeyError,TypeError) as error:blockers.append(str(error))
                base={'option_id':option['id'],'product_id':option['product_id'],'variant':option['variant'],'quantity':quantity,'level':level}
                if len(eligible)==1:
                    stored,computed=eligible[0]
                    if computed.get('configuration_label'):base['variant']=computed['configuration_label']
                    output.append({**base,**computed,'id':'quote-'+stored.id+'-'+str(quantity),'state':'ready_for_review','rule_id':stored.id})
                else:
                    status='needs_approval' if entries and all(r.status=='draft' for r,_ in entries) else 'needs_qualification' if missing_qualifications else 'needs_configuration' if option.get('sku_verified') is False else 'needs_price'
                    output.append({**base,'id':'quote-'+option['id']+'-'+level,'state':status,'total_minor':None,
                                   'required_qualifications':sorted(missing_qualifications),
                                   'blockers':['同类方案存在多份冲突的有效报价规则'] if len(eligible)>1 else blockers or (['该候选尚缺已核实的销售SKU、价格和有效期'] if option.get('sku_verified') is False else ['缺少已核验的门店价格与有效期']),
                                   'reference':option.get('price')})
    return output
