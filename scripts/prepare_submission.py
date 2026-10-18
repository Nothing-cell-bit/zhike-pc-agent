"""Build reviewed public source and a local submission desk, without network calls."""
import argparse
import hashlib
import html
import json
import os
import re
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit, quote

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {
    'README.md', 'ACCEPTANCE.md', 'spec.md', '.gitignore', '.gitattributes',
    '.env.example', 'requirements.txt', 'requirements-dev.txt', '一键准备提交.cmd',
    'Dockerfile', '.dockerignore',
}
PATTERNS = (
    'backend/*.py', 'backend/prompts/*.txt', 'tests/*.py', 'scripts/*.py',
    'scripts/*.ps1', 'scripts/*.cjs', 'frontend/src/*.tsx', 'frontend/src/*.ts', 'frontend/src/*.css',
    'frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html',
    'frontend/tsconfig.json', 'frontend/vite.config.ts', 'docs/competition/*.md',
    'docs/competition/submission.json',
    'samples/selected-works.json', 'samples/README.md',
)
LABELS = {'github_url': 'GitHub', 'modelscope_url': '魔搭',
          'description_url': '作品说明书', 'submission_url': '组委会提交入口'}


def public_files(root):
    paths = {root / name for name in TOP_FILES}
    for pattern in PATTERNS:
        paths.update(root.glob(pattern))
    selected = []
    for path in sorted(paths):
        if not path.is_file():
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('发布文件不能是外部链接：' + path.name)
        selected.append(path.relative_to(root).as_posix())
    return selected


def scan(root, files, contents=None):
    """Defense in depth: detect local secret values and common credential formats."""
    secrets = []
    for env_file in [root / '.env', *root.glob('.env.*')]:
        if not env_file.is_file() or env_file.name == '.env.example':
            continue
        for line in env_file.read_text(encoding='utf-8-sig').splitlines():
            key, sep, value = line.partition('=')
            value = value.strip().strip('\"\'')
            if sep and re.search(r'KEY|TOKEN|SECRET|PASSWORD|CLIENT_?ID|TEXT_API_BASE', key, re.I) and len(value) >= 8:
                secrets.append(value)
    for key, value in os.environ.items():
        if re.search(r'API_KEY|TOKEN|SECRET|PASSWORD|CLIENT_?ID|TEXT_API_BASE', key, re.I) and len(value) >= 12:
            secrets.append(value)
    for name in ('modelscope-runtime.json', 'model-gateway.json'):
        path = root / 'data/deployment' / name
        if path.exists():
            private = json.loads(path.read_text(encoding='utf-8-sig'))
            for key, value in private.items():
                if isinstance(value, str) and len(value) >= 8 and re.search(
                    r'KEY|TOKEN|CLIENT_?ID|PASSWORD|API_BASE|UPSTREAM_URL', key, re.I
                ):
                    secrets.append(value)
    pattern = re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}'
                         r'|sk-[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
    for name in files:
        text = contents[name].decode('utf-8-sig') if contents is not None else (root / name).read_text(encoding='utf-8-sig')
        if any(value in text for value in secrets) or pattern.search(text):
            raise ValueError('检测到疑似凭证，已停止打包；请检查：' + name)


def valid_url(value):
    if not isinstance(value, str) or any(char.isspace() for char in value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def blockers(config):
    missing = []
    if not config.get('team'):
        missing.append('团队名称待填写')
    for key, label in LABELS.items():
        if not valid_url(config.get(key)):
            missing.append(label + '链接待填写或格式不正确')
    for key, label in [('ima_evidence_reviewed', 'ima 真实接入与图源证据'),
                       ('results_reviewed', '符合阶段要求的真实运行结果'),
                       ('public_access_reviewed', '所有链接的免登录访问人工复核')]:
        if config.get(key) is not True:
            missing.append(label + '待完成')
    if config.get('stage') not in ('初赛', '复赛'):
        missing.append('请选择初赛或复赛')
    if config.get('stage') == '复赛' and not valid_url(config.get('video_url')):
        missing.append('复赛真实 Demo 视频链接待填写')
    return missing


def build(root, out, config):
    files = public_files(root)
    contents = {name: (root / name).read_bytes() for name in files}
    scan(root, files, contents)
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out / 'zhike-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
    missing = blockers(config)
    manifest = {'prepared_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()},
                'blockers': missing, 'network_called': False,
                'note': '准备工具不验证外网权限或模型质量；复核标志由操作者依据真实证据填写。'}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    fields = [('团队', config.get('team', '')), ('作品', '知客 · 华为PC营销图文智能体'),
              ('赛道', '华为·产业进阶赛道 — AI+华为PC营销软文智能体'),
              ('阶段', config.get('stage', '初赛'))]
    fields += [(label, config.get(key, '')) for key, label in LABELS.items()]
    fields += [('Demo 视频', config.get('video_url', ''))]
    form = '\n'.join(label + '：' + (value or '待补齐') for label, value in fields)
    form += '\n\n项目简介：' + config.get('summary', '')
    (out / 'submission-fields.txt').write_text(form, encoding='utf-8')
    escape = html.escape
    issues = ''.join('<li>' + escape(item) + '</li>' for item in missing)
    links = ''.join('<a href="' + escape(config[key], quote=True) + '" target="_blank" rel="noopener">'
                    + label + '</a> ' for key, label in LABELS.items() if valid_url(config.get(key)))
    status = '待补齐 · 请先完成以下事项' if missing else '人工复核项已确认 · 请核对最终版本后提交'
    manual = out.parent / 'pdf' / '比比拉布-知客-作品说明书.pdf'
    pdf_link = ('<p><a href="../pdf/' + quote(manual.name) + '" download>下载作品说明书 PDF（可直接上传）</a></p>') if manual.is_file() else '<p>尚未生成可上传的说明书 PDF。</p>'
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>知客 · 提交准备台</title>
<style>body{font:16px/1.8 system-ui;margin:40px auto;padding:0 24px;max-width:960px;color:#182c2a;background:#f4f7f5}
h1{font-size:36px}section{background:white;border:1px solid #d6e1db;border-radius:16px;padding:24px;margin:20px 0}
a{color:#17634c;margin-right:16px}textarea{box-sizing:border-box;width:100%;min-height:340px;font:15px/1.8 system-ui;padding:16px}
button{background:#17634c;color:white;border:0;border-radius:8px;padding:12px 20px;font:inherit;cursor:pointer}
.status{color:#8a4500}li{margin:8px 0}small{color:#536961}</style>
<h1>知客 · 提交准备台</h1><p>团队：TEAM ｜ 一次整理，集中核对与复制。</p>
<section><h2 class="status">STATUS</h2><ul>ISSUES</ul>
<p>此页面只整理材料，不会替你向组委会发送表单。链接和复核项在 docs/competition/submission.json 维护，修改后重新运行准备入口。</p></section>
<section><h2>提交字段</h2><textarea id="fields" aria-label="提交字段" readonly>FIELDS</textarea>
<p><button id="copy">一键复制全部字段</button> <span id="message" role="status"></span></p>LINKS</section>
<section><h2>材料下载</h2>PDFLINK<p><a href="zhike-source.zip" download>源码 ZIP</a><a href="submission-fields.txt" download>提交字段 TXT</a><a href="manifest.json">文件哈希与检查记录</a></p>
<p>作品说明书、魔搭文案、录屏提纲及赛题对照表均在源码包的 docs/competition 目录。知识库原件、客户数据、凭证和私有案例册未打包。</p>
<small>检查记录仅针对本次打包内容；自动扫描不能替代发布前人工审阅。未完成真实 ima 验收时不得声明符合全部赛题要求。</small></section>
<script>document.getElementById('copy').onclick=async()=>{const t=document.getElementById('fields');
try{await navigator.clipboard.writeText(t.value);document.getElementById('message').textContent='已复制';}
catch(e){t.focus();t.select();document.getElementById('message').textContent='已全选，请按 Ctrl+C 复制';}};</script></html>'''
    # Replace markers once; user strings are always escaped and never executable.
    replacements = {'TEAM': escape(config.get('team', '待填写')), 'STATUS': status,
                    'ISSUES': issues, 'FIELDS': escape(form), 'LINKS': links, 'PDFLINK': pdf_link}
    page = re.sub(r'TEAM|STATUS|ISSUES|FIELDS|LINKS|PDFLINK', lambda match: replacements[match[0]], page)
    (out / 'index.html').write_text(page, encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Only scan public source, no writes')
    parser.add_argument('--require-ready', action='store_true', help='Exit 2 if submission has blockers')
    args = parser.parse_args()
    if args.check:
        files = public_files(ROOT)
        scan(ROOT, files)
        print(f'Public-source scan passed: {len(files)} files.')
        return
    config = json.loads((ROOT / 'docs/competition/submission.json').read_text(encoding='utf-8-sig'))
    report = build(ROOT, ROOT / 'output/submission', config)
    print(f"Prepared {len(report['files'])} files; pending items: {len(report['blockers'])}.")
    if args.require_ready and report['blockers']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
