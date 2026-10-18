"""Versioned local knowledge provider. Retrieved documents are data, never instructions."""
import csv
import hashlib
import io
import json
import re
import shutil
import sqlite3
import zipfile
from contextlib import closing,contextmanager
from pathlib import Path, PurePosixPath
from typing import Protocol
from PIL import Image
import jieba
from .config import DATA

KNOWLEDGE=DATA/'knowledge'
INDEX=KNOWLEDGE/'index.db'
BLOCKED=('P4-', '90-待审核', '99-历史归档', '来源研究底稿')

class KnowledgeSource(Protocol):
    def search(self, query: str, product_id: str='', category: str='') -> list: ...
    def document(self, doc_id: str) -> dict | None: ...
    def images(self, product_id: str) -> list: ...
    def status(self) -> dict: ...

def tokenize(text):
    return ' '.join(x.lower() for x in jieba.cut(text[:100000]) if re.search(r'[\w\u4e00-\u9fff]',x))

def stable(value): return hashlib.sha256(value.encode()).hexdigest()[:24]


def price_product_name(name):
    """Use verified catalog aliases only; never match a model as a substring."""
    aliases={'HUAWEI MateBook Pro':'HUAWEI MateBook Pro（鸿蒙版）'}
    return re.sub(r'\s+', '', aliases.get(name.strip(), name.strip())).casefold()

def import_zip(source: Path) -> dict:
    """Validate before activation; old versions and their assets remain addressable."""
    KNOWLEDGE.mkdir(parents=True,exist_ok=True)
    if source.stat().st_size>300_000_000:raise ValueError('知识包超过导入大小限制')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    version='v7-'+digest[:12]
    final=KNOWLEDGE/'raw'/version
    archive=KNOWLEDGE/'archive'/f'{digest}.zip'
    archive.parent.mkdir(parents=True,exist_ok=True)
    if not archive.exists(): shutil.copy2(source,archive)
    staging=KNOWLEDGE/'staging'/version
    staging.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        entries=z.infolist()
        if not entries:raise ValueError('知识包为空')
        if len(entries)>10000 or sum(x.file_size for x in entries)>300_000_000:
            raise ValueError('知识包超过导入大小限制')
        roots={PurePosixPath(x.filename).parts[0] for x in entries}
        if len(roots)!=1: raise ValueError('知识包需要一个顶层目录')
        root=next(iter(roots))+'/'
        for x in entries:
            name=x.filename
            parts=PurePosixPath(name).parts
            if name.startswith(('/', '\\')) or '..' in parts or ':' in name or '\\' in name:
                raise ValueError('知识包包含不安全路径')
            if (x.external_attr>>16)&0o170000==0o120000: raise ValueError('不接受符号链接')
            if x.is_dir(): continue
            if Path(name).suffix.lower() not in {'.md','.csv','.json','.png','.jpg','.jpeg','.webp'}:
                raise ValueError('知识包包含不支持的格式')
        rows=list(csv.DictReader(io.StringIO(z.read(root+'全库文件清单_SHA256.csv').decode('utf-8-sig'))))
        files=[x.filename for x in entries if not x.is_dir()]
        if len(set(name.casefold() for name in files))!=len(files):raise ValueError('知识包存在重复文件路径')
        expected={root+row['相对路径'] for row in rows}
        if len(expected)!=len(rows) or set(files)!=(expected|{root+'全库文件清单_SHA256.csv'}):raise ValueError('知识包存在未校验文件或清单缺失文件')
        for row in rows:
            content=z.read(root+row['相对路径'])
            if hashlib.sha256(content).hexdigest()!=row['SHA256'] or len(content)!=int(row['字节数']):
                raise ValueError('知识包文件校验失败：'+row['相对路径'])
        for x in entries:
            if x.is_dir(): continue
            dest=staging/x.filename[len(root):]
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(z.read(x))
    if not final.exists():
        final.parent.mkdir(parents=True,exist_ok=True)
        staging.rename(final)
    build=KNOWLEDGE/'index.build.db'
    if build.exists(): build.unlink()
    c=sqlite3.connect(build)
    c.executescript('''
      CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
      CREATE TABLE documents(id TEXT PRIMARY KEY,path TEXT,title TEXT,category TEXT,product_id TEXT,body TEXT,sha256 TEXT,urls TEXT,version TEXT);
      CREATE TABLE chunks(id TEXT PRIMARY KEY,doc_id TEXT,heading TEXT,body TEXT);
      CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED,doc_id UNINDEXED,body);
      CREATE TABLE products(id TEXT PRIMARY KEY,name TEXT,path TEXT,facts_id TEXT,summary TEXT);
      CREATE TABLE images(id TEXT PRIMARY KEY,product_id TEXT,path TEXT,name TEXT,url TEXT,source TEXT,description TEXT,width INTEGER,height INTEGER,version TEXT);
      CREATE TABLE prices(id TEXT PRIMARY KEY,body TEXT);
    ''')
    fact_paths=sorted(final.glob('P1-产品参数库/0[12]-*/*/产品事实.md'))
    products=[]
    for fp in fact_paths:
        rel=fp.relative_to(final).as_posix(); body=fp.read_text(encoding='utf-8-sig')
        name=body.splitlines()[0].lstrip('# ').split(' - 产品事实')[0].strip()
        pid=stable(rel.rsplit('/',1)[0]); did=stable(version+':'+rel)
        p={'id':pid,'name':name,'path':rel.rsplit('/',1)[0],'facts_id':did,'summary':body[:500]}
        products.append(p)
        c.execute('INSERT INTO products VALUES(?,?,?,?,?)',tuple(p.values()))
    docs=0;chunks=0
    for fp in sorted(final.rglob('*.md')):
        rel=fp.relative_to(final).as_posix()
        if any(x in rel for x in BLOCKED) or '/' not in rel: continue
        body=fp.read_text(encoding='utf-8-sig'); did=stable(version+':'+rel)
        category=rel.split('/')[0].split('-')[0]
        pid=next((p['id'] for p in products if rel.startswith(p['path']+'/')),'')
        title=next((l.lstrip('# ') for l in body.splitlines() if l.startswith('#')),fp.stem)
        urls=list(dict.fromkeys(re.findall(r'https?://[^\s)<>`]+',body)))[:30]
        c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)',(did,rel,title,category,pid,body,hashlib.sha256(fp.read_bytes()).hexdigest(),json.dumps(urls),version))
        docs+=1
        for i,section in enumerate(re.split(r'(?m)(?=^## )',body)):
            for j in range(0,len(section),1800):
                segment=section[max(0,j-150):j+1800]
                if not segment.strip():continue
                cid=f'{did}-{i}-{j}';heading=section.splitlines()[0][:160]
                c.execute('INSERT INTO chunks VALUES(?,?,?,?)',(cid,did,heading,segment))
                c.execute('INSERT INTO search VALUES(?,?,?)',(cid,did,tokenize(title+' '+segment)))
                chunks+=1
    indexed=0
    for p in products:
        folder=final/p['path']
        for idx in folder.rglob('图片索引.csv'):
            for r in csv.DictReader(io.StringIO(idx.read_text(encoding='utf-8-sig'))):
                filename=r.get('文件名',''); matches=list(idx.parent.rglob(filename)) if filename else []
                matches=[x for x in matches if x.is_file() and x.suffix.lower() in {'.png','.jpg','.jpeg','.webp'}]
                if not matches: raise ValueError('图片索引缺少文件：'+filename)
                fp=matches[0]; rel=fp.relative_to(final).as_posix();iid=stable(version+':'+rel)
                with Image.open(fp) as image: width,height=image.size;image.verify()
                c.execute('INSERT OR IGNORE INTO images VALUES(?,?,?,?,?,?,?,?,?,?)',(iid,p['id'],str(fp),filename,r.get('原始图片URL',''),r.get('来源页面',''),r.get('官网图片说明',r.get('画面说明','')),width,height,version))
                indexed+=1
    # Include every image in the global catalog, including extended products.
    joint=final/'P1-产品参数库'/'00-全库横向索引'/'全部图片联合检索表.csv'
    for r in csv.DictReader(io.StringIO(joint.read_text(encoding='utf-8-sig'))):
        folder=final/r['本地目录'];matches=[x for x in folder.rglob(r['文件名']) if x.is_file()]
        if not matches:raise ValueError('全库图片缺失：'+r['文件名'])
        fp=matches[0];rel=fp.relative_to(final).as_posix();iid=stable(version+':'+rel)
        pid=next((p['id'] for p in products if rel.startswith(p['path']+'/')),stable(r['本地目录']))
        with Image.open(fp) as image:width,height=image.size
        c.execute('INSERT OR IGNORE INTO images VALUES(?,?,?,?,?,?,?,?,?,?)',(iid,pid,str(fp),r['文件名'],r.get('原始图片URL',''),r.get('页面来源',''),r.get('画面说明',''),width,height,version))
    for fp in final.glob('P1-产品参数库/08-*/官方价格快照.csv'):
        for i,r in enumerate(csv.DictReader(io.StringIO(fp.read_text(encoding='utf-8-sig')))):
            c.execute('INSERT INTO prices VALUES(?,?)',(str(i),json.dumps(r,ensure_ascii=False)))
    report={'source':'local_zip','version':version,'archive_sha256':digest,'documents':docs,'chunks':chunks,'products':len(products),'images':c.execute('SELECT count(*) FROM images').fetchone()[0],'checked_files':len(rows),'ima_connected':False}
    for k,v in report.items():c.execute('INSERT INTO meta VALUES(?,?)',(k,json.dumps(v)))
    c.commit();c.close()
    # Keep prior index for historical references and preserve old raw assets.
    if INDEX.exists():
        with closing(sqlite3.connect(INDEX)) as previous:
            row=previous.execute("SELECT value FROM meta WHERE key='version'").fetchone()
            old_version=json.loads(row[0]) if row else 'previous'
            # Version strings are generated by this importer, never paths from input.
            old_version=re.sub(r'[^a-zA-Z0-9_-]','_',old_version)
            with closing(sqlite3.connect(KNOWLEDGE/f'index-{old_version}.db')) as saved:previous.backup(saved)
    build.replace(INDEX)
    (KNOWLEDGE/'import-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

class LocalKnowledge:
    def historical_row(self,table,identifier):
        for index in sorted(KNOWLEDGE.glob('index-*.db'),reverse=True)+list(KNOWLEDGE.glob('index.previous.db')):
            with closing(sqlite3.connect(index.as_uri()+'?mode=ro',uri=True)) as c:
                c.row_factory=sqlite3.Row
                row=c.execute(f'SELECT * FROM {table} WHERE id=?',(identifier,)).fetchone()
                if row:return dict(row)
        return None
    @contextmanager
    def connect(self):
        if not INDEX.exists(): raise ValueError('请先导入知识库')
        c=sqlite3.connect(INDEX);c.row_factory=sqlite3.Row
        try:yield c
        finally:c.close()
    def status(self):
        if not INDEX.exists():return {'source':'local_zip','ready':False,'ima_connected':False}
        with self.connect() as c:return {**{r['key']:json.loads(r['value']) for r in c.execute('SELECT * FROM meta')},'ready':True}
    def products(self):
        with self.connect() as c:
            out=[dict(x) for x in c.execute('SELECT * FROM products ORDER BY name')]
        for p in out:
            imgs=self.images(p['id']);p['cover']=f'/api/knowledge/images/{imgs[0]["id"]}' if imgs else None
        return out
    def product(self,pid):
        with self.connect() as c:
            row=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
            if not row:return None
            p=dict(row);p['facts']=self.document(p['facts_id']);p['images']=self.images(pid)
            docs=[dict(x) for x in c.execute('SELECT id,title,category FROM documents WHERE product_id=?',(pid,))]
            p['documents']=docs
            prices=[json.loads(x['body']) for x in c.execute('SELECT body FROM prices')]
            p['prices']=[r for r in prices if price_product_name(r.get('规范产品名称',''))==price_product_name(p['name'])]
            return p
    def document(self,did):
        if did.startswith('ima-doc-'):
            from .ima import document
            return document(did)
        with self.connect() as c:
            row=c.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
            if row:return {**dict(row),'urls':json.loads(row['urls'])}
        row=self.historical_row('documents',did)
        return {**row,'urls':json.loads(row['urls'])} if row else None
    def images(self,pid):
        with self.connect() as c:return [{k:v for k,v in dict(r).items() if k!='path'} for r in c.execute('SELECT * FROM images WHERE product_id=? ORDER BY name',(pid,))]
    def image_path(self,iid):
        if iid.startswith('ima-img-'):
            from .ima import image_path
            return image_path(iid)
        with self.connect() as c:
            row=c.execute('SELECT path FROM images WHERE id=?',(iid,)).fetchone()
        if not row:row=self.historical_row('images',iid)
        return Path(row['path']) if row else None
    def search(self,query,pid='',category=''):
        # Normalize common spelling/spacing aliases without choosing a system or SKU.
        query=re.sub(r'(?i)(?<![a-z])(?:mate\s*book|mb)\s*(d\s*)?(\d{1,2})',lambda m:'MateBook '+('D ' if m[1] else '')+m[2],query)
        words=list(dict.fromkeys(tokenize(query).split()))[:20]
        with self.connect() as c:
            if not words:return []
            expr=' OR '.join('"'+x.replace('"','')+'"' for x in words)
            sql='SELECT d.*, ch.body AS excerpt, bm25(search) AS rank FROM search JOIN chunks ch ON ch.id=search.id JOIN documents d ON d.id=ch.doc_id WHERE search MATCH ?'
            # Matrices are navigation aids, never returned as fact evidence.
            sql+=" AND d.path NOT LIKE '%/00-全库横向索引/%'"
            args=[expr]
            if pid:sql+=' AND (d.product_id=? OR d.product_id="")';args.append(pid)
            if category:sql+=' AND d.category=?';args.append(category)
            rows=c.execute(sql+" ORDER BY CASE WHEN d.product_id<>'' THEN 0 ELSE 1 END, rank LIMIT 30",args).fetchall()
            found={}
            for row in rows:
                if row['id'] not in found:found[row['id']]={k:v for k,v in dict(row).items() if k not in {'body','rank'}}
            return list(found.values())[:8]

knowledge: KnowledgeSource=LocalKnowledge()


def work_images(content,brief):
    if content.get('source_type')=='ima':
        from .ima import load_snapshot
        return load_snapshot(content.get('source_snapshot',''),brief['product_id'])[0]['images']
    return knowledge.images(brief['product_id'])
