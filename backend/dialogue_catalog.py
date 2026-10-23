"""Canonical products, variants and evidence shared by selection and quoting."""
import hashlib
import json
import re
from pathlib import Path
from .knowledge import knowledge
from .config import MARKETING_SOURCE
from .ima import CACHE_ROOT


def catalog_index():return [{'id':p['id'],'name':p['name']} for p in knowledge.products()]


def cached_ima_facts(product_id):
    root=CACHE_ROOT/'snapshots'
    if not root.exists():return None
    for path in sorted(root.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        try:
            snapshot=json.loads(path.read_text(encoding='utf-8'))
            if snapshot['product']['id']!=product_id:continue
            refs=snapshot['sources']
            if all(hashlib.sha256(r['excerpt'].encode()).hexdigest()==r['sha256'] for r in refs):return refs
        except (OSError,ValueError,KeyError,TypeError):continue
    return None


async def load_information(product_ids,query=''):
    """Product evidence only. No price/SKU checks or sales workflow observations."""
    ids=set(product_ids or []);sources=[];products=[];retrieval=[]
    for entry in knowledge.products():
        if entry['id'] not in ids:continue
        product=knowledge.product(entry['id']);facts=product['facts']
        refs=None
        if MARKETING_SOURCE in {'ima','ima_first'}:
            from .ima_dialogue import retrieve
            try:
                result=await retrieve(product,query)
                refs=[ref for ref in result['sources'] if ref['title'].removesuffix('.md').endswith(('产品事实','article'))]
                if not refs:raise ValueError('ima 未返回允许用于接待的产品事实')
                retrieval.append({'product_id':entry['id'],'status':result['status'],'source_type':'ima','retrieved_at':result['retrieved_at']})
            except (ValueError,TimeoutError,KeyError,TypeError,OSError):
                retrieval.append({'product_id':entry['id'],'status':'failed' if MARKETING_SOURCE=='ima' else 'fallback',
                    'source_type':'none' if MARKETING_SOURCE=='ima' else 'local_zip','message':'ima 查询未完成，待门店核实' if MARKETING_SOURCE=='ima' else 'ima 查询未完成，本轮使用本地资料'})
                if MARKETING_SOURCE=='ima':
                    products.append({'id':entry['id'],'name':entry['name']})
                    continue
        products.append({'id':entry['id'],'name':entry['name']})
        for source in refs or [facts]:
            body=source.get('excerpt',source.get('body',''))
            sources.extend(information_sections({'id':source['id'],'product_id':entry['id'],'title':source['title'],
                            'excerpt':body,'source_type':'ima' if refs else 'local_zip'}))
    return {'products':products,'sources':sources,'retrieval':retrieval}


def information_sections(source):
    """Keep a specification and its footnotes together; do not infer relationships."""
    if source.get('sectioned'):return [source]
    parts=[part.strip() for part in re.split(r'(?m)(?=^#{2,6}\s)',source['excerpt']) if part.strip()]
    output=[]
    for index,part in enumerate(parts):
        heading=part.splitlines()[0]
        paragraphs=[p.strip() for p in re.split(r'\n\s*\n',part[len(heading):]) if p.strip()]
        if len(part)<=300:groups=[part]
        else:
            groups=[];position=0
            labels={'尺寸','宽度','长度','厚度','高度','重量','类型','屏幕类型','屏占比','屏幕比例','分辨率',
                    '刷新率','亮度','峰值亮度','色域','色准','色深','对比度','触摸屏','处理器','内存','存储',
                    '硬盘','存储容量','显卡','操作系统','预装系统','接口','端口','电池','摄像头','音频','无线','蓝牙'}
            def field_label(text):return text in labels or bool(re.fullmatch(r'[\u4e00-\u9fff]{2,8}\d+',text))
            while position<len(paragraphs):
                group=[paragraphs[position]];position+=1
                # Keep every value/version and its footnotes until the next
                # field label. Windows and Linux values belong to one field.
                while position<len(paragraphs) and not field_label(paragraphs[position]):
                    group.append(paragraphs[position]);position+=1
                groups.append(heading+'\n\n'+'\n\n'.join(group))
        for subindex,excerpt in enumerate(groups):
            output.append({**source,'sectioned':True,'id':source['id']+'#'+str(index)+'.'+str(subindex),
                           'title':source['title']+' · '+heading.lstrip('# '),'excerpt':excerpt})
    return output


async def load_options(product_ids=None):
    ids=set(product_ids or []);sources=[];options=[];warnings=[]
    current=await load_information(list(ids)) if ids and MARKETING_SOURCE in {'ima','ima_first'} else None
    for entry in knowledge.products():
        if ids and entry['id'] not in ids:continue
        product=knowledge.product(entry['id']);facts=product['facts'];refs=None
        if MARKETING_SOURCE in {'ima','ima_first'}:refs=cached_ima_facts(entry['id'])
        if current is not None:
            evidence=[source for source in current['sources'] if source.get('product_id')==entry['id']]
            warnings.extend({'product_id':entry['id'],'message':item['message']} for item in current.get('retrieval',[]) if item.get('message') and item.get('product_id')==entry['id'])
        elif refs:
            evidence=[{'id':r['id'],'product_id':entry['id'],'title':r['title'],'excerpt':r['excerpt'],'source_type':'ima','sha256':r['sha256']} for r in refs]
        else:
            evidence=[{'id':facts['id'],'product_id':entry['id'],'title':facts['title'],'excerpt':facts['body'],'source_type':'local_zip','sha256':facts['sha256']}]
            if MARKETING_SOURCE in {'ima','ima_first'}:warnings.append({'product_id':entry['id'],'message':'暂无可复用的该型号 ima 原文，使用本地资料；兼容性与动态价格仍需核验'})
        sources.extend(evidence)
        rows=product.get('prices',[])
        variants=[]
        for row in rows:
            label=str(row.get('精确款式','')).strip()
            if not label:continue
            vid='v-'+hashlib.sha256((entry['id']+'|'+str(row.get('记录ID',''))+'|'+label).encode()).hexdigest()[:24]
            raw=str(row.get('页面金额（元）',''))
            try:
                from decimal import Decimal
                amount=int(Decimal(raw)*100) if raw and Decimal(raw)>0 else None
            except Exception:amount=None
            variants.append({'id':vid,'product_id':entry['id'],'name':entry['name'],'variant':label,
                             'sku_verified':bool(row.get('SKU编码')),
                             'configuration_status':'verified' if row.get('SKU编码') else 'unresolved',
                             'source_ids':[x['id'] for x in evidence],
                             'price':{'amount_minor':amount,'kind':row.get('价格类型',''),'checked_at':row.get('核验时间',''),'source_url':row.get('官方URL',''),
                                      'conditions':row.get('条件摘要',''),'state':'reference_only','source_type':'local_zip'} if amount else None})
        # A product without a verified SKU remains a product-level candidate.
        options.extend(variants or [{'id':'product-'+entry['id'],'product_id':entry['id'],'name':entry['name'],'variant':'具体配置待核对','source_ids':[x['id'] for x in evidence],'price':None}])
    return {'options':options,'sources':sources,'warnings':warnings,**({'retrieval':current.get('retrieval',[])} if current is not None else {})}
