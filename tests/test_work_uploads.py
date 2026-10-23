import io
import json
import zipfile
import asyncio

from PIL import Image

from backend.db import Session, Work, Asset
from .test_workflow import make_work, guest
from .test_work_review import fixture_model, repair_job
from backend import ai


def photo():
    output = io.BytesIO()
    image = Image.new('RGB', (800, 600), '#9faea4')
    image.save(output, 'PNG')
    return output.getvalue()


def upload(client, wid, data=None, **headers):
    return client.post(f'/api/works/{wid}/images?filename=study.png',
                       content=photo() if data is None else data,
                       headers={'X-Store-Request': '1', 'Content-Type': 'image/png', **headers})


def test_upload_persists_without_changing_draft_and_exports(clients):
    admin, staff, customer, _ = clients
    wid, _ = make_work(admin)
    response = upload(staff, wid)
    assert response.status_code == 200, response.text
    image = response.json()
    assert image['id'].startswith('upload-') and image['source_type'] == 'user_upload'
    detail = staff.get(f'/api/works/{wid}').json()
    assert detail['version'] == 1 and detail['report']['status'] == 'passed'
    assert image in detail['available_images']
    assert customer.get('/api/assets/' + image['id']).status_code == 401
    assert staff.get('/api/assets/' + image['id']).headers['content-type'].startswith('image/')
    edit = {'expected_version': 1, 'title': '学习桌面', 'body': '学习和写代码。',
            'image_ids': [image['id']], 'image_positions': {image['id']: 1}}
    assert staff.patch(f'/api/works/{wid}', json=edit, headers={'X-Store-Request': '1'}).status_code == 200
    saved = staff.get(f'/api/works/{wid}').json()
    assert saved['content']['images'][0]['id'] == image['id']
    html = staff.get(f'/api/works/{wid}/export?format=html&draft=true&scope=publication')
    assert html.status_code == 200 and 'data:image/' in html.text
    archive = staff.get(f'/api/works/{wid}/export?format=zip&draft=true&scope=publication')
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        assert 'images/' + image['name'] in bundle.namelist()
        Image.open(io.BytesIO(bundle.read('images/' + image['name']))).verify()
    assert staff.post(f'/api/works/{wid}/approve', json={'expected_version': 2, 'note': '本地配图已经核对'},
                      headers={'X-Store-Request': '1'}).status_code == 200


def test_uploaded_images_are_work_bound_and_not_knowledge(clients):
    admin, staff, *_ = clients
    wid, _ = make_work(admin)
    other, _ = make_work(admin)
    image = upload(staff, wid).json()
    assert image not in staff.get(f'/api/works/{other}').json()['available_images']
    assert staff.patch(f'/api/works/{other}', json={'expected_version': 1, 'title': '别的作品',
        'body': '正文', 'image_ids': [image['id']]}, headers={'X-Store-Request': '1'}).status_code == 400
    assert staff.get('/api/knowledge/images/' + image['id']).status_code == 404


def test_upload_rejects_unsafe_files_and_unauthorized_requests(clients):
    admin, staff, customer, _ = clients
    wid, _ = make_work(admin)
    assert upload(customer, wid).status_code == 401
    guest(customer)
    assert upload(customer, wid).status_code == 403
    assert staff.post(f'/api/works/{wid}/images', content=photo()).status_code == 403
    assert upload(staff, wid, Origin='https://evil.example').status_code == 403
    assert upload(staff, 'missing').status_code == 404
    for data in [b'', b'<svg xmlns="http://www.w3.org/2000/svg"/>', b'not an image', photo()[:40]]:
        assert upload(staff, wid, data).status_code == 400
    assert upload(staff, wid, b'x' * (10 * 1024 * 1024 + 1)).status_code == 413
    # Count streamed bytes too; an absent Content-Length must not bypass the cap.
    assert upload(staff, wid, (b'x' * 1_000_000 for _ in range(11))).status_code == 413
    assert staff.patch(f'/api/works/{wid}', content=b'x' * 250001,
                       headers={'X-Store-Request': '1'}).status_code == 413
    with Session() as session:
        assert session.query(Asset).filter_by(kind='work_upload').count() == 0


def test_upload_normalizes_orientation_and_strips_metadata(clients):
    admin = clients[0]
    wid, _ = make_work(admin)
    output = io.BytesIO()
    exif = Image.Exif(); exif[274] = 6; exif[270] = 'private location'
    Image.new('RGB', (80, 40)).save(output, 'JPEG', exif=exif)
    response = upload(admin, wid, output.getvalue())
    assert response.status_code == 200
    image = response.json()
    result = Image.open(io.BytesIO(admin.get('/api/assets/' + image['id']).content))
    assert result.size == (40, 80) and not result.getexif()
    with Session() as session:
        metadata = json.loads(session.get(Asset, image['id']).metadata_json)
        assert metadata['work_id'] == wid
        assert json.loads(session.get(Work, wid).content)['images'][0]['id'] != image['id']


def test_uploaded_picture_remains_user_supplied_during_review_and_repair(clients, monkeypatch):
    admin = clients[0]
    wid, _ = make_work(admin)
    image = upload(admin, wid).json()
    assert admin.patch(f'/api/works/{wid}', json={'expected_version': 1, 'title': '学习',
        'body': '了解产品配置。', 'image_ids': [image['id']]}, headers={'X-Store-Request': '1'}).status_code == 200
    fixture_model(monkeypatch)
    with Session() as session:
        work = session.get(Work, wid)
        content, brief = json.loads(work.content), json.loads(work.brief)
    report = asyncio.run(ai.verify(content, brief, work_id=wid))
    assert any(issue['type'] == '本地配图' for issue in report['issues'])
    assert not any(issue['type'] == '图片型号' for issue in report['issues'])
    foreign = asyncio.run(ai.verify(content, brief, work_id='different-work'))
    assert any(issue['type'] == '图片型号' for issue in foreign['issues'])
    job = repair_job(admin, wid, version=2)
    asyncio.run(ai.run_text_job(job))
    repaired = admin.get(f'/api/works/{wid}').json()
    assert repaired['version'] == 3
    assert any(item['id'] == image['id'] for item in repaired['content']['images'])
