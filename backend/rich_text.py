"""Validated editor documents; plain text remains the source for model checks."""
import html
import json
import re
from urllib.parse import urlsplit

import bleach
import markdown

FIELDS={'title','intro','body','cta'}
NODES={'doc','paragraph','heading','text','hardBreak','horizontalRule','bulletList','orderedList','listItem','blockquote','codeBlock','productImage'}
MARKS={'bold','italic','strike','code','link','textStyle'}
FONT=re.compile(r'^[\w ,\-]{1,80}$',re.UNICODE)
SIZE=re.compile(r'^(?:[1-8]\d|9[0-6])px$')


def validate_rich_text(value):
    if value is None:return value
    if not isinstance(value,dict) or not set(value)<=FIELDS or len(json.dumps(value,ensure_ascii=False))>160000:
        raise ValueError('文稿样式过大或字段无效')
    count=0
    def visit(node,field,depth=0):
        nonlocal count
        count+=1
        if depth>30 or count>8000 or not isinstance(node,dict) or node.get('type') not in NODES:
            raise ValueError('文稿样式结构无效')
        if not set(node)<={'type','attrs','content','text','marks'}:raise ValueError('文稿节点含未知属性')
        kind=node['type'];attrs=node.get('attrs') or {}
        if not isinstance(attrs,dict):raise ValueError('节点属性无效')
        allowed={'heading':{'level'},'orderedList':{'start','type'},'codeBlock':{'language'},'productImage':{'id','caption'}}.get(kind,set())
        if not set(attrs)<=allowed:raise ValueError('节点属性无效')
        if kind=='heading' and attrs.get('level') not in {1,2,3}:raise ValueError('标题级别无效')
        if kind=='orderedList' and (type(attrs.get('start',1)) is not int or not 1<=attrs.get('start',1)<=10000):raise ValueError('列表编号无效')
        if kind=='productImage' and (field!='body' or not isinstance(attrs.get('id'),str) or len(attrs['id'])>150):raise ValueError('图片节点无效')
        if kind=='productImage' and (not isinstance(attrs.get('caption',''),str) or len(attrs.get('caption',''))>2000):raise ValueError('图片说明无效')
        if kind=='text' and not isinstance(node.get('text'),str):raise ValueError('文字节点无效')
        marks=node.get('marks',[])
        if not isinstance(marks,list) or len(marks)>8:raise ValueError('文字格式无效')
        for mark in marks:
            if not isinstance(mark,dict) or mark.get('type') not in MARKS or not set(mark)<={'type','attrs'}:raise ValueError('文字格式无效')
            style=mark.get('attrs') or {}
            if not isinstance(style,dict):raise ValueError('文字格式属性无效')
            if mark['type']=='textStyle':
                if not set(style)<={'fontFamily','fontSize'}:raise ValueError('仅支持字体和字号')
                if style.get('fontFamily') is not None and (not isinstance(style['fontFamily'],str) or not FONT.fullmatch(style['fontFamily'])):raise ValueError('字体名称无效')
                if style.get('fontSize') is not None and (not isinstance(style['fontSize'],str) or not SIZE.fullmatch(style['fontSize'])):raise ValueError('字号须为10至96px')
            elif mark['type']=='link':
                if not set(style)<={'href','target','rel','class'}:raise ValueError('链接属性无效')
                href=style.get('href','')
                if not isinstance(href,str) or urlsplit(href).scheme not in {'http','https'}:raise ValueError('链接无效')
            elif style:raise ValueError('文字格式属性无效')
        children=node.get('content',[])
        if not isinstance(children,list):raise ValueError('文稿子节点无效')
        if kind in {'text','hardBreak','horizontalRule','productImage'} and children:raise ValueError('文稿叶节点无效')
        if kind!='text' and marks:raise ValueError('格式只能作用于文字')
        for child in children:visit(child,field,depth+1)
    for field,item in value.items():
        if not isinstance(item,dict) or set(item)!={'source','doc'} or not isinstance(item['source'],str):raise ValueError('文稿样式记录无效')
        if not isinstance(item['doc'],dict) or item['doc'].get('type')!='doc':raise ValueError('文稿文档无效')
        visit(item['doc'],field)
    return value


def document_text(node):
    if node['type']=='productImage':return ''
    if node['type']=='text':return node['text']
    if node['type']=='hardBreak':return '\n'
    separator='\n' if node['type'] in {'doc','bulletList','orderedList','blockquote','listItem'} else ''
    return separator.join(document_text(child) for child in node.get('content',[]))


def check_sources(rich,content,image_ids):
    def normalized(text):return re.sub(r'\s+','',text)
    def image_nodes(node):
        return ([node['attrs']['id']] if node['type']=='productImage' else [])+[image for child in node.get('content',[]) for image in image_nodes(child)]
    for field,item in (rich or {}).items():
        source=content.get(field,'')
        expected=html.unescape(bleach.clean(markdown.markdown(source),tags=[],strip=True)) if field=='body' else source
        # Markdown's strike syntax is rendered by the editor but not Python-Markdown.
        if field=='body':expected=expected.replace('~~','')
        if item['source']!=source or normalized(document_text(item['doc']))!=normalized(expected):raise ValueError('样式文字与当前文案不一致，请重新保存')
        ids=image_nodes(item['doc'])
        if field=='body' and (len(set(ids))!=len(ids) or set(ids)!=set(image_ids)):raise ValueError('样式配图必须与所选图片一致')


def render_document(doc,images=None,inline=False):
    images=images or {}
    def render(node):
        kind=node['type'];attrs=node.get('attrs') or {}
        if kind=='text':
            text=html.escape(node['text'])
            for mark in node.get('marks',[]):
                name=mark['type'];style=mark.get('attrs') or {}
                if name=='textStyle':
                    css=';'.join(key+':'+style[value] for key,value in [('font-family','fontFamily'),('font-size','fontSize')] if style.get(value))
                    text='<span style="'+html.escape(css,quote=True)+'">'+text+'</span>'
                elif name=='link':text='<a href="'+html.escape(style['href'],quote=True)+'" rel="noreferrer">'+text+'</a>'
                else:
                    tag={'bold':'strong','italic':'em','strike':'s','code':'code'}[name];text=f'<{tag}>'+text+f'</{tag}>'
            return text
        if kind=='productImage':
            image=images.get(attrs['id'])
            if not image:return ''
            return '<figure><img src="'+html.escape(image['url'],quote=True)+'" alt="'+html.escape(image.get('caption',''),quote=True)+'"><figcaption>'+html.escape(image.get('caption',''))+'</figcaption></figure>'
        if kind=='hardBreak':return '<br>'
        if kind=='horizontalRule':return '<hr>'
        children=('<br>' if kind=='doc' and inline else '').join(render(child) for child in node.get('content',[]))
        if kind=='doc' or inline:return children
        tag={'paragraph':'p','heading':'h'+str(attrs.get('level',2)),'bulletList':'ul','orderedList':'ol','listItem':'li','blockquote':'blockquote','codeBlock':'pre'}[kind]
        start=f' start="{attrs.get("start",1)}"' if kind=='orderedList' else ''
        return '<'+tag+start+'>'+children+'</'+tag+'>'
    return render(doc)
