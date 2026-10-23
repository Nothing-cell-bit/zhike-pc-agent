"""Program-owned work dispatch and evidence-backed deliverables, independent of prose."""
import hashlib
import json
import re
from pydantic import BaseModel,Field
from typing import Literal
from .dialogue import Evidence,valid_evidence

FACETS={
 'weight':('重量',('重量','体重','weight')),
 'resolution':('分辨率',('分辨率','像素','resolution')),
 'gamut':('色域',('色域','srgb','dci-p3','gamut')),
 'display':('屏幕类型',('屏幕','屏幕类型','display')),
 'processor':('处理器',('处理器','cpu','processor')),
 'graphics':('显卡',('显卡','gpu','graphics')),
 'memory':('内存',('内存','ram','memory')),
 'storage':('存储',('硬盘','存储','ssd','storage')),
 'os':('操作系统',('操作系统','系统版本','windows','鸿蒙','os')),
 'ports':('接口',('接口','端口','ports')),
}


class CustomerRequest(BaseModel):
    kind:Literal['answer','compare','recommend','quote']
    subject:str=Field(min_length=1,max_length=120)
    facets:list[str]=Field(default_factory=list,max_length=6)
    evidence:Evidence=Field(description='引用包含前提和条件的完整客户原句；条件询价仍可独立准备报价，但不可省略如果等限定')
    product_scope:Literal['mentioned','alternatives','any']='mentioned'


def requested_facets(query):
    text=query.casefold()
    return [key for key,(_,words) in FACETS.items() if any(word in text for word in words)]


def normalized_facets(values):
    return list(dict.fromkeys(key for value in values for key in ([value] if value in FACETS else requested_facets(value))))[:6]


def facet_excerpt(source,facet):
    body=source.get('excerpt','')
    if re.search(r'(?m)^#{1,6}\s*(?:来源|包装清单|免责声明)',body):return ''
    labels={
        'weight':{'重量','weight'},'resolution':{'分辨率','resolution'},'gamut':{'色域','gamut'},
        'display':{'类型','屏幕类型','display'},'processor':{'处理器','cpu','processor'},
        'graphics':{'显卡','gpu','graphics'},'memory':{'内存','ram','memory'},
        'storage':{'存储','硬盘','存储容量','ssd','storage'},'os':{'操作系统','预装系统','os'},
        'ports':{'接口','端口','ports'},
    }
    boundaries=set().union(*labels.values(),{'尺寸','宽度','长度','厚度','高度','刷新率','亮度','峰值亮度',
        '色准','色深','对比度','触摸屏','屏占比','屏幕比例','电池','摄像头','音频','无线','蓝牙'})
    blocks=[p.strip() for p in re.split(r'\n\s*\n',body) if p.strip()]
    normalized=[re.sub(r'^#{1,6}\s*','',p).strip().casefold() for p in blocks]
    start=next((i for i,p in enumerate(normalized) if p in labels[facet]),None)
    if start is None:
        # Some source sections put a label and its value on consecutive lines.
        match=re.search(r'(?im)^(?:'+ '|'.join(re.escape(x) for x in labels[facet])+r')\s*[:：]?\s*\n+(.+)',body,re.S)
        if match:values=[match[1].strip()]
        elif facet=='gamut':
            values=[p for p in blocks if not p.startswith(('*','#')) and re.search(r'\d+%\s*(?:sRGB|Adobe\s*RGB|P3).*色域',p,re.I)]
        else:return ''
    else:
        values=[]
        for i in range(start+1,len(blocks)):
            if normalized[i] in boundaries or blocks[i].startswith('#'):break
            values.append(blocks[i])
    text='\n\n'.join(values).strip()
    if not text:return ''
    if facet=='weight' and not re.search(r'\d+(?:\.\d+)?\s*(?:kg|g|千克|公斤|克)\b',text,re.I):return ''
    if facet=='resolution' and not re.search(r'\d{3,}\s*[×xX*（]',text):return ''
    if facet=='gamut' and not re.search(r'sRGB|Adobe\s*RGB|P3|色域.{0,10}\d+%',text,re.I):return ''
    if facet=='os' and not re.search(r'Windows|HarmonyOS|Linux|鸿蒙',text,re.I):return ''
    # Preserve source wording and footnotes; no derived suitability judgement.
    return text if len(text)<=600 else ''


def build_deliverable(kind,product_ids,facets,tools,catalog,seq):
    facets=normalized_facets(facets)
    if not facets or not product_ids:return None
    names={p['id']:p['name'] for p in catalog};cells=[]
    for pid in product_ids[:3]:
        for facet in facets:
            matches=[(source,facet_excerpt(source,facet)) for source in tools.get('source_pool',tools.get('sources',[])) if source.get('product_id')==pid]
            matches=[(s,text) for s,text in matches if text]
            source,text=min(matches,key=lambda item:len(item[1])) if matches else ({},'')
            cells.append({'product_id':pid,'facet':facet,'source_id':source.get('id',''),'quote':text,
                          'status':'sourced' if text else 'missing'})
    header=['机型']+[FACETS[f][0]+'（资料原文）' for f in facets]
    rows=[' | '.join(header),' | '.join(['---']*len(header))]
    for pid in product_ids[:3]:
        values=[]
        for facet in facets:
            cell=next(c for c in cells if c['product_id']==pid and c['facet']==facet)
            values.append(cell['quote'].replace('|','／').replace('\n','<br>') if cell['quote'] else '本轮资料未覆盖，待门店核实')
        rows.append(' | '.join([names.get(pid,pid),*values]))
    text='\n\n'+'\n'.join('| '+row+' |' for row in rows)
    if kind in {'recommend','compare'}:text+='\n\n以上为已检索规格；具体软件兼容和游戏实测表现分别核实，不以规格表保证适配。'
    ident=hashlib.sha256(json.dumps(cells,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
    return {'id':ident,'kind':kind,'product_ids':product_ids[:3],'product_names':names,'facets':facets,'cells':cells,'text':text,
            'complete':all(c['status']=='sourced' for c in cells),'created_seq':seq,'status':'ready'}


def register_requests(state,requests,messages,seq,product_ids):
    tasks=state.setdefault('tasks',[])
    for request in requests:
        if not valid_evidence(request['evidence'],messages):continue
        key='request:'+request['kind']+':'+request['evidence']['message_id']
        if any(t['key']==key or t.get('canonical_request') and t['kind']==request['kind']
               and t.get('evidence',{}).get('quote')==request['evidence']['quote'] for t in tasks):continue
        facets=normalized_facets(request.get('facets',[]))
        explicit=requested_facets(request['evidence']['quote'])
        facets=[facet for facet in facets if facet in explicit]
        if request['kind']=='answer' and not facets:continue
        if request['kind']=='compare' and not facets:facets=['weight','resolution','gamut','os']
        if request['kind']=='recommend' and not facets:facets=['os','processor','graphics','memory','weight']
        tasks.append({'id':hashlib.sha256(key.encode()).hexdigest()[:24],'key':key,'kind':request['kind'],
            'title':request['subject'][:60],'evidence':request['evidence'],'product_ids':list(product_ids),
            'required_facets':facets,'status':'ready','owner':'assistant','depends_on':[],'blockers':[],
            'created_seq':seq,'result':'','canonical_request':True,'product_scope':request.get('product_scope','mentioned')})


def ready_work(state):
    order={'quote':0,'compare':1,'recommend':2,'answer':3}
    return sorted([t for t in state.get('tasks',[]) if t.get('canonical_request') and t['status']=='ready'],
                  key=lambda t:(order.get(t['kind'],9),-t.get('created_seq',0)))


def build_turn_deliverable(kind,product_ids,facets,tools,catalog,seq,state):
    delivery=build_deliverable(kind,product_ids,facets,tools,catalog,seq)
    # A repeated recommendation with unchanged evidence is not new progress.
    # An explicit answer/comparison can legitimately request the same facts again.
    if delivery and kind=='recommend' and any(old['id']==delivery['id'] and old.get('sent_message_id')
                                                for old in state.get('deliverables',[])):
        return None
    return delivery


def public_deliverable(delivery,tasks,active_keys,action):
    """Only explicitly requested facts become customer-visible attachments."""
    if not delivery or action in {'ask','pause','wait'}:return None
    requested=[t for t in tasks if t['key'] in active_keys and
               (t['kind']=='compare' or t['kind']=='answer' and t.get('required_facets'))]
    if not requested:return None
    facets=[f for f in delivery['facets'] if any(f in t.get('required_facets',delivery['facets']) for t in requested)]
    ids=[pid for pid in delivery['product_ids'] if any(pid in t.get('product_ids',[]) for t in requested)]
    if not facets or not ids:return None
    cells=[c for c in delivery['cells'] if c['product_id'] in ids and c['facet'] in facets]
    def value(pid,facet):
        cell=next((c for c in cells if c['product_id']==pid and c['facet']==facet),{})
        return '；'.join(line.strip().lstrip('*').strip() for line in cell.get('quote','').splitlines() if line.strip()) or '待门店确认'
    if len(ids)==1:
        text='\n\n'+'\n'.join(FACETS[f][0]+'：'+value(ids[0],f) for f in facets)
    else:
        rows=[['机型',*[FACETS[f][0] for f in facets]],['---']*(len(facets)+1)]
        rows += [[delivery.get('product_names',{}).get(pid,pid),*[value(pid,f).replace('|','／') for f in facets]] for pid in ids]
        text='\n\n'+'\n'.join('| '+' | '.join(row)+' |' for row in rows)
    return {**delivery,'product_ids':ids,'facets':facets,'cells':cells,'text':text,
            'complete':bool(cells) and all(c['status']=='sourced' for c in cells)}


def meaningful_changes(personal):
    return any(c['operation']!='confirm' for c in personal.get('changes',[])) or bool(personal.get('constraints') or personal.get('clear_fields')) or personal.get('purchase_intent',{}).get('mode','unknown')!='unknown'
