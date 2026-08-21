# Termux Agent

وكيل برمجي محلي وآمن للأجهزة المحمولة، مصمم للعمل داخل **Termux** مع فصل واضح بين حلقة الاستدلال وأدوات التنفيذ. يوفّر هذا المستودع نواة عملية قابلة للتوسعة بدلاً من منح نموذج لغوي صلاحية مطلقة على الهاتف.

## ما الذي يقدمه المشروع؟

يحتوي المشروع على خادم أدوات محلي متوافق مع نمط MCP عبر `stdio`، وواجهة سطر أوامر، وطبقة حوكمة تمر عبر **ANALYZING / PREVIEWING / SELF_REVIEW / EXECUTING** قبل السماح بالكتابة أو التنفيذ. الأدوات المدمجة قليلة وعالية الإشارة: قراءة الملفات، البحث النصي، تعديل ملف، تنفيذ أمر مضبوط، وإرسال إشعار إلى Termux:API. وتُحفظ الجلسات محلياً في SQLite، مع سجل تغييرات Git وأحداث حوكمة وأدلة مصنفة يمكن استخدامها للتراجع والمراجعة.

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
termux-agent --root . plan --task 'حل أخطاء الاختبارات'

# عرض حالة الحوكمة
termux-agent --db .termux-agent/sessions.db governance status

# البناء: يتطلب تأكيداً صريحاً قبل الأوامر أو التعديلات
termux-agent --root . build --command 'python -m pytest' --yes

# فتح الواجهة التفاعلية المحلية
termux-agent --root . tui

# أو عبر الأمر المستقل
termux-agent-tui --root . --db ~/.termux-agent/sessions.db

# تشغيل خادم الأدوات عبر stdio
termux-agent-mcp --root . --mode plan
```

في وضع البناء، يمكن تمرير `--yes` فقط عندما يكون الاستدعاء مقصوداً ومراجَعاً. ولعرض الموافقة كخطوة منفصلة:

```bash
termux-agent --root . governance approve
termux-agent --root . build --command 'python -m pytest' --yes
```

## الواجهة التفاعلية المحلية

The TUI uses Python's standard `curses` module, so it needs no web server or network port. The visible screen is intentionally minimal: titles, session controls, governance panels, and footer hints remain hidden. After sending, only the latest message is shown above the bottom question rectangle with `❯ Ask your question...`; a compact metadata line shows `Model`, `Repo`, `Draft`, and `Used`. Full message history and governance data continue to be stored internally in SQLite.

| Key | Action |
|---|---|
| `Enter` or `i` | Open the input prompt and save a message locally. |
| `r` | Refresh the view. |
| `?` | Show the keyboard hint. |
| `q` or `Esc` | Quit. |

On small Termux screens, resize the terminal to at least 40 columns by 7 rows.

### Live token counter

Install the optional tokenizer support in Termux with:

```bash
pip install -e '.[tokens]'
```

While composing a message, the footer updates after every keypress:

```text
Model: gpt-4o-mini  |  Repo: termux-agent  |  Draft: 12 tokens  |  Used: 0
```

`Draft` is counted locally with the selected model's `tiktoken` encoding. `Used` is the accumulated provider usage stored in SQLite and is not guessed. If `tiktoken` is unavailable, the draft value is shown as `—` rather than an invented exact number. The input loop caches the model encoding and metadata, then redraws only the four bottom rows while typing; it does not clear the whole screen or query SQLite on every keypress. Configure the model and repository labels with:

```bash
export TERMUX_AGENT_MODEL="gpt-4o-mini"
export TERMUX_AGENT_REPOSITORY="iraqveo/termux-agent"
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

## نموذج الحوكمة والصلاحيات

| الحالة | القراءة والبحث | الكتابة والتنفيذ | الانتقال التالي |
|---|---:|---:|---|
| `ANALYZING` | نعم | لا | `PREVIEWING` أو `HALTED` |
| `PREVIEWING` | نعم | لا | `SELF_REVIEW` أو `HALTED` |
| `SELF_REVIEW` | نعم | لا | `EXECUTING` أو `HALTED` |
| `EXECUTING` | نعم | نعم، بعد المطابقة الدقيقة | `ANALYZING` عند الفشل أو `HALTED` عند الحد |
| `HALTED` | لا توجد عمليات تنفيذ | لا | جلسة جديدة |

يُسمح بالتنفيذ فقط بعد المرور الصريح بالمراحل الثلاث الأولى. يوقف النظام التنفيذ بعد ثلاث خطوات ناجحة متتابعة، أو بعد تكرار سبب الفشل نفسه مرتين. كل نتيجة تُسجل كدليل `OBSERVED` أو `INFERRED` أو `UNKNOWN` في SQLite.

الأوامر التنفيذية المسموحة افتراضياً هي قائمة **exact argv**، مثل `pytest`, `python -m pytest`, `npm test`, `npm run build`, `git diff`, و`git status`. لا تكفي مطابقة جزء من النص، وتُرفض عوامل shell مثل `&&`, `||`, `;`, `|`, وإعادة التوجيه. ويظل denylist الدفاعي فعالاً ضد `rm`, `sudo`, أغلفة shell، `git push`، وعمليات النشر حتى لو أُضيفت بالخطأ إلى allowlist. ويمكن تغيير القائمة عبر `TERMUX_AGENT_ALLOWED_COMMANDS` بصيغة JSON من سلاسل أو مصفوفات argv.

## GitHub Actions

يحتوي سير العمل على ثلاثة مسارات:

1. فحص الاختبارات عند كل `push` و`pull_request`.
2. فحص TODOs وإنشاء قضية صيانة عند التشغيل اليدوي أو وفق الجدول الأسبوعي. لا ينشئ قضية إذا كانت قضية مماثلة مفتوحة.
3. إضافة مراجعة تحليلية إلى طلب السحب عند فتحه أو تحديثه، باستخدام `pull-requests: write` فقط.

يُنصح بإبقاء `permissions` في أضيق نطاق، وعدم وضع مفاتيح النماذج أو رموز GitHub داخل الملفات. تشغيل النموذج اللغوي الخارجي اختياري ولم يُفعّل افتراضياً.

## الاختبارات

للاختبار المحلي داخل بيئة التطوير:

```bash
python -m pytest
```

لاختبار المشروع فعلياً على جهاز Android داخل Termux، انسخ الأمر التالي إلى Termux. سيقوم بتثبيت Git وPython، وسحب آخر نسخة من المستودع، وتثبيت حزمة الاختبارات، ثم تشغيل فحص البيئة واختبار الحوكمة وMCP وSQLite:

```bash
pkg install -y curl
curl -fsSL https://raw.githubusercontent.com/iraqveo/termux-agent/main/scripts/run-device-smoke-test.sh | bash
```

يفحص الاختبار وجود Termux وGit وPython و`proot-distro` وTermux:API والتخزين المشترك، لكنه لا يعتبر الأدوات الاختيارية فشلاً. ولإرسال إشعار حقيقي عند النهاية:

```bash
curl -fsSL https://raw.githubusercontent.com/iraqveo/termux-agent/main/scripts/run-device-smoke-test.sh | TERMUX_AGENT_SEND_NOTIFICATION=1 bash
```

> إذا كان `curl` غير متاح، استخدم البديل الآمن التالي دون تنفيذ محتوى بعيد مباشرة: `pkg install -y git python` ثم `git clone https://github.com/iraqveo/termux-agent.git` ثم `cd termux-agent && bash scripts/run-device-smoke-test.sh`.

## الترخيص

MIT. انظر ملف `LICENSE`.
