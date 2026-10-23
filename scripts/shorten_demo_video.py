"""Shorten the recorded walkthrough by trimming pauses, without speeding up actions."""
import json,shutil,subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'output/competition-video-full-20261023'
OUT=ROOT/'output/competition-video-short-20261023'
OUT.mkdir(parents=True,exist_ok=True)
ffmpeg=shutil.which('ffmpeg');ffprobe=shutil.which('ffprobe')
chapters=json.loads((SOURCE/'视频检查.json').read_text(encoding='utf-8'))['chapters']
# Source chapter, in-point, duration. Preserve the interactions and their real outcomes.
cuts=[(0,4,4),(1,1,7),(2,1,6),(3,3,5),(4,3,5),(7,1,7),
      (8,1,5),(9,1,8),(10,1,6),(11,3,6),(12,3,8),(13,1,7),
      (14,1,6),(15,3,5),(17,1,5),(18,2,8),(19,1,5),(20,3,5),
      (21,1,7),(22,3,9),(25,4,5),(28,3,8),(29,3,6),(30,1,5),(31,8,4)]

def render(item):
    n,(idx,start,duration)=item
    src=SOURCE/f'take-{idx+1:02}.mp4';name=f'cut-{n:02}.mp4'
    subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-ss',str(start),'-i',str(src),'-t',str(duration),
        '-c:v','libx264','-preset','veryfast','-crf','20','-threads','2','-pix_fmt','yuv420p','-an',str(OUT/name)],check=True)
    return name

with ThreadPoolExecutor(max_workers=2) as pool:names=list(pool.map(render,enumerate(cuts,1)))
(OUT/'join.concat').write_text('\n'.join(f"file '{name}'" for name in names),encoding='utf-8')
result=OUT/'知客-三端精简演示-字幕版.mp4'
subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i','join.concat','-c','copy','-movflags','+faststart',result.name],cwd=OUT,check=True)
def stamp(t):return f'{int(t)//3600:02}:{int(t)//60%60:02}:{int(t)%60:02},000'
offset=0;subs=[];plan=[]
for n,(idx,start,duration) in enumerate(cuts,1):
    c=chapters[idx]
    subs.extend([str(n),stamp(offset)+' --> '+stamp(offset+duration),c['title']+'\n'+c['caption'],''])
    plan.append({'start':offset,'duration':duration,'title':c['title'],'source_chapter':idx,'source_in':start})
    offset+=duration
(OUT/'中文字幕.srt').write_text('\n'.join(subs),encoding='utf-8-sig')
probe=json.loads(subprocess.check_output([ffprobe,'-v','error','-show_format','-show_streams','-of','json',str(result)]))
(OUT/'剪辑与检查.json').write_text(json.dumps({'chapters':plan,'method':'剪去静态停留和重复操作，保留三端与多轮对话；无动作加速，中文字幕，无配音。','ffprobe':probe},ensure_ascii=False,indent=2),encoding='utf-8')
subprocess.run([ffmpeg,'-v','error','-i',str(result),'-f','null','-'],check=True)
for i,t in enumerate([18,58,116,133],1):
    subprocess.run([ffmpeg,'-y','-hide_banner','-loglevel','error','-ss',str(t),'-i',str(result),'-frames:v','1',str(OUT/f'check-{i}.jpg')],check=True)
print(json.dumps({'file':str(result),'seconds':probe['format']['duration'],'bytes':probe['format']['size']},ensure_ascii=False))
