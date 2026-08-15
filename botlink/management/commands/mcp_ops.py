"""خادم MCP لأدوات العمليات (stdio, JSON-RPC 2.0) — من غير أي مكتبات إضافية.

بيتشغّل جوّه كونتينر الويب (عشان يوصل لقاعدة البيانات) و`claude` بينده عليه من
المضيف عن طريق `docker compose exec -T`. بكده بوت العمليات بيشتغل على اشتراك
Claude العادي — من غير مفتاح API مدفوع — وبرضه بيفضل مقفول على الأدوات دي بس.

التشغيل (مش بإيدك عادةً):  python manage.py mcp_ops
"""
import json
import sys

from django.core.management.base import BaseCommand

from botlink import tools_ops

PROTOCOL = '2024-11-05'


def _reply(msg_id, result=None, error=None):
    out = {'jsonrpc': '2.0', 'id': msg_id}
    if error is not None:
        out['error'] = error
    else:
        out['result'] = result
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def _call(name, args):
    """بينفّذ الأداة — مع نفس قفل التأكيد بتاع بوت العمليات."""
    fn = tools_ops.HANDLERS.get(name)
    if fn is None:
        return f'الأداة «{name}» مش موجودة.', True
    args = dict(args or {})
    if name not in tools_ops.READ_ONLY:
        if not bool(args.pop('confirm', False)):
            return ('محتاج تأكيد المستخدم الأول. اعرض عليه الحركة دي بالتفصيل '
                    'واسأله «تمام؟»، وأول ما يوافق نادي نفس الأداة تاني بنفس '
                    'البيانات + confirm=true:\n\n'
                    + tools_ops.summarize(name, args)), False
    else:
        args.pop('confirm', None)
    try:
        return str(fn(**args)), False
    except Exception as e:
        return f'{type(e).__name__}: {e}', True


class Command(BaseCommand):
    help = 'خادم MCP لأدوات العمليات (stdio)'

    def handle(self, *args, **opts):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            method, msg_id = msg.get('method'), msg.get('id')
            if method == 'initialize':
                _reply(msg_id, {
                    'protocolVersion': PROTOCOL,
                    'capabilities': {'tools': {}},
                    'serverInfo': {'name': 'roma-ops', 'version': '1.0.0'},
                })
            elif method in ('notifications/initialized', 'notifications/cancelled'):
                continue                      # إشعارات — مالهاش رد
            elif method == 'tools/list':
                _reply(msg_id, {'tools': [
                    {'name': t['name'], 'description': t['description'],
                     'inputSchema': t['input_schema']} for t in tools_ops.TOOLS]})
            elif method == 'tools/call':
                p = msg.get('params') or {}
                text, is_err = _call(p.get('name'), p.get('arguments'))
                _reply(msg_id, {'content': [{'type': 'text', 'text': text[:20000]}],
                                'isError': is_err})
            elif method == 'ping':
                _reply(msg_id, {})
            elif msg_id is not None:
                _reply(msg_id, error={'code': -32601,
                                      'message': f'method not found: {method}'})
