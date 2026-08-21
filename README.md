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

## Real API connectivity and interactive chat

The agent can send real multi-turn requests to any OpenAI-compatible chat-completions endpoint. The API key is read only from the Termux process environment and is never written to SQLite, displayed in the TUI, committed to Git, or included in error messages. Do not paste the key into chat or into a source file.

First configure the provider for the current shell. The following example uses OpenRouter; replace the model with one that is visible and enabled in your account. Do not assume that a model name is funded merely because it exists in a public catalog.

```bash
read -rsp "API key: " TERMUX_AGENT_API_KEY
export TERMUX_AGENT_API_KEY
echo
export TERMUX_AGENT_BASE_URL="https://openrouter.ai/api/v1"
export TERMUX_AGENT_MODEL="your-enabled-model-id"
export TERMUX_AGENT_REPOSITORY="iraqveo/termux-agent"
```

Before opening the TUI, discover the model IDs exposed by the configured provider and run one small request:

```bash
termux-agent --root "$HOME/termux-agent" api models
termux-agent --root "$HOME/termux-agent" api test --prompt "Reply with exactly: TERMUX_AGENT_API_OK"
```

The `api models` command calls the provider's `/models` endpoint. The `api test` command calls `/chat/completions`, prints the provider reply and usage totals, and records only the model, repository, and token counts in the local SQLite session database. A provider response such as HTTP 402 means the key reached the provider but the account needs credits; HTTP 404 commonly means the selected model is not enabled or does not exist at that endpoint.

### Start the real chat inside Termux

After the one-request test succeeds, launch the interactive chat:

```bash
termux-agent --root "$HOME/termux-agent" tui
```

Each submitted message is saved locally, sent together with the recent conversation history, and followed by the assistant response in the same TUI. The default context contains the latest 20 user/assistant messages; change it with `TERMUX_AGENT_MAX_HISTORY`. An optional system instruction can be supplied through `TERMUX_AGENT_SYSTEM_PROMPT`. Neither setting contains or stores the API key.

```bash
export TERMUX_AGENT_MAX_HISTORY=20
export TERMUX_AGENT_SYSTEM_PROMPT="You are a concise coding assistant. Never execute commands without explicit governance approval."
termux-agent --root "$HOME/termux-agent" tui
```

The TUI uses Python's standard `curses` module, so it needs no web server or network port. The visible screen remains minimal: session controls and governance panels stay hidden, while the chat transcript shows `You` and `Agent` messages above the single bottom input rectangle. The footer shows `Model`, `Repo`, and accumulated provider `Used` tokens. If no key is configured, the interface still works as a local draft/session viewer and tells the user to set `TERMUX_AGENT_API_KEY` before expecting an online reply.

## الواجهة التفاعلية المحلية

| Key | Action |
|---|---|
| `Enter` or `i` | Open the input prompt, send the message to the configured model, and display the assistant reply. |
| `r` | Refresh the view. |
| `?` | Show the keyboard hint. |
| `q` or `Esc` | Quit. |

On small Termux screens, resize the terminal to at least 40 columns by 7 rows.

### Input responsiveness and usage footer

The live Draft tokenizer has been removed from the typing path to keep input responsive on mobile hardware. While composing, a visible caret appears after the current text:

```text
❯ Ask your question...▌
```

The footer shows only persistent provider usage:

```text
Model: gpt-4o-mini  |  Repo: termux-agent  |  Used: 0
```

`Used` is the accumulated provider usage stored in SQLite and is not guessed. The input loop caches metadata, redraws only the four bottom rows, and does not query SQLite or run tokenization on every keypress. Configure the model and repository labels with:

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
