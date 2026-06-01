# دليل نشر Roma ERP على سيرفر Hetzner

دي الخطوات بالترتيب لنشر السيستم على سيرفر بعيد بحيث يشتغل 24/7 من غير ما اللاب توب يكون مفتوح.

## نظرة عامة

| المرحلة | المدة | تقدر تشتغلها قبل غيرها؟ |
|---|---|---|
| 1. تسجيل Hetzner + إنشاء VPS | 10 دقايق | ✓ |
| 2. سيتب DNS للـ domain | 5 دقايق + انتظار 10 دقايق | بعد المرحلة 1 |
| 3. تجهيز الكود على GitHub | 10 دقايق | متوازي مع 1 |
| 4. تشغيل سكريبت سيتب السيرفر | 5 دقايق | بعد 1، 2، 3 |
| 5. ملء `.env` + النشر | 10 دقايق | بعد 4 |
| 6. نقل الداتا من اللاب | 5 دقايق | بعد 5 |

---

## المرحلة 1: إنشاء VPS على Hetzner

1. اعمل حساب على [https://accounts.hetzner.com/signUp](https://accounts.hetzner.com/signUp)
2. فعّل الإيميل + ضيف طريقة دفع (Visa/Mastercard)
3. روح [Hetzner Cloud Console](https://console.hetzner.cloud) → "New Project" → سميه "Roma ERP"
4. داخل المشروع → "Add Server" واختار:
   - **Location**: Falkenstein (FSN1)
   - **Image**: Ubuntu 24.04
   - **Type**: **CX22** (4GB RAM, 2 vCPU، €4.51/شهر — الأنسب للبداية)
   - **SSH key**: ارفع المفتاح العام بتاعك (لو معندكش، تعليمات تحت)
   - **Name**: roma-erp
5. اضغط "Create & Buy now"
6. هيظهر **IP العام** للسيرفر — احفظه (مثلاً `49.12.45.123`)

### كيف تعمل SSH key (على Windows)

افتح PowerShell واكتب:
```powershell
ssh-keygen -t ed25519 -C "roma-erp"
# اضغط Enter لقبول المسار الافتراضي
# اضغط Enter (اتركه فاضي) للـ passphrase
cat $env:USERPROFILE\.ssh\id_ed25519.pub
```

انسخ السطر اللي يبدأ بـ `ssh-ed25519` ولصقه في Hetzner عند إضافة SSH key.

---

## المرحلة 2: ضبط DNS للـ domain

في لوحة تحكم الـ domain بتاعك (Namecheap / GoDaddy / إلخ):

1. روح إعدادات DNS لـ domain بتاعك
2. ضيف A record:
   - **Type**: A
   - **Host**: app (أو @ لو عايز الـ root domain)
   - **Value**: الـ IP من المرحلة 1
   - **TTL**: 1800 ثانية
3. احفظ، واستنى من 5-15 دقيقة عشان DNS ينتشر

اختبار: من PowerShell:
```powershell
nslookup app.your-domain.com
```
لازم يرجع الـ IP بتاعك.

---

## المرحلة 3: رفع الكود على GitHub

من PowerShell في مجلد المشروع:

```powershell
cd C:\Users\MahmoudIsmael\Desktop\Roma-ERP
git init
git add .
git commit -m "Initial commit"
# اعمل Repository فاضي على github.com (سميه roma-erp)
git remote add origin https://github.com/YOUR_USERNAME/roma-erp.git
git branch -M main
git push -u origin main
```

ملاحظة: لو ما عندكش git مثبت، حمّله من [git-scm.com](https://git-scm.com/download/win).

---

## المرحلة 4: سيتب السيرفر

من PowerShell، اعمل SSH للسيرفر:
```powershell
ssh root@<your-server-ip>
```

داخل السيرفر، شغّل:
```bash
# تنزيل وتشغيل سكريبت السيتب
curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/roma-erp/main/deploy/setup-server.sh -o setup-server.sh
bash setup-server.sh
```

السكريبت ده:
- بيحدّث النظام
- بيثبّت Docker + Compose + git + ufw firewall
- بيفتح ports 80, 443
- بيفعّل automatic security updates

---

## المرحلة 5: تشغيل التطبيق

لسه على السيرفر:

```bash
# سحب الكود
git clone https://github.com/YOUR_USERNAME/roma-erp.git /opt/roma-erp
cd /opt/roma-erp

# تجهيز ملف الإعدادات
cp .env.example .env
nano .env
```

في الـ `.env` املأ:
- `DOMAIN=app.your-domain.com`
- `DJANGO_ALLOWED_HOSTS=app.your-domain.com`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://app.your-domain.com`
- `DJANGO_SECRET_KEY=<مفتاح طويل عشوائي>` — اعمله بـ:
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(64))"
  ```
- `POSTGRES_PASSWORD=<كلمة سر طويلة عشوائية>` — اعملها بنفس الطريقة
- `LE_EMAIL=ايميلك@example.com`

احفظ بـ `Ctrl+O` ثم `Ctrl+X`.

ثم نشّر:
```bash
bash deploy/first-deploy.sh
```

السكريبت بيعمل:
1. بيبني الـ Docker image
2. بيشغّل Postgres + Django + nginx
3. بيطلب شهادة SSL مجانية من Let's Encrypt
4. بيعمل HTTPS auto-renew

افتح: **`https://app.your-domain.com`** — هيظهرلك صفحة لوجين فيها قفل أخضر.

اعمل أول مستخدم admin:
```bash
docker compose exec web python manage.py createsuperuser
```

---

## المرحلة 6: نقل الداتا من اللاب توب

**على اللاب توب** (PowerShell):

```powershell
cd C:\Users\MahmoudIsmael\Desktop\Roma-ERP
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe manage.py dumpdata `
    --exclude contenttypes --exclude auth.permission `
    --natural-foreign --natural-primary `
    -o data_dump.json
```

ارفع الملف للسيرفر:
```powershell
scp data_dump.json root@<your-server-ip>:/opt/roma-erp/
```

**على السيرفر**:
```bash
cd /opt/roma-erp
bash deploy/migrate_data.sh data_dump.json
```

كل العملاء + الفواتير + الـ COA + الجرد ينتقلوا. افتح الـ admin من Hetzner واتأكد إن كل حاجة ظاهرة.

---

## التشغيل اليومي

### تشغيل أمر فعل في الـ container
```bash
docker compose exec web python manage.py shell
docker compose exec web python manage.py recompute_stock
```

### رفع تحديث جديد
على اللاب توب: عدّل الكود، commit، push:
```powershell
git add .
git commit -m "وصف التعديل"
git push
```

على السيرفر:
```bash
cd /opt/roma-erp
git pull
docker compose up -d --build web
docker compose exec web python manage.py migrate --noinput
```

### Backups
أضف للسيرفر سطر cron عشان backup يومي:
```bash
echo "0 3 * * * cd /opt/roma-erp && bash deploy/backup.sh >> /var/log/roma-backup.log 2>&1" \
  | crontab -
```

البكاب يتعمل كل يوم 3 صباحاً في `/opt/roma-erp/deploy/backups/`.

لو عايز ينزل عندك على اللاب توب أسبوعياً:
```powershell
scp -r root@<your-server-ip>:/opt/roma-erp/deploy/backups/ ./
```

### مراقبة الـ logs
```bash
docker compose logs -f web    # logs الـ Django
docker compose logs -f nginx  # logs الـ nginx
```

### إعادة تشغيل
```bash
docker compose restart        # كل الخدمات
docker compose restart web    # Django فقط
```

---

## مشاكل شائعة

| المشكلة | الحل |
|---|---|
| `https://...` بيقول "Not secure" بعد الـ deploy | استنى 2 دقيقة وحاول تاني — Let's Encrypt محتاج DNS propagated |
| الـ admin بيرجع 502 Bad Gateway | `docker compose restart web` |
| الـ DB احتاج reset كامل | `docker compose down -v` (⚠️ بيمسح كل الداتا) ثم `bash deploy/first-deploy.sh` |
| نسيت password admin | `docker compose exec web python manage.py changepassword admin` |

---

## التكلفة الشهرية المتوقعة

| العنصر | السعر/شهر |
|---|---|
| Hetzner CX22 VPS | €4.51 (≈$5) |
| Domain (.com) | $1 (≈$10/سنة) |
| Backups على Hetzner Volume (10GB) | €0.44 (اختياري) |
| **الإجمالي** | **~$6-7/شهر** |

Let's Encrypt SSL مجاناً تماماً (auto-renew).
