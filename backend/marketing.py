"""Local, deterministic presentation and image planning; never asserts an ima connection."""
import re
from urllib.parse import quote


PROMPT_VERSION = 'store-v4-ima'
SCENARIO_LABELS = {
    'audience': '目标人群', 'scene': '使用场景', 'buying_stage': '购买阶段',
    'user_problem': '用户问题', 'goal': '内容目标', 'platform': '发布平台',
}
SCENE_GROUPS = (
    ('学习', ('学生', '新生', '课堂', '学习', '笔记', '图书馆', '课件', '手写')),
    ('差旅', ('差旅', '出差', '移动', '携带', '便携', '轻薄', '机身', '办公', '会议')),
    ('创作', ('创作', '设计', '绘画', '摄影', '剪辑', '屏幕', '色彩', '手写笔')),
    ('家庭', ('家庭', '全家', '换新', '易用', '外观', '配色')),
    ('采购', ('企业', '采购', '部署', '管理', '安全', '接口')),
)

def has_source_conflict(report):
    return bool(report.get('blocked') or any(i.get('type') == '资料冲突' for i in report.get('issues', [])))

def has_inline_images(content):
    # Product images must be selected through the typed, same-model image list.
    return any(re.search(r'!\[|<\s*img\b', str(content.get(key, '')), re.I)
               for key in ['title', 'intro', 'body', 'cta'])


def scenario_judgment(brief, extracted=None):
    extracted = extracted or {}
    # Stage must be explicitly supplied, never guessed from a demographic.
    result = {key: str(brief.get(key) or '待确认') for key in SCENARIO_LABELS}
    if not brief.get('user_problem') and extracted.get('user_problem'):
        result['user_problem'] = str(extracted['user_problem'])
    return result


def body_blocks(body):
    return [part for part in re.split(r'\n\s*\n', body.strip()) if part.strip()]


def _tokens(text):
    words = set(re.findall(r'[a-z0-9]+', text.lower()))
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        words.update(run[i:i+2] for i in range(len(run)-1))
    return words


def _matches(context, description):
    overlap = _tokens(context) & _tokens(description)
    groups = [name for name, words in SCENE_GROUPS
              if any(w in context for w in words) and any(w in description for w in words)]
    return len(overlap) + len(groups)*3, sorted(overlap), groups


def place_images(images, body):
    blocks = body_blocks(body)
    output = []
    for i, image in enumerate(images):
        description = image.get('description') or image.get('caption') or image.get('name', '')
        scores = [_matches(block, description)[0] for block in blocks]
        # A zero match gets an honest neutral placement, not a claimed semantic match.
        after = scores.index(max(scores))+1 if scores and max(scores) else min(i+1, len(blocks))
        output.append({**image, 'caption': image.get('caption') or description,
                       'after_block': after, 'position': f'正文第{after}块后' if after else '导语后',
                       'selection_reason': image.get('selection_reason', '人工选择的同型号图片；插入位置按当前正文重新计算')})
    return output


def select_images(images, brief, body, count):
    context = ' '.join(str(brief.get(k, '')) for k in ['audience', 'scene', 'user_problem', 'goal', 'emphasis'])
    ranked = []; seen = set()
    for index, image in enumerate(images):
        if image.get('product_id') != brief.get('product_id') or image.get('id') in seen:
            continue
        seen.add(image.get('id'))
        score, overlap, groups = _matches(context, image.get('description', '')+' '+image.get('name', ''))
        reason = '匹配场景：'+'、'.join(groups + overlap[:4]) if score else '同型号素材；无明确场景匹配，需人工确认画面适用性'
        ranked.append((score, index, {**image, 'selection_reason': reason}))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return place_images([item[2] for item in ranked[:count]], body)


def image_after(image, block_count, index):
    value = image.get('after_block')
    if isinstance(value, int): return max(0, min(value, block_count))
    # Old works are rendered without mutating their stored content.
    legacy = re.search(r'第(\d+)[段块]', image.get('position', ''))
    return min(int(legacy[1]) if legacy else index+1, block_count)


def image_relative_url(image):
    return 'images/'+quote(image['name'], safe='')


def picture_markdown(image):
    caption = str(image.get('caption') or image.get('description') or image['name'])
    caption = re.sub(r'([\\\[\]])', r'\\\1', caption).replace('\n', ' ')
    return f'![{caption}]({image_relative_url(image)})'


def article_with_images(content):
    blocks = body_blocks(content.get('body', '')); images = content.get('images', [])
    parts = ['### '+content.get('title', ''), content.get('intro', '')]
    for slot in range(len(blocks)+1):
        if slot: parts.append(blocks[slot-1])
        parts.extend(picture_markdown(im) for i, im in enumerate(images) if image_after(im, len(blocks), i) == slot)
    parts.extend([content.get('cta', ''), ' '.join(content.get('tags', []))])
    return '\n\n'.join(p for p in parts if p)


def unified_markdown(content, brief, report, draft=False):
    scenario = scenario_judgment(brief, content.get('scenario'))
    is_ima=content.get('source_type')=='ima'
    source_label=('ima共享知识库：'+content.get('knowledge_base_name','指定比赛知识库')+'；本稿使用该次检索保存的资料和原图。') if is_ima else '本地 ZIP；本稿不作为 ima 图源验收证明。'
    if content.get('fallback_reason'):source_label+=' 本次 ima 调用失败，已整体回退本地：'+content['fallback_reason']
    parts = ['# '+('待确认草稿' if draft else '营销图文与核验记录'),
             '> 知识来源：'+source_label,
             '## 一、场景判断']
    parts.extend(f'- {label}：{scenario[key]}' for key, label in SCENARIO_LABELS.items())
    strategy = content.get('strategy', '')
    if strategy:
        parts += ['### 内容策略'+('（修改前的策略，仅供追溯）' if content.get('strategy_current') is False else ''), strategy]
    parts += ['## 二、知识库依据', '- 产品型号：'+content.get('product_name', '待确认')]
    sources = content.get('sources', [])
    for ref in sources:
        parts.append(f'- {ref["id"]}：{ref["title"]}；版本 {ref.get("version", "待确认")}；{ref.get("path", "")}')
        parts.extend(ref.get('urls', []))
    claims = report.get('claims', content.get('claims', []))
    parts.extend(f'- 事实点：{claim["text"]}；依据：{claim["source_id"]}' for claim in claims)
    if not sources: parts.append('- 尚无资料依据，待确认。')
    parts += ['## 三、图文软文', article_with_images(content), '### 配图方案']
    for im in content.get('images', []):
        parts.append(f'- {im["name"]}；位置：{im.get("position", "待确认")}；说明：{im.get("caption", im.get("description", "待确认"))}；来源：{im.get("source") or im.get("url") or "待确认"}；选图理由：{im.get("selection_reason", "历史稿件未记录")}')
    status = report.get('status', 'unchecked')
    parts += ['## 四、核验结果', '- 内容检查：'+{'passed':'通过', 'manual_passed':'人工已通过', 'needs_review':'需人工复核', 'unchecked':'待检查'}.get(status, status),
              '- 产品事实：'+('已人工确认，系统原始检查记录见下方' if status=='manual_passed' else '已按所列'+(' ima 来源快照' if is_ima else '本地资料')+'核验' if status == 'passed' else '待核验或需修订'),
              '- 图片型号：'+('已人工确认' if status=='manual_passed' else '同型号索引检查通过' if status == 'passed' else '待核验或需修订')+('；ima 原图来源已记录' if is_ima else '；本地图源'),
              '- 合规：'+('已人工确认，系统原始检查记录见下方' if status=='manual_passed' else '本次检查未发现问题；仍需发布前复核' if status == 'passed' else '待核验或需修订')]
    if status=='manual_passed':
        approval=report.get('approval',{})
        parts += ['- 人工确认：'+approval.get('display_name','')+'；'+approval.get('approved_at',''),
                  '- 确认说明：'+approval.get('note',''), '### 人工确认时的原始检查记录（保留追溯）']
    parts.extend('- '+i.get('type', '核验')+'：'+i['text'] for i in report.get('issues', []))
    pending = list(dict.fromkeys(content.get('pending', [])+report.get('pending', [])))
    parts.append('- 待确认信息：'+('；'.join(pending) if pending else '本次记录未列出'))
    parts += ['- 模型：'+report.get('model', '未记录'), '- 提示词版本：'+report.get('prompt_version', '历史稿件未记录')]
    return '\n\n'.join(parts)+'\n'
