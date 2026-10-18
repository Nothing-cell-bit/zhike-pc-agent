import argparse
import json
import secrets
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
from argon2 import PasswordHasher
from sqlalchemy import select
from .config import DATA
from .db import init_db,Session,User
from .knowledge import import_zip

def backup():
    folder=DATA/'backups';folder.mkdir(exist_ok=True)
    target=folder/(datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S-%f')+'.db')
    with closing(sqlite3.connect(DATA/'store.db')) as source,closing(sqlite3.connect(target)) as dest:source.backup(dest)
    cutoff=datetime.now(timezone.utc).timestamp()-7*86400
    for old in folder.glob('*.db'):
        if old.stat().st_mtime<cutoff:old.unlink()
    return str(target)

def restore_drill(source:Path):
    """Restore into an isolated temporary database, leaving live data untouched."""
    source=source.resolve()
    if not source.is_file():raise ValueError('备份文件不存在')
    with tempfile.TemporaryDirectory(prefix='store-restore-') as folder:
        target=Path(folder)/'restored.db'
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(target)) as dest:
            src.backup(dest)
            integrity=dest.execute('PRAGMA integrity_check').fetchone()[0]
            if integrity!='ok':raise ValueError('恢复演练完整性检查失败')
            tables={name:dest.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0] for name in ['users','conversations','messages','works','jobs','followups','assets']}
    return {'backup':source.name,'integrity':integrity,'tables':tables,'live_data_unchanged':True}

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('admin');a.add_argument('--username',default='admin');a.add_argument('--password')
    i=sub.add_parser('import');i.add_argument('zip')
    sub.add_parser('backup')
    d=sub.add_parser('restore-drill');d.add_argument('backup',nargs='?')
    r=sub.add_parser('restore');r.add_argument('backup')
    args=p.parse_args();init_db()
    if args.command=='import':print(json.dumps(import_zip(Path(args.zip)),ensure_ascii=False,indent=2))
    if args.command=='admin':
        with Session() as s:
            if s.scalar(select(User).where(User.username==args.username)):raise SystemExit('账号已存在，不覆盖密码')
            password=args.password or secrets.token_urlsafe(16)
            if len(password)<10:raise SystemExit('密码至少10位')
            s.add(User(username=args.username,display_name='门店管理员',password=PasswordHasher().hash(password),role='admin'));s.commit()
            if not args.password:
                fp=DATA/'initial-admin.txt';fp.write_text(f'username={args.username}\npassword={password}\n',encoding='utf-8')
                print('随机初始密码已写入私有 data/initial-admin.txt，请登录后修改密码。')
    if args.command=='backup':print(backup())
    if args.command=='restore-drill':print(json.dumps(restore_drill(Path(args.backup or backup())),ensure_ascii=False))
    if args.command=='restore':
        src=Path(args.backup).resolve()
        if not src.is_file() or src==DATA/'store.db':raise SystemExit('请选择独立的有效备份文件')
        restore_drill(src)
        backup()
        with closing(sqlite3.connect(src)) as source,closing(sqlite3.connect(DATA/'store.db')) as target:source.backup(target)
        print('恢复完成；恢复前已备份。恢复时应停止网站。')

if __name__=='__main__':main()
