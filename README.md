# Termux Agent

وكيل برمجي محلي وآمن للأجهزة المحمولة، مصمم للعمل داخل **Termux** مع فصل واضح بين حلقة الاستدلال وأدوات التنفيذ. يوفّر هذا المستودع نواة عملية قابلة للتوسعة بدلاً من منح نموذج لغوي صلاحية مطلقة على الهاتف.

## ما الذي يقدمه المشروع؟

يحتوي المشروع على خادم أدوات محلي متوافق مع نمط MCP عبر `stdio`، وواجهة سطر أوامر، وطبقة صلاحيات تفصل بين **وضع التخطيط** و**وضع البناء**. الأدوات المدمجة قليلة وعالية الإشارة: قراءة الملفات، البحث النصي، تعديل ملف، تنفيذ أمر مضبوط، وإرسال إشعار إلى Termux:API. وتُحفظ الجلسات محلياً في SQLite، مع سجل تغييرات Git يمكن استخدامه للتراجع.

> ملاحظة أمنية: هذا المشروع لا ينفذ أوامر تشغيلية أو يرسل تعليقات إلى GitHub تلقائياً إلا عند تشغيل الأمر صراحةً أو من خلال سير عمل GitHub Actions مفعّل من مالك المستودع.

## البنية

| المكوّن | المسؤولية |
|---|---|
| `termux_agent/permissions.py` | فرض Plan/Build، والتحقق من المسارات والأوامر المسموحة. |
| `termux_agent/session.py` | تخزين الجلسات والرسائل محلياً باستخدام SQLite. |
| `termux_agent/tools.py` | أدوات الملفات والبحث والتنفيذ والتنبيهات. |
| `termux_agent/mcp_server.py` | خادم MCP مبسط عبر `stdio` دون اعتماديات خارجية. |
| `termux_agent/cli.py` | أوامر `plan`, `build`, `session`, و`tool`. |
| `.github/workflows/opencode.yml` | فحص TODOs، مراجعة طلبات السحب، وفرز القضايا بصلاحيات محدودة. |

## التثبيت في Termux

```bash
pkg update
pkg install -y python git ripgrep proot-distro termux-api
termux-setup-storage
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

يجب تثبيت تطبيق **Termux:API** من المصدر نفسه الذي ثُبّت منه تطبيق Termux، ثم اختبار الجسر:

```bash
termux-notification --title 'Termux Agent' --content 'API OK'
```

لتجهيز مساحة عمل glibc معزولة للأدوات التي تحتاج إلى توافق لينكس قياسي:

```bash
proot-distro install debian
proot-distro login debian
apt update && apt install -y python3 python3-pip build-essential git
```

لا يُشغّل الوكيل `proot-distro` تلقائياً؛ بل ينبغي استدعاؤه من أمر عمل صريح بعد التحقق من المسار والصلاحيات.

## التشغيل

```bash
# إنشاء جلسة
termux-agent session new --title 'إصلاح الاختبارات'

# التخطيط: قراءة واستكشاف فقط
termux-agent plan --root . --task 'حل أخطاء الاختبارات'

# البناء: يتطلب تأكيداً صريحاً قبل الأوامر أو التعديلات
termux-agent build --root . --command 'python -m pytest'

# تشغيل خادم الأدوات عبر stdio
termux-agent-mcp --root . --mode plan
```

في وضع البناء، يمكن تمرير `--yes` فقط عندما يكون الاستدعاء مقصوداً ومراجَعاً:

```bash
termux-agent build --root . --command 'python -m pytest' --yes
```

## نموذج MCP

الخادم يرسل ويستقبل رسائل JSON متسلسلة عبر `stdin/stdout`. كل طلب يأخذ الشكل التالي:

```json
{"id":1,"method":"tools/list","params":{}}
{"id":2,"method":"tools/call","params":{"name":"search_text","arguments":{"pattern":"TODO","path":"."}}}
```

الأداة `search_text` تُرجع نتائج محدودة الحجم، بينما تُبقي العمليات على الملفات محصورة داخل جذر مساحة العمل. ويمكن لأي عميل MCP يدعم نقل `stdio` تشغيل الخادم عبر:

```json
{
  "mcpServers": {
    "termux-agent": {
      "command": "termux-agent-mcp",
      "args": ["--root", "/data/data/com.termux/files/home/project", "--mode", "plan"]
    }
  }
}
```

## نموذج الصلاحيات

| الوضع | القراءة | البحث | الكتابة | تنفيذ الأوامر |
|---|---:|---:|---:|---:|
| `plan` | نعم | نعم | لا | لا |
| `build` | نعم | نعم | نعم | نعم، مع قائمة سماح وتأكيد |

الأوامر التنفيذية المسموحة افتراضياً هي أوامر الاختبار والبناء الآمنة نسبياً، مثل `pytest`, `python`, `npm test`, `npm run build`, `git diff`, و`git status`. ويمكن تغيير القائمة عبر `TERMUX_AGENT_ALLOWED_COMMANDS` بصيغة JSON.

## GitHub Actions

يحتوي سير العمل على ثلاثة مسارات:

1. فحص الاختبارات عند كل `push` و`pull_request`.
2. فحص TODOs وإنشاء قضية صيانة عند التشغيل اليدوي أو وفق الجدول الأسبوعي. لا ينشئ قضية إذا كانت قضية مماثلة مفتوحة.
3. إضافة مراجعة تحليلية إلى طلب السحب عند فتحه أو تحديثه، باستخدام `pull-requests: write` فقط.

يُنصح بإبقاء `permissions` في أضيق نطاق، وعدم وضع مفاتيح النماذج أو رموز GitHub داخل الملفات. تشغيل النموذج اللغوي الخارجي اختياري ولم يُفعّل افتراضياً.

## الاختبارات

```bash
python -m pytest
```

## الترخيص

MIT. انظر ملف `LICENSE`.
