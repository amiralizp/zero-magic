# Roadmap: Gantry (magic-zero), Week 4

> هر مرحله یک session. فقط اولین مرحله بدون تیک را انجام بده، بعد بایست و منتظر من بمان.
> قوانین Git در AGENTS.md است. بدون اجازه من commit یا push نکن.

## بخش: آماده‌سازی

- [x] **S0 — نصب OpenCode و اتصال به OpenRouter**  (branch: `step/S0-<slug>`)
  - **Goal:** ابزار کار را آماده کنی تا agent بتواند داخل پوشه پروژه کار کند.
  - **Tasks:**
    - نصب: در PowerShell دستور `npm i -g opencode-ai` را بزن (یا راهنمای opencode.ai را ببین).
    - وارد پوشه پروژه شو: `cd "C:\Users\M\Documents\Default Project\magic-zero"` و بنویس `opencode`.
    - داخل OpenCode بزن `/connect`، گزینه OpenRouter را انتخاب کن و API Key را وارد کن. بعد با `/models` یک مدل انتخاب کن.
    - کلید را هرگز داخل فایل‌های پروژه نگذار؛ OpenCode خودش آن را جدا نگه می‌دارد.
  - **Prompt:** `Read the project tree and summarize it in 10 lines. Do not change any file.`
  - **Done when:** agent خلاصه‌ای از ساختار می‌دهد و `git status` تمیز می‌ماند.
  - **Commit:** none

- [x] **S1 — اجازه‌ها و پروتکل Git**  (branch: `step/S1-<slug>`)
  - **Goal:** مطمئن شوی agent بدون اجازه تو commit، push یا حذف نمی‌کند. این مرحله «ایمنی» کل مسیر است.
  - **Tasks:**
    - شاخه بساز: `git switch -c step/S1-permissions`.
    - فایل `opencode.json` را در ریشه پروژه بساز (متن در صفحه «پروتکل Git»). این فایل راز ندارد و commit می‌شود.
    - بخش «Git protocol» را به انتهای `AGENTS.md` (و یک نسخه کوتاه در `CLAUDE.md`) اضافه کن.
    - اگر نسخه OpenCode تو یکی از کلیدها را نشناخت، با `/help` و مستندات opencode.ai تطبیقش بده.
  - **Prompt:** `Create opencode.json and add the Git protocol section to AGENTS.md exactly as I paste below. Then run `git status` and propose a commit. Wait for my OK.`
  - **Done when:** `git status` بدون سؤال اجرا می‌شود، اما `git commit` از تو اجازه می‌خواهد.
  - **Commit:** `chore(agent): add opencode permissions and git protocol`

- [x] **S2 — نقطه شروع امن**  (branch: `step/S2-<slug>`)
  - **Goal:** اگر وسط راه چیزی خراب شد، بتوانی به یک حالت سالم برگردی.
  - **Tasks:**
    - `pytest -q` را اجرا کن. اگر قرمز بود، همان را یادداشت کن؛ قرار نیست الان درستش کنیم.
    - `git remote -v` را بررسی کن که ریپو روی GitHub وصل است.
    - این فایل ROADMAP.md را در `docs/ROADMAP.md` بگذار و commit کن.
    - برچسب بزن: `git tag baseline-before-week4`.
  - **Prompt:** `Run pytest -q and report the result. Then add docs/ROADMAP.md with the content I provide. Change nothing else.`
  - **Done when:** برچسب `baseline-before-week4` وجود دارد و ROADMAP روی شاخه است.
  - **Commit:** `docs(roadmap): add project roadmap`

## بخش: شناخت وضع فعلی

- [x] **S3 — ممیزی بک‌اند و نوشتن critique.md**  (branch: `step/S3-<slug>`)
  - **Goal:** بفهمی کد فعلی کجا با معماری سه‌لایه فاصله دارد. لیست این مرحله مبنای refactor است. (تحویل روز ۱۷)
  - **Tasks:**
    - اول خودت ۱۵ دقیقه `app/api/cards.py`، `app/services/cards.py` و `app/store.py` را بخوان. برای هر مورد یک مثال بنویس: coupling، cohesion، layering، جهت وابستگی.
    - کلید Tab را بزن تا به حالت **Plan** بروی (agent فقط می‌خواند و چیزی تغییر نمی‌دهد). همین ممیزی را از او بگیر.
    - فایل `docs/critique.md` را بساز: چهار مورد با «فایل:خط»، جدول «چه چیزی به کجا برود»، و بخش «agent چه دید که من ندیدم / کجا اشتباه کرد».
  - **Prompt:** `Plan mode. Audit app/ and list, with file:line: (1) api code that touches the store or SQL directly, (2) business rules living outside app/services, (3) services importing fastapi or SQL libraries, (4) store/db code importing services. For each, say which layer it should move to. Do not edit files.`
  - **Done when:** `critique.md` چهار مورد واقعی با شماره خط دارد و تفاوت نقد تو با نقد agent نوشته شده است.
  - **Commit:** `docs(audit): add critique of current backend`

## بخش: تثبیت معماری

- [x] **S4 — نوشتن architecture.md**  (branch: `step/S4-<slug>`)
  - **Goal:** مرز لایه‌ها را روی کاغذ بیاوری تا تو، agent و تست معماری همه به یک متن تکیه کنند. مهم‌ترین توصیه طرح خودت همین است.
  - **Tasks:**
    - فایل موجود `docs/architecture.md` را به‌روز کن (یا اگر ندارد بساز).
    - بخش ۱: سه لایه با جدول «چه کاری مجاز / چه کاری ممنوع» (صفحه بعد را ببین).
    - بخش ۲: سه ویژگی کیفی برتر. پیشنهاد: **امنیت، قابلیت تست، نگه‌داری‌پذیری**.
    - بخش ۳: سبک انتخاب‌شده: یک بک‌اند لایه‌ای + یک worker + یک دیتابیس.
    - بخش ۴: گزینه‌های ردشده (microservices، event-driven، modular monolith) و دلیل هر کدام.
  - **Prompt:** `Update docs/architecture.md with 4 sections: three-layer boundaries (allowed/forbidden table), top 3 qualities, chosen style, rejected options with reasons. Use the content I provide. Do not touch code.`
  - **Done when:** می‌توانی در ۲ دقیقه بگویی هر لایه چه می‌کند، چه نمی‌کند، و چرا این سبک را انتخاب کردی.
  - **Commit:** `docs(arch): define three-layer boundaries and style`

- [x] **S5 — نوشتن ADRها**  (branch: `step/S5-<slug>`)
  - **Goal:** «چرا»ی تصمیم‌ها را ثبت کنی تا بحث تکراری نشود و بتوانی در دفاع توضیح بدهی.
  - **Tasks:**
    - در `docs/adr/` چهار فایل بساز؛ هر کدام: وضعیت، زمینه، تصمیم، پیامدها، چطور چک می‌شود.
    - `0007` معماری لایه‌ای با لایه Repository (جایگزین نام store).
    - `0008` PostgreSQL + Alembic به‌جای SQL Server (جایگزین 0006).
    - `0009` احراز هویت با توکن و نقش‌ها به‌جای هدر `X-Actor-Id` (جایگزین 0002).
    - `0010` سه ویژگی کیفی برتر و انتخاب سبک (بک‌اند + worker + یک دیتابیس).
    - وضعیت 0002 و 0006 را به «جایگزین شده با ...» تغییر بده.
  - **Prompt:** `Write ADRs 0007-0010 in docs/adr/ following the format of the existing ADRs. Mark 0002 and 0006 as superseded. Use the decisions I describe. Do not touch code.`
  - **Done when:** چهار ADR وجود دارد و هر کدام بخش «چطور چک می‌شود» دارد (مثلاً: تست معماری).
  - **Commit:** `docs(adr): add ADR 0007-0010`

- [ ] **S6 — قوانین agent (AGENTS.md و CLAUDE.md)**  (branch: `step/S6-<slug>`)
  - **Goal:** هر agent قبل از کار، قوانین معماری را بخواند و رعایت کند.
  - **Tasks:**
    - یک خط اضافه کن: «Read docs/architecture.md and the ADRs and follow them.»
    - سه قانون لایه‌ها را کوتاه بنویس (api بدون منطق، service بدون SQL، repository بدون قانون).
    - فایل‌های ممنوع را بنویس: `.env`، `backups/`، `.venv`.
    - قانون «برای سبز شدن، تست را دستکاری نکن» را اضافه کن.
  - **Prompt:** `Add the architecture rules to AGENTS.md and a short matching version to CLAUDE.md. Keep both files consistent.`
  - **Done when:** هر دو فایل یک پیام یکسان درباره لایه‌ها و فایل‌های ممنوع دارند.
  - **Commit:** `docs(agent): add architecture rules to agent files`

- [ ] **S7 — تست معماری (اول قرمز)**  (branch: `step/S7-<slug>`)
  - **Goal:** قوانین لایه‌ها خودکار چک شوند؛ اگر agent عجله کرد، تست جلویش را بگیرد. (Fitness Function)
  - **Tasks:**
    - فایل `tests/test_architecture.py` را بساز. با ماژول `ast` بخش `import`ها را می‌خواند، نه کل کد را.
    - قانون‌ها: api نباید Repository/SQL را import کند؛ services نباید `fastapi` یا SQL را import کند؛ repositories نباید services یا api را import کنند؛ فقط `app/ai/` به سرویس مدل زبانی وصل شود.
    - چون هنوز refactor نشده، تست قرمز می‌شود. همین خوب است: تخلف‌های واقعی را نشان می‌دهد.
    - برای رعایت قانون «commit فقط وقتی سبز»، تست را موقتاً با `@pytest.mark.xfail` علامت بزن. در S8 برش می‌داریم.
  - **Prompt:** `Create tests/test_architecture.py using the ast module to enforce the import rules in docs/architecture.md. Run it, show me the violations it finds, then mark it xfail until the refactor is done.`
  - **Done when:** تست اجرا می‌شود و فهرست تخلف‌ها را با نام فایل نشان می‌دهد.
  - **Commit:** `test(arch): add architecture fitness tests (xfail)`

- [ ] **S8 — Refactor تا سبز شدن**  (branch: `step/S8-<slug>`)
  - **Goal:** کد را به معماری ثبت‌شده برسانی، بدون عوض شدن رفتار برنامه.
  - **Tasks:**
    - پوشه `app/repositories/` بساز: یک interface (Protocol)، پیاده‌سازی `memory.py` (همان InMemoryStore فعلی) و موقتاً `sql_server.py`.
    - هر قانون تجاری که هنوز در api است را به `app/services/` ببر.
    - services فقط از interface استفاده کنند، نه از SQL و نه از کلاس مشخص.
    - **ماژول‌به‌ماژول** جلو برو: cards، بعد comments، assignment، prds. بعد از هر ماژول `pytest -q` و یک commit.
    - در پایان `xfail` را از تست معماری بردار.
  - **Prompt:** `Refactor one module at a time, starting with cards. After each module run pytest -q and the architecture test. HTTP behavior must not change. Show the diff and ask before each commit.`
  - **Done when:** همه تست‌های قبلی و تست معماری سبز است و پاسخ‌های API مثل قبل است.
  - **Commit:** `refactor(cards): move rules to services, use repository interface  (برای هر ماژول جدا)`

## بخش: PostgreSQL

- [ ] **S9 — راه‌اندازی PostgreSQL و اتصال**  (branch: `step/S9-<slug>`)
  - **Goal:** یک دیتابیس واقعی (طبق ADR 0008) که داده‌ها بعد از ری‌استارت بمانند.
  - **Tasks:**
    - با Docker: `docker run --name gantry-pg -e POSTGRES_PASSWORD=<رمز-خودت> -e POSTGRES_DB=gantry -p 5432:5432 -d postgres:16` (یا نصب‌کننده رسمی PostgreSQL).
    - در `.env` بنویس: `DATABASE_URL=postgresql+psycopg://postgres:<رمز>@localhost:5432/gantry`. در `.env.example` فقط الگو بگذار، بدون رمز.
    - به requirements اضافه کن: `sqlalchemy`, `alembic`, `psycopg[binary]`.
  - **Prompt:** `Add sqlalchemy, alembic and psycopg[binary] to requirements.txt and DATABASE_URL to config.py and .env.example (no password). Do not read or print my .env file.`
  - **Done when:** یک اتصال آزمایشی `SELECT 1` موفق است.
  - **Commit:** `chore(db): add postgres settings and dependencies`

- [ ] **S10 — Alembic و دو migration**  (branch: `step/S10-<slug>`)
  - **Goal:** تغییر دیتابیس هم مثل کد «نسخه‌دار» و قابل برگشت شود.
  - **Tasks:**
    - `alembic init migrations` و تنظیم `DATABASE_URL`.
    - migration ۱ «initial schema»: جدول‌های actors، cards، comments، prds، audit_log (همان‌هایی که الان داری).
    - migration ۲ «add users table»: جدول users با `id`, `username` (یکتا), `password_hash`, `role`, `actor_id`, `created_at`.
    - ثابت کن برگشت‌پذیر است: `alembic upgrade head` ← `alembic downgrade -1` ← دوباره `upgrade head`.
  - **Prompt:** `Set up Alembic and create exactly two migrations: initial schema (match current tables) and add users table. Prove downgrade -1 then upgrade head works.`
  - **Done when:** `alembic history` دو نسخه نشان می‌دهد و رفت‌وبرگشت بدون خطاست.
  - **Commit:** `feat(db): add alembic with two migrations`

- [ ] **S11 — Repository واقعی، تست ماندگاری و بکاپ**  (branch: `step/S11-<slug>`)
  - **Goal:** جایگزین SqlServerStore شوی و ثابت کنی کارت‌ها بعد از ری‌استارت می‌مانند.
  - **Tasks:**
    - `app/repositories/postgres.py` را با همان interface بنویس و با تنظیمات انتخاب کن.
    - همان تست‌های repository را روی memory و postgres هر دو اجرا کن (parametrize).
    - تست ماندگاری: کارت بساز، سرور را خاموش و روشن کن، کارت باید باشد.
    - بکاپ: یا با `pg_dump` بازنویسی کن یا دکمه را موقتاً بردار و تصمیم را در ADR 0008 بنویس.
    - `sql_server.py` و `python-tds` را حذف کن.
  - **Prompt:** `Implement repositories/postgres.py behind the existing interface and run the same repository tests against memory and postgres. Then remove the SQL Server code and python-tds. Ask before deleting files.`
  - **Done when:** کارت بعد از ری‌استارت هنوز هست و هیچ اشاره‌ای به SQL Server در کد نمانده.
  - **Commit:** `feat(db): postgres repository replaces sql server`

## بخش: امنیت

- [ ] **S12 — Authentication: «تو کی هستی؟»**  (branch: `step/S12-<slug>`)
  - **Goal:** به‌جای باور کردن هدر قابل جعل `X-Actor-Id`، هویت از رمز و توکن بیاید. (OWASP A01 و A07)
  - **Tasks:**
    - رمز با الگوریتم امن هش شود (argon2 یا bcrypt)، هرگز متن ساده.
    - مسیر `POST /api/v1/auth/login` توکن (JWT) برمی‌گرداند. کلید امضا از `.env` می‌آید.
    - دو کاربر اولیه (human و agent) با رمزی که از `.env` می‌آید بساز، نه از داخل کد.
    - در `api/deps.py` خواندن هدر را با خواندن توکن عوض کن. کنسول وب هم یک فرم ورود ساده لازم دارد.
  - **Prompt:** `Implement login with password hashing and signed tokens. Replace X-Actor-Id trust in api/deps.py with token verification. Secrets must come from .env. Do not put any password in code.`
  - **Done when:** رمز اشتباه → 401؛ رمز درست → توکن؛ هدر `X-Actor-Id` دیگر هویت را تعیین نمی‌کند.
  - **Commit:** `feat(auth): add login and token authentication`

- [ ] **S13 — Authorization: «چه کاری مجازی؟»**  (branch: `step/S13-<slug>`)
  - **Goal:** هر نقش فقط کمترین دسترسی لازم را داشته باشد. بررسی در لایه service انجام شود، نه فقط پنهان کردن endpoint.
  - **Tasks:**
    - نقش‌ها: `human` و `agent`.
    - human: همه کارهای عادی + انتقال به Done + عملیات مدیریتی (بکاپ).
    - agent: ساخت کارت، کامنت، انتقال در مرحله‌های مجاز؛ **نه** Done و **نه** مدیریت.
    - قانون‌ها از قبل در `services/cards.py` هست؛ همان را به نقش واقعی توکن وصل کن.
  - **Prompt:** `Connect the token's role to the existing stage-machine guards in services/cards.py. Authorization must be enforced in the service layer. Agents must not move cards to Done or call admin operations.`
  - **Done when:** agent برای رفتن کارت به Done پاسخ ممنوع می‌گیرد، حتی اگر مستقیم به API درخواست بزند.
  - **Commit:** `feat(auth): enforce roles in service layer`

- [ ] **S14 — تست‌های امنیتی 401 و 403**  (branch: `step/S14-<slug>`)
  - **Goal:** ثابت کنی دسترسی‌ها واقعاً کار می‌کنند و بعدها خراب نمی‌شوند.
  - **Tasks:**
    - بدون توکن → 401.
    - توکن خراب یا منقضی → 401.
    - agent → انتقال به Done → 403.
    - agent → `POST /api/v1/backup` → 403.
    - human → همان کارها → موفق.
    - تست را روی همه endpointها parametrize کن تا یکی جا نیفتد.
  - **Prompt:** `Write parametrized security tests: 401 for missing/invalid token on every endpoint, 403 for agent on Done and admin routes, success for human.`
  - **Done when:** همه تست‌های 401/403 سبز است. (برای هر کدام یک تست نوشته‌ای.)
  - **Commit:** `test(security): add 401 and 403 tests`

- [ ] **S15 — ممیزی OWASP Top 10**  (branch: `step/S15-<slug>`)
  - **Goal:** ضعف‌های رایج را در کد خودت پیدا و ببندی. در دفاع یکی از ۱۰ مورد را تصادفی می‌پرسند.
  - **Tasks:**
    - چک‌لیست ده‌گانه (صفحه «OWASP») را در `docs/architecture.md`، `AGENTS.md` و `CLAUDE.md` بگذار.
    - یک subagent فقط‌خواندنی بساز که تغییرات را با چک‌لیست بسنجد (بخش تمرین OpenCode).
    - هر یافته یا همین‌جا اصلاح شود یا در یک جدول «پذیرفته‌شده/باز» ثبت شود.
  - **Prompt:** `Use the security-reviewer subagent to review the diff of this branch against the OWASP checklist. List findings with file:line. Fix the ones I approve.`
  - **Done when:** همه ده مورد یا اصلاح شده یا مکتوب شده‌اند، و می‌توانی هرکدام را توضیح بدهی.
  - **Commit:** `docs(security): add OWASP checklist  /  fix(security): <شرح هر اصلاح>`

## بخش: تحویل

- [ ] **S16 — تحویل نهایی**  (branch: `step/S16-<slug>`)
  - **Goal:** مطمئن شوی هر چیزی که باید تحویل بدهی کامل و قابل دفاع است.
  - **Tasks:**
    - همه شاخه‌های `step/*` با Pull Request و بازبینی merge شده باشند.
    - اجرای کامل: `pytest -q` سبز و `alembic upgrade head` روی دیتابیس تازه درست کار کند.
    - README را با دستور اجرای جدید (PostgreSQL، migration، لاگین) به‌روز کن.
    - دفاع ۲ دقیقه‌ای از ADR را تمرین کن: چه انتخاب کردی؟ چه چیزی را از دست دادی؟ چرا گزینه دیگر نه؟
    - هر خطی را که agent نوشته بتوانی توضیح بدهی.
    - برچسب بزن: `git tag week4-delivery`.
  - **Prompt:** `Run pytest -q, check alembic upgrade head on a fresh database, and list any file where a layer rule is bent. Do not change anything.`
  - **Done when:** همه موارد بالا انجام شده و برچسب تحویل روی main است.
  - **Commit:** `docs(readme): update run instructions`

## OWASP Top 10 (2025) checklist

- [ ] **A01 Broken Access Control** — کاربر یا agent کار غیرمجاز کند. In Gantry: Done فقط human؛ بررسی نقش در services؛ پیش‌فرض: ممنوع
- [ ] **A02 Security Misconfiguration** — تنظیم ناامن. In Gantry: CORS بسته، debug خاموش، `.env` در gitignore
- [ ] **A03 Software Supply Chain Failures** — کتابخانه آلوده. In Gantry: نسخه‌ها در requirements قفل؛ فقط پکیج‌های لازم
- [ ] **A04 Cryptographic Failures** — رمز یا کلید لو برود. In Gantry: رمز هش‌شده، کلید JWT فقط در `.env`
- [ ] **A05 Injection** — متن کاربر به‌عنوان کد اجرا شود. In Gantry: فقط کوئری پارامتری؛ بررسی `ai/safety.py` برای prompt injection
- [ ] **A06 Insecure Design** — ایراد در خود طراحی. In Gantry: agent که کارت را ساخته، خودش تأییدش نکند
- [ ] **A07 Authentication Failures** — ورود ضعیف. In Gantry: لاگین با هش، توکن با انقضا، محدودیت تلاش (`rate_limit`)
- [ ] **A08 Software or Data Integrity Failures** — داده یا کد دست‌کاری شود. In Gantry: migration فقط با Alembic؛ بکاپ را قبل از restore بررسی کن
- [ ] **A09 Security Logging and Alerting Failures** — اتفاق ثبت نشود. In Gantry: `audit_log` برای هر انتقال و ورود ناموفق
- [ ] **A10 Mishandling of Exceptional Conditions** — خطا اطلاعات لو بدهد. In Gantry: پاسخ خطا یکسان؛ `details` بدون مسیر فایل یا SQL

## Git protocol

## Git protocol (follow exactly)
- Work only on a branch named step/<ID>-<slug> (example: step/S4-architecture). Never commit to main.
- Do ONE roadmap step per session, then stop and wait for me.
- Before any commit run `pytest -q`. If anything is red, stop and report. (Exception: S7 marks the new architecture test as xfail.)
- Stage specific files only: `git add <path>`. Never `git add .` or `git add -A`.
- Never stage .env, backups/, .venv, *.bak, *.log.
- Before committing, show me: `git status`, `git diff --stat` and the proposed commit message. Wait for my OK.
- Commit message format: type(scope): short summary. Types: feat, fix, refactor, test, docs, chore.
- After the commit, tick the step in docs/ROADMAP.md.
- Never push, merge, rebase, `reset --hard` or force-push unless I explicitly say so.
- Never edit a test just to make it pass.
