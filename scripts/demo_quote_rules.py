"""Explicit demo catalog and four-level prices, restricted to isolated project tmp data."""
import json,sqlite3
from datetime import datetime,timedelta,timezone
from pathlib import Path


async def seed(root,author_id,reviewer_id,out):
    from backend import knowledge as kb
    from backend.config import DATA
    from backend.db import Session,PriceRule,engine
    from backend.dialogue_catalog import load_options
    root=Path(root).resolve();data=DATA.resolve();database=Path(engine.url.database).resolve()
    if not data.is_relative_to(root/'tmp') or not database.is_relative_to(data):raise ValueError('演示规则仅允许写入项目 tmp 下的独立数据目录')
    if not author_id or not reviewer_id or author_id==reviewer_id:raise ValueError('演示也需要不同的编制和复核账号')
    target=data/'demo-catalog.db'
    with sqlite3.connect(kb.INDEX.as_uri()+'?mode=ro',uri=True) as original,sqlite3.connect(target) as copied:
        original.backup(copied)
        names=copied.execute("select name from products where name like '%MateBook D 16 2024%'").fetchall()
        if len(names)!=1:raise ValueError('演示目标产品不唯一')
        name=names[0][0]
        for pid,body in copied.execute('select id,body from prices').fetchall():
            if json.loads(body).get('规范产品名称')==name:copied.execute('delete from prices where id=?',(pid,))
        for code,cpu in [('I5','i5-13420H'),('I9','i9-13900H')]:
            sku='DEMO-D16-'+code+'-16G-1T'
            record={'规范产品名称':name,'精确款式':'演示销售组合：'+cpu+' / 16GB / 1TB / Windows 11家庭版（测试SKU）','SKU编码':sku,
                    '记录ID':sku,'价格类型':'演示测试，非真实门店售价','页面金额（元）':''}
            copied.execute('insert into prices(id,body) values(?,?)',(sku,json.dumps(record,ensure_ascii=False)))
        copied.commit()
    kb.INDEX=target
    options=[o for o in (await load_options())['options'] if o['name']==name]
    now=datetime.now(timezone.utc);rules=[]
    with Session() as s:
        for option in options:
            is_i9='i9-13900H' in option['variant'];base=699900 if is_i9 else 599900
            sku='DEMO-D16-'+('I9' if is_i9 else 'I5')+'-16G-1T'
            for level in ['L1','L2','L3','L4']:
                payload={'level':level,'sku_ref':sku,'configuration_label':option['variant'],'unit_minor':base,'currency':'CNY','tax_included':True,'fees_minor':0,
                    'source_id':'DEMO-USER-AUTHORISED-20261022','approval_id':'DEMO-REVIEW-'+level,'is_demo':True,'max_quantity':3,
                    'valid_from':(now-timedelta(minutes=1)).isoformat(),'valid_until':(now+timedelta(hours=24)).isoformat(),'qualifications_required':[]}
                if level=='L2':
                    payload.update(qualifications_required=['demo_education'],discounts=[{'id':'DEMO-EDUCATION-300','kind':'fixed','scope':'unit','amount_minor':30000,'qualification':'demo_education'}])
                if level=='L3':
                    payload['unit_minor']=base+29800
                    payload['components']=[{'sku_ref':sku,'name':'演示电脑配置','quantity':1,'unit_minor':base},
                        {'sku_ref':'DEMO-MOUSE-199','name':'演示鼠标','quantity':1,'unit_minor':19900},
                        {'sku_ref':'DEMO-BAG-99','name':'演示电脑包','quantity':1,'unit_minor':9900}]
                if level=='L4':payload['unit_minor']=base-50000
                record=PriceRule(product_id=option['product_id'],variant_id=option['id'],payload=json.dumps(payload,ensure_ascii=False),author_id=author_id,
                    approved_by=reviewer_id if level!='L4' else '',status='approved' if level!='L4' else 'draft')
                s.add(record);s.flush();rules.append({'id':record.id,'product_id':option['product_id'],'variant_id':option['id'],'status':record.status,'payload':payload})
        s.commit()
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    (out/'演示四级报价规则.json').write_text(json.dumps(rules,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'演示四级报价规则.md').write_text('''# 演示四级报价规则

所有金额、销售 SKU、活动与审批记录均为用户授权的演示测试数据，不是官方或真实门店售价。只写入独立演示库。

| 级别 | i5-13420H / 16GB / 1TB | i9-13900H / 16GB / 1TB | 条件 |
|---|---:|---:|---|
| L1 单机标准 | ¥5,999 | ¥6,999 | 1–3 台，含税，额外费用 0 |
| L2 资格优惠 | ¥5,699 | ¥6,699 | 演示教育资格须由管理员核验；每台减 300，未核验时不输出金额 |
| L3 套装方案 | ¥6,297 | ¥7,297 | 电脑 + 演示鼠标 199 + 演示电脑包 99；按台组成一套 |
| L4 审批专项 | 待审批，不对客输出金额 | 待审批，不对客输出金额 | 保持草稿，独立审批后才可报价 |

有效期：每次新建演示站起 24 小时，以 JSON 中带时区的时间为准。四类为互斥备选方案，不跨级叠加。币种 CNY，全部含税，无额外费用。产品事实仍读取已有资料，演示 SKU 不构成真实在售组合或适配承诺。
''',encoding='utf-8')
    return options,rules
