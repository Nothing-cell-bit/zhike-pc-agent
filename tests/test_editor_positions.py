from .test_workflow import make_work


def test_inline_editor_image_position_is_persisted_without_inline_image_code(clients):
    admin,*_=clients;wid,iid=make_work(admin)
    response=admin.patch('/api/works/'+wid,headers={'X-Store-Request':'1'},json={
        'expected_version':1,'title':'直接编辑的标题','intro':'导语','body':'第一段。\n\n第二段。\n\n第三段。',
        'cta':'到店体验','image_ids':[iid],'image_positions':{iid:2}})
    assert response.status_code==200
    work=admin.get('/api/works/'+wid).json()
    assert work['content']['images'][0]['after_block']==2
    assert work['report']['status']=='unchecked'
    assert '/api/knowledge/images' not in work['content']['body']


def test_manual_rich_text_style_is_saved_and_exported(clients):
    admin,*_=clients;wid,_=make_work(admin)
    title={'source':'手写标题','doc':{'type':'doc','content':[{'type':'paragraph','content':[{'type':'text','text':'手写标题','marks':[{'type':'italic'},{'type':'textStyle','attrs':{'fontFamily':'宋体','fontSize':'37px'}}]}]}]}}
    response=admin.patch('/api/works/'+wid,headers={'X-Store-Request':'1'},json={
        'expected_version':1,'title':'手写标题','body':'正文','image_ids':[],'rich_text':{'title':title}})
    assert response.status_code==200
    assert admin.get('/api/works/'+wid).json()['content']['rich_text']['title']==title
    exported=admin.get('/api/works/'+wid+'/export?format=html&draft=true').text
    assert 'font-size:37px' in exported and 'font-family:宋体' in exported
    assert '<em>' in exported


def test_rich_style_rejects_external_css_and_unmanaged_images(clients):
    admin,*_=clients;wid,_=make_work(admin)
    for node in [
        {'type':'paragraph','content':[{'type':'text','text':'标题','marks':[{'type':'textStyle','attrs':{'fontFamily':'url(https://evil.test)','fontSize':'33px'}}]}]},
        {'type':'image','attrs':{'src':'https://evil.test/a.png'}},
        {'type':'paragraph','content':[{'type':'text','text':'标题','marks':[{'type':'textStyle','attrs':{'fontFamily':123}}]}]},
    ]:
        response=admin.patch('/api/works/'+wid,headers={'X-Store-Request':'1'},json={
            'expected_version':1,'title':'标题','body':'正文','image_ids':[],
            'rich_text':{'title':{'source':'标题','doc':{'type':'doc','content':[node]}}}})
        assert response.status_code==422


def test_rich_product_caption_cannot_be_html_nodes(clients):
    admin,*_=clients;wid,iid=make_work(admin)
    response=admin.patch('/api/works/'+wid,headers={'X-Store-Request':'1'},json={
        'expected_version':1,'title':'标题','body':'正文','image_ids':[iid],
        'rich_text':{'body':{'source':'正文','doc':{'type':'doc','content':[
            {'type':'paragraph','content':[{'type':'text','text':'正文'}]},
            {'type':'productImage','attrs':{'id':iid,'caption':['img',{'src':'https://evil.test/a.png'}]}},
        ]}}}})
    assert response.status_code==422


def test_styled_body_keeps_managed_image_and_image_evidence_in_html(clients):
    admin,*_=clients;wid,iid=make_work(admin)
    source='正文样式\n\n第二段'
    doc={'type':'doc','content':[
        {'type':'paragraph','content':[{'type':'text','text':'正文样式','marks':[{'type':'textStyle','attrs':{'fontFamily':'楷体','fontSize':'23px'}}]}]},
        {'type':'productImage','attrs':{'id':iid,'caption':'产品图'}},
        {'type':'paragraph','content':[{'type':'text','text':'第二段'}]},
    ]}
    response=admin.patch('/api/works/'+wid,headers={'X-Store-Request':'1'},json={
        'expected_version':1,'title':'标题','body':source,'image_ids':[iid],'image_positions':{iid:1},
        'rich_text':{'body':{'source':source,'doc':doc}}})
    assert response.status_code==200
    work=admin.get('/api/works/'+wid).json()
    assert work['content']['images'][0]['after_block']==1
    exported=admin.get('/api/works/'+wid+'/export?format=html&draft=true').text
    assert 'font-size:23px' in exported and '第二段' in exported and '<figure><img ' in exported
    assert '选图理由' in exported
