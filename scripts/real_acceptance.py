"""Opt-in real-service acceptance, using synthetic scenarios only.

--text requests three articles, or five with --suite handbook.
--image explicitly submits one background.
Saved job IDs are resumed, not silently submitted again.
"""
import argparse
import json
import sys
import time
from datetime import datetime,timezone,timedelta
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--text',action='store_true')
    parser.add_argument('--image',action='store_true')
    parser.add_argument('--base',default='http://127.0.0.1:8765/api')
    parser.add_argument('--run-id',default='recovery-20261018')
    parser.add_argument('--suite',choices=['baseline','handbook'],default='baseline',help='handbook adds same-product/same-platform scene comparison and a poster task')
    args=parser.parse_args()
    if not (args.text or args.image):parser.error('请选择 --text 或 --image；真实服务可能消耗额度，必须先获得授权。')
    if not args.run_id.replace('-','').replace('_','').isalnum():parser.error('run-id 仅允许字母数字、下划线和连字符')
    sys.stdout.reconfigure(encoding='utf-8')
    out=ROOT/'data'/'acceptance'/args.run_id;out.mkdir(parents=True,exist_ok=True)
    result_path=out/'results.json'
    results=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {'text':[],'image':None,'synthetic_scenarios':True}
    if results.get('suite','baseline')!=args.suite:raise SystemExit('run-id 已属于另一组测试，请指定新的 run-id，不覆盖历史记录。')
    results['suite']=args.suite
    def save():
        results['updated_at']=datetime.now(timezone(timedelta(hours=8))).isoformat()
        temp=result_path.with_suffix('.tmp');temp.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(result_path)
    def wait(client,entry):
        deadline=time.monotonic()+360
        while True:
            response=client.get('/jobs/'+entry['job_id']);response.raise_for_status();job=response.json()
            entry.update({key:job[key] for key in ['status','error','result','remote_id']});save()
            if job['status'] not in {'queued','running'} or time.monotonic()>deadline:return job
            time.sleep(2)
    credentials_file=ROOT/'data'/'initial-admin.txt'
    if not credentials_file.exists():raise SystemExit('未找到私有初始化凭证文件，不会重置现有账号。请通过网站登录后逐项执行。')
    credentials=dict(line.split('=',1) for line in credentials_file.read_text(encoding='utf-8').splitlines() if '=' in line)
    with httpx.Client(base_url=args.base,headers={'X-Store-Request':'1'},timeout=25) as client:
        response=client.post('/auth/login',json=credentials);response.raise_for_status()
        products=client.get('/products').json()
        harmony=next(p for p in products if '14（鸿蒙' in p['name'])
        windows=next(p for p in products if '酷睿 Ultra' in p['name'])
        scenarios=[(harmony,'准备开学的大学新生','课堂笔记、图书馆阅读、日常文档，需要携带方便。具体专业软件兼容性请在选购前核对。','小红书'),(windows,'经常出差的职场人士','会议记录、机场处理文档、差旅携带，引导到店核对实际销售版本。','公众号'),(harmony,'准备开学的大学新生','课堂笔记、图书馆阅读、日常文档，需要携带方便。具体专业软件兼容性请在选购前核对。','朋友圈')]
        if args.suite=='handbook':
            scenarios.extend([(harmony,'经常出差的职场人士','同一款鸿蒙电脑，用于差旅携带、会议记录与文档处理；不承诺软件兼容性，邀请带工作清单到店核对。','小红书'),(harmony,'门店附近正在比较电脑的顾客','周末到店看屏幕与外观，不提供活动价、补贴、库存或赠品承诺。','海报')])
        if args.text:
            for index,(product,audience,scene,platform) in enumerate(scenarios):
                if index>=len(results['text']):
                    brief={'product_id':product['id'],'audience':audience,'scene':scene,'platform':platform,'goal':'引导咨询与到店体验','tone':'自然专业，不虚构个人体验'}
                    response=client.post('/marketing/tasks',json=brief);response.raise_for_status()
                    results['text'].append({'job_id':response.json()['job_id'],'product':product['name'],'platform':platform,'brief':brief});save()
                entry=results['text'][index];job=wait(client,entry)
                wid=job['result'].get('work_id')
                if wid:
                    work=client.get('/works/'+wid).json();entry['verification']=work['report'];entry['work_id']=wid
                    (out/f'work-{index+1}.json').write_text(json.dumps(work,ensure_ascii=False,indent=2),encoding='utf-8')
                    response=client.get(f'/works/{wid}/export',params={'format':'zip','draft':str(work['report']['status']!='passed').lower()})
                    response.raise_for_status();(out/f'work-{index+1}.zip').write_bytes(response.content)
                save();print(json.dumps({'scenario':index+1,'status':job['status'],'work_id':wid,'verification':entry.get('verification',{}).get('status'),'error':job['error']},ensure_ascii=False),flush=True)
        if args.image:
            if not results['image']:
                response=client.post('/images/tasks',json={'scene':'自然光图书馆，浅色桌面，中央留白，无人、无电脑、无产品、无标志、无文字。','ratio':'3:4','request_id':'demo-image-'+args.run_id});response.raise_for_status()
                results['image']={'job_id':response.json()['job_id']};save()
            job=wait(client,results['image'])
            print(json.dumps({'image_status':job['status'],'remote_id':job['remote_id'],'error':job['error']},ensure_ascii=False),flush=True)
        results['complete_text_demo']=len(results['text'])==len(scenarios) and all(x.get('verification',{}).get('status')=='passed' for x in results['text'])
        save();print('真实验收记录已保存在 data/acceptance/'+args.run_id,flush=True)

if __name__=='__main__':main()
