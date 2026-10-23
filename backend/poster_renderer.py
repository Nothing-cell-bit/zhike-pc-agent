"""Product posters adapted from Poster Maker's MIT HTML/CSS templates and export flow.

Upstream provenance and the original license: third_party/poster-maker/.
Product pixels stay original; the browser renders deterministic Chinese text layers.
"""
import base64
import html
import io
import re
from pathlib import Path

from PIL import Image

STYLES={'studio':'极简科技','ember':'暗色发布'}
TEMPLATE=Path(__file__).with_name('poster_templates')/'product.html'


def poster_copy(content,product_name):
    title=str(content.get('title') or product_name)
    parts=re.split(r'[！!：:]',title,maxsplit=1)
    if len(parts)==2 and 2<=len(parts[0])<=15 and parts[1].strip():
        eyebrow,headline=parts[0].strip(),parts[1].strip()
    else:eyebrow,headline='为你的使用场景选电脑',title
    sources={r.get('id') for r in content.get('sources',[]) if r.get('id')}
    highlights=[]
    for claim in content.get('claims',[]):
        text=claim.get('text','')
        if claim.get('source_id') not in sources or not isinstance(text,str):continue
        if text.startswith(product_name):text=text[len(product_name):].lstrip(' ，,:：')
        if text and len(text)<=64 and text not in highlights:highlights.append(text)
        if len(highlights)==3:break
    return {'eyebrow':eyebrow,'headline':headline,'product_name':product_name,
            'highlights':highlights,'intro':str(content.get('intro') or ''),
            'cta':str(content.get('cta') or '欢迎到店，按你的需求体验产品')}


def image_uri(path):
    # Re-encode only the export copy; source files and original alpha are untouched.
    with Image.open(path) as original:
        image=original.convert('RGBA');image.thumbnail((2400,2400),Image.Resampling.LANCZOS)
        output=io.BytesIO();image.save(output,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode('ascii')


def build_html(content,product_name,product_path,background_path,size,style,source):
    if style not in STYLES:raise ValueError('请选择有效的海报风格')
    width,height=size;copy=poster_copy(content,product_name);escape=html.escape
    # Only trusted template code is executable. User copy is always escaped text.
    highlighted=escape(copy['headline'])
    if '，' in copy['headline']:
        first,last=copy['headline'].split('，',1)
        separator='<br>' if 3<=len(first)<=18 and 3<=len(last)<=18 else '<wbr>'
        highlighted=escape(first)+'，'+separator+'<em>'+escape(last)+'</em>'
    highlights=''.join('<div class="highlight"><div class="number">0'+str(i+1)+'</div><p data-fit>'+escape(text)+'</p></div>' for i,text in enumerate(copy['highlights']))
    if not highlights:highlights=escape(copy['intro'])
    values={'WIDTH':str(width),'HEIGHT':str(height),'STYLE':style,
            'FORMAT':'landscape' if width>height else 'square' if width==height else 'portrait',
            'COUNT':str(max(1,len(copy['highlights']))),'INTRO_CLASS':'' if copy['highlights'] else 'intro',
            'BACKGROUND':'<img class="scene" src="'+image_uri(background_path)+'" alt="">' if background_path else '',
            'EYEBROW':escape(copy['eyebrow']),'HEADLINE':highlighted,'PRODUCT_NAME':escape(product_name),
            'PRODUCT_IMAGE':image_uri(product_path),'HIGHLIGHTS':highlights,'CTA':escape(copy['cta']),'SOURCE':escape(source)}
    template=TEMPLATE.read_text(encoding='utf-8')
    return re.sub(r'__([A-Z_]+)__',lambda match:values[match[1]],template),copy


def render_poster(content,product_name,product_path,background_path,size,style,source,destination):
    try:from playwright.sync_api import sync_playwright,Error
    except ImportError as error:
        raise ValueError('历史模板渲染器未安装；如需使用，请安装开发依赖及 Chromium') from error
    document,copy=build_html(content,product_name,product_path,background_path,size,style,source)
    width,height=size
    with sync_playwright() as runtime:
        try:browser=runtime.chromium.launch(headless=True)
        except Error as error:
            raise ValueError('海报渲染器未就绪，请运行 python -m playwright install chromium 后重试') from error
        try:
            page=browser.new_page(viewport={'width':width,'height':height},device_scale_factor=1)
            # Poster export is entirely local. No external URLs, uploads or API calls.
            page.route('**/*',lambda route:route.abort())
            page.set_content(document,wait_until='load')
            page.evaluate('document.fonts.ready')
            page.evaluate('''() => {
                for (const element of document.querySelectorAll('[data-fit], .highlights.intro')) {
                    const container = element.parentElement;
                    let size = parseFloat(getComputedStyle(element).fontSize);
                    const available = element.matches('.title span') ? container.clientHeight :
                        element.matches('.cta-text') ? container.clientHeight - 40 :
                        element.matches('.highlight p') ? container.clientHeight - 48 : element.clientHeight;
                    while (size > 12 && (element.scrollHeight > available + 1 || element.scrollWidth > element.clientWidth + 1)) {
                        element.style.fontSize = (--size) + 'px';
                    }
                }
            }''')
            layout=page.evaluate('''() => Object.fromEntries([...document.querySelectorAll('[data-region]')].map(element => {
                const box=element.getBoundingClientRect();
                return [element.dataset.region,[box.left,box.top,box.right,box.bottom]];
            }))''')
            # Same viewport/font-ready/clip export contract as upstream scripts/export.js.
            page.screenshot(path=str(destination),clip={'x':0,'y':0,'width':width,'height':height})
            return {'layout':layout,'poster_copy':copy,'design_version':'poster-maker-v1','style':style,
                    'design_source':'https://github.com/dabodamjan/poster-maker','design_license':'MIT'}
        finally:browser.close()
