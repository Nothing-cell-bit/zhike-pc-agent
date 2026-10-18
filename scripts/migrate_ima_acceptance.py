"""Add selected acceptance works to the original DB without replacing existing rows."""
import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def connect(path):
    c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    c.row_factory=sqlite3.Row
    return c


def sha(blob):return hashlib.sha256(blob).hexdigest()
def ident(value):return '"'+value.replace('"','""')+'"'


def knowledge_row(folder,table,identifier):
    indexes=[folder/'knowledge/index.db',*sorted((folder/'knowledge').glob('index-*.db'))]
    for path in indexes:
        if not path.exists():continue
        with connect(path) as c:
            row=c.execute('SELECT * FROM '+ident(table)+' WHERE id=?',(identifier,)).fetchone()
            if row:return dict(row)
    raise ValueError('本地知识引用缺失，停止迁移：'+identifier)


def dependencies(source,target,contents):
    copies={};checked_snapshots=set()
    def add(relative):
        relative=Path(relative);src=(source/relative).resolve();dst=(target/relative).resolve()
        if not src.is_relative_to(source) or not dst.is_relative_to(target):raise ValueError('迁移文件越界')
        if not src.is_file():raise ValueError('来源文件缺失：'+str(relative))
        blob=src.read_bytes()
        if dst.exists() and sha(dst.read_bytes())!=sha(blob):raise ValueError('来源文件冲突：'+str(relative))
        copies[str(relative)]=(src,dst,sha(blob))
        return blob
    for content in contents:
        if content.get('source_type')=='ima':
            sid=content.get('source_snapshot','')
            if not re.fullmatch(r'[a-f0-9]{32}',sid):raise ValueError('ima 快照编号无效')
            if sid in checked_snapshots:continue
            checked_snapshots.add(sid)
            snapshot=json.loads(add(Path('ima/snapshots')/(sid+'.json')))
            for ref in snapshot['sources']:
                if not re.fullmatch(r'ima-doc-[a-f0-9]{32}',ref['id']):raise ValueError('ima 资料编号无效')
                record=json.loads(add(Path('ima/records')/(ref['id']+'.json')))
                if sha(record['document']['body'].encode())!=ref['sha256']:raise ValueError('ima 文档完整性失败')
            for image in snapshot['product']['images']:
                if not re.fullmatch(r'ima-img-[a-f0-9]{32}',image['id']):raise ValueError('ima 图片编号无效')
                record=json.loads(add(Path('ima/records')/(image['id']+'.json')))
                if not re.fullmatch(r'[a-f0-9]{64}\.(png|jpg|webp)',record['object']):raise ValueError('ima 图片文件名无效')
                blob=add(Path('ima/objects')/record['object'])
                if sha(blob)!=image['sha256']:raise ValueError('ima 图片完整性失败')
        else:
            for ref in content.get('sources',[]):
                original=knowledge_row(target,'documents',ref['id'])
                if original['sha256']!=ref['sha256']:raise ValueError('本地资料哈希冲突')
            for image in content.get('images',[]):
                a=knowledge_row(source,'images',image['id']);b=knowledge_row(target,'images',image['id'])
                if sha(Path(a['path']).read_bytes())!=sha(Path(b['path']).read_bytes()):raise ValueError('本地图片哈希冲突')
    return copies,checked_snapshots


def migrate(source,target,work_ids,dry_run=False):
    source=Path(source).resolve();target=Path(target).resolve();wanted=set(work_ids)
    if source==target or not wanted:raise ValueError('请选择独立的来源与目标数据库')
    with connect(source/'store.db') as src:
        for folder in [source,target]:
            with connect(folder/'store.db') as c:
                if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('数据库完整性异常')
                if c.execute("SELECT count(*) FROM jobs WHERE status IN ('running','queued')").fetchone()[0]:raise ValueError('仍有运行中的任务，停止迁移')
        rows={t:[] for t in ['works','work_versions','jobs','audit','assets']}
        rows['works']=[dict(r) for r in src.execute('SELECT * FROM works') if r['id'] in wanted]
        if {r['id'] for r in rows['works']}!=wanted:raise ValueError('指定作品不完整')
        for work in rows['works']:
            if json.loads(work['report']).get('status')!='passed':raise ValueError('验收作品尚未通过模型核验')
        rows['work_versions']=[dict(r) for r in src.execute('SELECT * FROM work_versions') if r['work_id'] in wanted]
        for work in rows['works']:
            versions=[r for r in rows['work_versions'] if r['work_id']==work['id']]
            if sorted(v['version'] for v in versions)!=list(range(1,work['version']+1)):raise ValueError('作品版本链不完整')
            final=next(v for v in versions if v['version']==work['version'])
            if final['content']!=work['content'] or final['report']!=work['report']:raise ValueError('最终版本与作品不一致')
        rows['jobs']=[dict(r) for r in src.execute('SELECT * FROM jobs') if r['target_id'] in wanted or json.loads(r['result']).get('work_id') in wanted]
        related=wanted|{r['id'] for r in rows['jobs']}
        rows['audit']=[dict(r) for r in src.execute('SELECT * FROM audit') if r['target'] in related]
        rows['assets']=[dict(r) for r in src.execute('SELECT * FROM assets') if json.loads(r['metadata_json']).get('work_id') in wanted]
    contents=[json.loads(r['content']) for r in rows['works']+rows['work_versions']]
    copies,snapshots=dependencies(source,target,contents)
    for asset in rows['assets']:
        path=Path(asset['path']).resolve()
        if path.is_relative_to(target):continue
        if not path.is_relative_to(source/'assets'):raise ValueError('作品资产不在来源资产目录内')
        relative=path.relative_to(source);destination=target/relative
        if destination.exists() and sha(destination.read_bytes())!=sha(path.read_bytes()):raise ValueError('作品资产文件冲突')
        copies[str(relative)]=(path,destination,sha(path.read_bytes()));asset['path']=str(destination)
    c=sqlite3.connect(target/'store.db',isolation_level=None);c.row_factory=sqlite3.Row
    try:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT count(*) FROM jobs WHERE status IN ('running','queued')").fetchone()[0]:raise ValueError('出现运行中的任务，停止迁移')
        users={r[0] for r in c.execute('SELECT id FROM users')}
        if any(r.get('actor_id') and r['actor_id'] not in users for entries in rows.values() for r in entries):raise ValueError('原库缺少作品所属账号，不自动复制账号或密码')
        tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        originals={t:[dict(r) for r in c.execute('SELECT * FROM '+ident(t))] for t in tables}
        counts={t:len(r) for t,r in originals.items()};inserted={t:0 for t in rows}
        for table,entries in rows.items():
            columns=[r[1] for r in c.execute('PRAGMA table_info('+ident(table)+')')]
            for row in entries:
                if set(columns)!=set(row):raise ValueError('来源与目标表结构不一致：'+table)
                old=c.execute('SELECT * FROM '+ident(table)+' WHERE id=?',(row['id'],)).fetchone()
                if old:
                    if dict(old)!=row:raise ValueError('原有记录冲突，不覆盖：'+table+'/'+row['id'])
                    continue
                c.execute('INSERT INTO '+ident(table)+' ('+','.join(map(ident,columns))+') VALUES ('+','.join('?' for _ in columns)+')',[row[k] for k in columns]);inserted[table]+=1
        for table,entries in originals.items():
            keys=[r[1] for r in c.execute('PRAGMA table_info('+ident(table)+')') if r[5]]
            if not keys:raise ValueError('原表缺少主键，无法证明记录保留')
            for row in entries:
                current=c.execute('SELECT * FROM '+ident(table)+' WHERE '+' AND '.join(ident(k)+'=?' for k in keys),[row[k] for k in keys]).fetchone()
                if not current or dict(current)!=row:raise ValueError('原有数据发生变化，回滚迁移')
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or c.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('迁移完整性验证失败')
        after={t:c.execute('SELECT count(*) FROM '+ident(t)).fetchone()[0] for t in tables}
        report={'dry_run':dry_run,'source':str(source),'target':str(target),'work_ids':sorted(wanted),'inserted':inserted,'before_counts':counts,'after_counts':after,'original_rows_unchanged':True,'ima_snapshots':len(snapshots),'files':len(copies),'integrity':'ok'}
        if dry_run:c.execute('ROLLBACK');return report
        for src,dst,expected in copies.values():
            dst.parent.mkdir(parents=True,exist_ok=True)
            if not dst.exists():
                temporary=dst.with_name(dst.name+'.migrating');shutil.copyfile(src,temporary)
                if sha(temporary.read_bytes())!=expected:raise ValueError('复制文件完整性失败')
                temporary.replace(dst)
            if sha(dst.read_bytes())!=expected:raise ValueError('目标文件完整性失败')
        c.execute('COMMIT');return report
    except Exception:
        if c.in_transaction:c.execute('ROLLBACK')
        raise
    finally:c.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dry-run',action='store_true');args=parser.parse_args()
    manifest=json.loads((ROOT/'data/acceptance/ima-20261018-v4/final-summary.json').read_text(encoding='utf-8'))
    work_ids=[x['work_id'] for x in manifest['final_cases']]
    if not args.dry_run:
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup_root=ROOT/'data/backups';backup_root.mkdir(exist_ok=True)
        backups=[]
        for name,folder in [('original',ROOT/'data'),('acceptance',ROOT/'tmp/ima-live-data')]:
            path=backup_root/f'ima-migration-{stamp}-{name}.db'
            with connect(folder/'store.db') as src,sqlite3.connect(path) as target:src.backup(target)
            backups.append(str(path))
    report=migrate(ROOT/'tmp/ima-live-data',ROOT/'data',work_ids,args.dry_run)
    if not args.dry_run:
        report['backups']=backups
        output=ROOT/'data/migrations'/f'ima-{stamp}.json';output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Migration report:',output)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
