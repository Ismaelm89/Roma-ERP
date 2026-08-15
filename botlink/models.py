from django.db import models


class BotAuditLog(models.Model):
    """سجل لكل رسالة بتوصل لبوت تليجرام + الأدوات اللي اتنفّذت + الرد.

    مهم للمراجعة: أي حركة اتعملت من التليجرام تبقى متسجّلة بمين عملها وإمتى.
    """
    BOT_CHOICES = [('OPS', 'بوت العمليات'), ('ADMIN', 'بوت المدير')]

    bot = models.CharField('البوت', max_length=10, choices=BOT_CHOICES, default='OPS')
    telegram_user_id = models.BigIntegerField('Telegram ID', db_index=True)
    telegram_name = models.CharField('الاسم', max_length=120, blank=True)
    allowed = models.BooleanField('مصرّح له', default=True)
    message = models.TextField('الرسالة')
    tools_used = models.TextField('الأدوات اللي اتنفّذت', blank=True)
    reply = models.TextField('الرد', blank=True)
    tokens = models.PositiveIntegerField('التوكنز', default=0)
    ok = models.BooleanField('تمّت', default=True)
    created_at = models.DateTimeField('التاريخ', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'سجل بوت'
        verbose_name_plural = 'سجل البوتات'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_bot_display()} — {self.telegram_name or self.telegram_user_id}'
