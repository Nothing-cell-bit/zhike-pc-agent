"""Safe platform publication fragments; doocs/md base typography is inlined."""
import html
import re
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote
import bleach
import markdown
from .rich_text import validate_rich_text,check_sources,render_document

TAGS={'h1','h2','h3','h4','p','ul','ol','li','strong','em','s','blockquote','a','img','br','hr','code','pre','table','thead','tbody','tr','th','td','figure','figcaption','span'}


@lru_cache(maxsize=1)
def wechat_styles():
    css=(Path(__file__).resolve().parents[1]/'third_party/doocs-md/default.css').read_text(encoding='utf-8')
    css=re.sub(r'/\*.*?\*/','',css,flags=re.S)
    styles={}
    for tag in TAGS:
        match=re.search(r'(?:^|\n)'+tag+r'\s*\{([^}]+)\}',css)
        if not match:continue
        value=match[1].replace('hsl(var(--foreground))','#30362d')
        for name,replacement in [('md-primary-color','#a33c3c'),('md-font-size','16px'),('md-block-spacing','1'),('md-link-color','#a33c3c')]:value=value.replace('var(--'+name+')',replacement)
        value=value.replace('var(--md-blockquote-background, var(--blockquote-background))','#f6f6f1')
        value=re.sub(r'calc\(([\d.]+)(em|px)\s*\*\s*([\d.]+)\)',lambda m:f'{float(m[1])*float(m[3]):g}{m[2]}',value)
        styles[tag]=';'.join(part.strip() for part in value.split(';') if part.strip() and 'var(' not in part)
    return styles


class InlineTheme(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=False);self.parts=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs);base=wechat_styles().get(tag,'')
        if base:attrs['style']=base+';'+(attrs.get('style') or '')
        self.parts.append('<'+tag+''.join(' '+key+'="'+html.escape(value or '',quote=True)+'"' for key,value in attrs.items())+'>')
    def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs)
    def handle_endtag(self,tag):self.parts.append('</'+tag+'>')
    def handle_data(self,data):self.parts.append(data)
    def handle_entityref(self,name):self.parts.append('&'+name+';')
    def handle_charref(self,name):self.parts.append('&#'+name+';')


def render_publication(content,platform,image_url=None,gallery=None):
    from .work_media import image_url as media_url
    image_url=image_url or media_url
    images={image['id']:{'url':image_url(image),'caption':image.get('caption') or image.get('description','')} for image in content.get('images',[])}
    allowed={image['url'] for image in images.values()}
    def clean(text):
        return bleach.clean(markdown.markdown(text or '',extensions=['tables',*(['nl2br'] if platform=='小红书' else [])]),tags=TAGS,
            attributes={'a':['href'],'ol':['start'],'img':lambda tag,key,value:key=='alt' or key=='src' and value in allowed},protocols=['https','http'])
    def field(key,inline=False):
        item=content.get('rich_text',{}).get(key)
        if item and item.get('source')==content.get(key):
            try:
                validate_rich_text({key:item});check_sources({key:item},content,list(images))
                return render_document(item['doc'],{} if platform=='朋友圈' and key=='body' else images,inline=inline)
            except (ValueError,KeyError,TypeError):pass
        if key=='body':
            blocks=re.split(r'\n\s*\n',(content.get('body') or '').strip());parts=[]
            from .marketing import image_after
            for slot in range(len(blocks)+1):
                if slot:parts.append(clean(blocks[slot-1]))
                for index,image in enumerate(content.get('images',[]) if platform!='朋友圈' else []):
                    if image_after(image,len(blocks),index)==slot:
                        item=images[image['id']];parts.append('<figure><img src="'+html.escape(item['url'],quote=True)+'" alt="'+html.escape(item['caption'],quote=True)+'"><figcaption>'+html.escape(item['caption'])+'</figcaption></figure>')
            return ''.join(parts)
        return html.escape(content.get(key,'')).replace('\n','<br>')
    if platform=='朋友圈':
        fragment='<div style="white-space:pre-wrap">'+field('body')+'</div>'
        photos=gallery.get('items',[]) if gallery else [{'url':item['url'],'title':item['caption']} for item in images.values()]
        if photos:
            columns=1 if len(photos)==1 else 3
            fragment+=f'<div class="moments-image-grid" style="display:grid;grid-template-columns:repeat({columns},minmax(0,1fr));gap:5px;margin-top:18px;max-width:330px">'+''.join('<img src="'+html.escape(item['url'],quote=True)+'" alt="'+html.escape(item.get('title','朋友圈配图'),quote=True)+'" style="display:block;width:100%;aspect-ratio:1;object-fit:contain;background:#f5f6f0;border-radius:4px">' for item in photos[:9])+'</div>'
        return '<section data-platform="朋友圈" style="font:16px/1.9 system-ui;color:#26332b;max-width:430px;margin:auto">'+fragment+'</section>'
    fragment='<h1>'+field('title',True)+'</h1>'
    if content.get('intro'):fragment+='<blockquote>'+field('intro',True)+'</blockquote>'
    fragment+=field('body')
    if content.get('cta'):fragment+='<p>'+field('cta',True)+'</p>'
    if content.get('tags'):fragment+='<p style="color:#456c84">'+html.escape(' '.join('#'+tag.lstrip('#') for tag in content['tags']))+'</p>'
    if platform=='公众号':
        renderer=InlineTheme();renderer.feed(fragment);fragment=''.join(renderer.parts)
    return '<section data-platform="'+html.escape(platform,quote=True)+'" style="font-family:Microsoft YaHei,system-ui;font-size:16px;line-height:1.9;font-synthesis:weight style;max-width:680px;margin:auto">'+fragment+'</section>'
