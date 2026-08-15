from django.contrib import admin

from .models import BotAuditLog


@admin.register(BotAuditLog)
class BotAuditLogAdmin(admin.ModelAdmin):
    """قراءة بس — ده سجل مراجعة، مش بيتعدّل من الأدمن."""
    list_display = ('created_at', 'bot', 'telegram_name', 'allowed', 'ok',
                    'short_message', 'tools_used', 'tokens')
    list_filter = ('bot', 'allowed', 'ok', 'created_at')
    search_fields = ('telegram_name', 'message', 'reply', 'tools_used')
    date_hierarchy = 'created_at'
    readonly_fields = tuple(f.name for f in BotAuditLog._meta.fields)

    def short_message(self, obj):
        return (obj.message or '')[:70]
    short_message.short_description = 'الرسالة'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
