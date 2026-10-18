export type Data = Record<string, any>;
export const requestId = () => crypto.randomUUID ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(20))).map(x=>x.toString(16).padStart(2,'0')).join('');
export async function api<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, {
    method, credentials: 'same-origin',
    headers: {'Content-Type':'application/json', 'X-Store-Request':'1'},
    ...(body !== undefined ? {body:JSON.stringify(body)} : {}),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : '输入无效或操作失败，请检查后重试');
  }
  return response.json();
}
export const time = (date?: string) => date ? new Date(date).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
export const statuses: Data = {queued:'排队中',running:'进行中',completed:'已完成',failed:'失败',waiting_remote:'仍在处理',needs_input:'待补充',cancelled:'已停止',passed:'可使用',manual_passed:'人工已通过',needs_review:'需要调整',unchecked:'待检查'};
