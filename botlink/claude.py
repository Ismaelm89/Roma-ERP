"""عميل Claude (Anthropic Messages API) بـ stdlib بس + حلقة استخدام الأدوات.

بوت العمليات بيدّي Claude مجموعة أدوات مقفولة (بحث/فواتير/إيصالات...) وClaude
بينده عليها لحد ما يوصل للنتيجة، وبعدين يرد على المستخدم بالعربي.
"""
import json
import urllib.error
import urllib.request

API_URL = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2023-06-01'
MODEL = 'claude-opus-5'
MAX_TOKENS = 4096
# سقف لفات الأدوات في الرسالة الواحدة — يمنع أي لفة لا نهائية.
MAX_TOOL_ROUNDS = 12


class ClaudeError(Exception):
    pass


def _post(api_key, payload, timeout=180):
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'content-type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': API_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise ClaudeError(f'HTTP {e.code}: {e.read()[:400].decode("utf-8", "replace")}')
    except Exception as e:
        raise ClaudeError(str(e))


def run(api_key, system, tools, handlers, history, user_text, on_step=None):
    """بيشغّل لفة كاملة: رسالة المستخدم → أدوات → رد نهائي.

    history: list of message dicts (بيتعدّل في المكان عشان المحادثة تفضل متواصلة).
    handlers: {tool_name: callable(**input) -> str}
    on_step: callback اختياري بيتنده باسم كل أداة (لعرض التقدّم في تليجرام).
    بيرجّع (نص الرد, إجمالي التوكنز).
    """
    history.append({'role': 'user', 'content': user_text})
    total_in = total_out = 0

    for _ in range(MAX_TOOL_ROUNDS):
        resp = _post(api_key, {
            'model': MODEL,
            'max_tokens': MAX_TOKENS,
            'system': system,
            'tools': tools,
            'messages': history,
        })
        usage = resp.get('usage') or {}
        total_in += usage.get('input_tokens', 0)
        total_out += usage.get('output_tokens', 0)

        content = resp.get('content') or []
        history.append({'role': 'assistant', 'content': content})

        tool_uses = [c for c in content if c.get('type') == 'tool_use']
        if not tool_uses:
            text = '\n'.join(c.get('text', '') for c in content
                             if c.get('type') == 'text').strip()
            return text or '(مفيش رد)', total_in + total_out

        results = []
        for tu in tool_uses:
            name = tu.get('name')
            args = tu.get('input') or {}
            if on_step:
                on_step(name, args)
            fn = handlers.get(name)
            if fn is None:
                out, err = f'الأداة «{name}» مش موجودة.', True
            else:
                try:
                    out, err = fn(**args), False
                except Exception as e:                # الخطأ بيرجع لكلود عشان يتصرف
                    out, err = f'{type(e).__name__}: {e}', True
            results.append({
                'type': 'tool_result',
                'tool_use_id': tu.get('id'),
                'content': str(out)[:20000],
                'is_error': err,
            })
        history.append({'role': 'user', 'content': results})

    return ('وقفت بعد عدد كبير من الخطوات من غير نتيجة نهائية — '
            'جرّب تسأل بصيغة أوضح.'), total_in + total_out
