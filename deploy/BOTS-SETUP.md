# تشغيل بوتات التليجرام (بوت المدير + بوت العمليات)

الكود كله متنزّل على السيرفر. فاضل بس المفاتيح — وهي بتتحط **مرة واحدة** في
`/opt/roma-erp/.env`.

---

## 1) هات المفاتيح (3 حاجات)

### أ) مفتاح Anthropic
من <https://console.anthropic.com> → **API Keys** → **Create Key** → انسخه
(بيبدأ بـ `sk-ant-`).

### ب) البوتات (اتنين)
افتح تليجرام وكلّم **@BotFather**:

```
/newbot
```
- الاسم: `Roma Admin` — واليوزر مثلاً `roma_admin_bot` → هيديك توكن.
- كرّرها تاني للبوت التاني: `Roma Ops` / `roma_ops_bot` → توكن تاني.

### ج) رقم التليجرام بتاعك
كلّم **@userinfobot** في تليجرام → هيرد عليك بـ `Id: 123456789`.

---

## 2) حطّهم في `.env` على السيرفر

ادخل على السيرفر:

```bash
ssh root@13.140.146.81
```

وبعدين شغّل الأمر ده **بعد ما تبدّل القيم** (سيب علامات التنصيص):

```bash
cd /opt/roma-erp && cat >> .env <<'EOF'
ANTHROPIC_API_KEY=حط_المفتاح_هنا
TELEGRAM_ADMIN_BOT_TOKEN=توكن_بوت_المدير
TELEGRAM_ADMIN_ALLOWED_IDS=رقم_التليجرام_بتاعك
TELEGRAM_OPS_BOT_TOKEN=توكن_بوت_العمليات
TELEGRAM_OPS_ALLOWED_IDS=رقم_التليجرام_بتاعك
EOF
chmod 600 .env
```

> **`TELEGRAM_OPS_ALLOWED_IDS`** = مين مسموحله يستخدم بوت العمليات. لو هتدّيه
> لموظف، ضيف رقمه بفاصلة: `123456789,987654321`. أي حد تاني البوت هيرفضه.
>
> **`TELEGRAM_ADMIN_ALLOWED_IDS`** سيبه **رقمك إنت بس** — البوت ده معاه صلاحية
> كاملة على السيرفر والكود.

---

## 3) شغّل البوتات

```bash
cd /opt/roma-erp && docker compose --profile bots up -d --build opsbot && cp deploy/roma-admin-bot.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now roma-admin-bot && sleep 5 && docker compose logs --tail 5 opsbot && systemctl is-active roma-admin-bot
```

المفروض تشوف: `بوت العمليات شغّال: @...` و `active`.

---

## 4) جرّب

افتح كل بوت في تليجرام واكتب `/start`.

- **بوت المدير:** «قولي رصيد المخزون» أو «عدّل كذا في الكود ونزّله».
- **بوت العمليات:** «رصيد جابر كام؟» — وجرّب حركة: «اعمل إيصال قبض 5000 من جابر
  على بنك فيصل» → هيقولك هيعمل إيه ويستنى تقوله **تمام**.

---

## أوامر مفيدة

| | |
|---|---|
| لوج بوت العمليات | `docker compose logs -f opsbot` |
| لوج بوت المدير | `journalctl -u roma-admin-bot -f` |
| إعادة تشغيل | `docker compose restart opsbot` / `systemctl restart roma-admin-bot` |
| إيقاف | `docker compose stop opsbot` / `systemctl stop roma-admin-bot` |

سجل كل الرسايل والحركات موجود في الأدمن تحت **«سجل البوتات»**.

---

## ملاحظات أمان

- `.env` مش بيترفع على git أبداً — المفاتيح بتفضل على السيرفر بس.
- البوتات بترد **بس** على الأرقام اللي في القايمة البيضا؛ أي حد تاني بيترفض
  وبيتسجّل في السجل.
- بوت العمليات مقفول: مفيش عنده ترمينال ولا كود، ومش بيقدر يلمس الوصفات ولا
  أسعار المنتجات ولا الإعدادات ولا يحذف حاجة.
- أي حركة بتغيّر بيانات في بوت العمليات مقفولة في الكود ورا تأكيد — مش مجرد
  تعليمات للموديل.
- لو ضاع تليفونك: امسح التوكن من BotFather (`/revoke`) أو شيل رقمك من القايمة
  البيضا وأعد التشغيل.
