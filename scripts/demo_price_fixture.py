"""User-authorized demonstration rules; never import into a live database."""
import json
import sqlite3
from datetime import datetime,timedelta,timezone
from pathlib import Path


async def seed_demo_prices(root,folder):
    from backend.config import DATA
    from backend.db import Session,PriceRule,engine
    from backend.dialogue_catalog import load_options
    database=Path(engine.url.database).resolve()
    if database.is_relative_to((root/'data').resolve()) or DATA.resolve().is_relative_to((root/'data').resolve()):
        raise ValueError('演示规则禁止写入正式数据目录')
    if not DATA.name.startswith('dialogue-natural-'):raise ValueError('仅允许本次隔离模拟库')
    # Test sales SKUs live in a private copy of the catalog. Product facts are
    # copied unchanged; neither the shared knowledge index nor real SKUs change.
    from backend import knowledge as kb
    demo_index=DATA/'demo-catalog.db'
    with sqlite3.connect(kb.INDEX.as_uri()+'?mode=ro',uri=True) as original,sqlite3.connect(demo_index) as copied:
        original.backup(copied)
        names=copied.execute("select name from products where name like '%MateBook X Pro%'").fetchall()
        demo_skus=[]
        for (name,) in names:
            for cpu in ['Ultra 7 155H','Ultra 9 185H']:
                label='演示SKU：'+cpu+' / 32GB / 1TB / Windows 11家庭版（虚构销售组合）'
                key='DEMO-XPRO-'+cpu.split()[1]
                row={'规范产品名称':name,'精确款式':label,'SKU编码':key,'记录ID':key,'价格类型':'演示测试，非门店售价','页面金额（元）':''}
                copied.execute('insert into prices(id,body) values(?,?)',(key,json.dumps(row,ensure_ascii=False)))
                demo_skus.append(row)
        copied.commit()
    kb.INDEX=demo_index
    (folder/'演示销售SKU.json').write_text(json.dumps(demo_skus,ensure_ascii=False,indent=2),encoding='utf-8')
    options=(await load_options())['options']
    current=datetime.now(timezone.utc)
    rules=[]
    with Session() as session:
        for option in options:
            for level in ['L1','L2','L3','L4']:
                payload={'level':level,'sku_ref':'DEMO-'+option['id'],'unit_minor':1599900,'fees_minor':0,'currency':'CNY','tax_included':True,
                    'max_quantity':3,'source_id':'DEMO-ONLY-USER-AUTHORISED','approval_id':'DEMO-REVIEW-'+level,
                    'valid_from':(current-timedelta(minutes=1)).isoformat(),'valid_until':(current+timedelta(days=1)).isoformat(),
                    'is_demo':True,'qualifications_required':[]}
                if 'MateBook X Pro' in option['name']:
                    payload['configuration_label']=option['variant'] if option['variant'].startswith('演示SKU：') else '演示SKU：Ultra 7 155H / 32GB / 1TB / Windows 11家庭版（虚构销售组合）'
                if level=='L2':payload['discounts']=[{'id':'DEMO-OFFER','kind':'fixed','scope':'unit','amount_minor':50000}]
                if level=='L3':
                    payload['unit_minor']=1629800
                    payload['components']=[{'sku_ref':payload['sku_ref'],'name':'演示电脑配置','quantity':1,'unit_minor':1599900},
                                           {'sku_ref':'DEMO-MOUSE','name':'演示鼠标','quantity':1,'unit_minor':29900}]
                if level=='L4':payload['unit_minor']=1499900
                approved=level!='L4'
                session.add(PriceRule(product_id=option['product_id'],variant_id=option['id'],payload=json.dumps(payload,ensure_ascii=False),
                    author_id='demo-author',approved_by='demo-reviewer' if approved else '',status='approved' if approved else 'draft'))
                rules.append({'product_id':option['product_id'],'option_id':option['id'],'name':option['name'],'variant':option['variant'],
                              'level':level,'status':'approved' if approved else 'draft','payload':payload})
        session.commit()
    (folder/'演示价格规则.json').write_text(json.dumps(rules,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'演示报价说明.md').write_text('# 演示报价数据\n\n用户明确授权为本次隔离测试生成，不是门店或官方售价。对目录内各候选采用同一演示价组，目的仅为验证流程，不用于判断真实产品性价比。\n\n'
        '| 类型 | 演示规则 | 状态 |\n|---|---|---|\n| L1 | 每台含税15999元，附加费0 | 演示复核通过 |\n| L2 | L1每台减500元，15499元，无额外资格要求 | 演示复核通过 |\n| L3 | 电脑15999元+鼠标299元，合计16298元 | 演示复核通过 |\n| L4 | 专项演示申请，金额仅在内部测试数据记录 | 待审批，不可对客发送 |\n\n'
        '全部SKU以DEMO开头。知识库索引复制到隔离目录，仅增加X Pro的Ultra 7/9、32GB、1TB、Windows 11两个虚构销售组合；产品事实原文保持不变，不表示真实在售组合。价格规则仅写入独立临时数据库；未填造游戏或软件实测结果。\n',encoding='utf-8')
    return len(rules)
