/**
 * Persian/Farsi (RTL).
 *
 * Every key from `en.ts` must be present with a non-empty Persian value and the
 * same `{{placeholder}}` names. `npm run i18n:check` fails otherwise.
 *
 * Note: Persian uses its own digits and the letters پ چ ژ گ, which are not
 * used in Arabic — the RTL screenshots exercise both.
 */
import type { TranslationKey } from './en.ts';

const fa: Record<TranslationKey, string> = {
  'app.name': 'نکسوس — سیستم عامل عامل‌ها',
  'app.tagline': 'تیم عامل‌های هوش مصنوعی شما، تحت کنترل خودتان',
  'app.skipToContent': 'پرش به محتوای اصلی',
  'app.theme.dark': 'پوستهٔ تیره',
  'app.theme.light': 'پوستهٔ روشن',
  'app.language.label': 'زبان',
  'app.language.current': 'زبان کنونی: {{language}}',
  'app.status.online': 'متصل',
  'app.status.degraded': 'کاهش کیفیت',
  'app.status.offline': 'قطع',
  'app.owner': 'مالک',
  'app.organization': 'سازمان محلی',

  'nav.label': 'ناوبری اصلی',
  'nav.dashboard': 'داشبورد',
  'nav.connections': 'مدیر اتصال‌ها',
  'nav.agents': 'عامل‌ها',
  'nav.runs': 'اجراها',
  'nav.settings': 'تنظیمات',

  'page.dashboard.title': 'داشبورد',
  'page.dashboard.description': 'وضعیت زندهٔ تیم، اتصال‌ها و اجراهای شما.',
  'page.dashboard.empty': 'هنوز عاملی وجود ندارد. برای شروع یک عامل بسازید.',
  'page.dashboard.startedAt': 'تاریخ ایجاد تیم',
  'page.dashboard.uptime': 'مدت اجرا',
  'page.dashboard.stats': 'تیم در یک نگاه',
  'page.dashboard.facts': 'سازمان و اجرا',
  'page.agents.count': 'عامل پیکربندی‌شده',
  'page.runs.count': 'اجرای ثبت‌شده',
  'page.connections.count': 'اتصال پیکربندی‌شده',
  'page.settings.theme': 'پوسته',
  'page.agents.title': 'عامل‌ها',
  'page.agents.description': 'هر عامل یک نقش، یک هدف، یک محیط اجرا و یک اتصال دارد.',
  'page.agents.empty': 'هیچ عاملی پیکربندی نشده است.',
  'page.runs.title': 'اجراها',
  'page.runs.description': 'هر اجرا، رویدادها و هزینهٔ آن.',
  'page.runs.empty': 'هیچ اجرایی ثبت نشده است.',
  'page.settings.title': 'تنظیمات',
  'page.settings.description': 'زبان، پوسته، سازمان و اعتبارنامه‌ها.',
  'page.settings.language': 'زبان رابط کاربری',
  'page.settings.languageHint': 'جهت متن رابط کاربری بی‌درنگ تغییر می‌کند.',

  'connection.title': 'مدیر اتصال‌ها',
  'connection.subtitle': 'همهٔ دسترسی به هوش مصنوعی از یک رابط اتصال واحد عبور می‌کند.',
  'connection.browser.title': 'از طریق مرورگر خود وصل شوید',
  'connection.browser.step1': 'مدیر اسکریپت کاربر را نصب کنید.',
  'connection.browser.step2': 'اسکریپت نکسوس را نصب کنید.',
  'connection.browser.step3': 'پل محلی را اجرا کنید.',
  'connection.browser.step4': 'کد جفت‌سازی را وارد کنید.',
  'connection.browser.step5': 'آزمون انتخابگرها را اجرا کنید.',
  'connection.wizard.progress': 'گام {{current}} از {{total}}',
  'connection.wizard.title': 'راه‌اندازی اتصال مرورگر',
  'connection.wizard.inProgress': 'در حال انجام',
  'connection.wizard.pending': 'هنوز آغاز نشده',
  'connection.local.title': 'مدل‌های محلی',
  'connection.local.description': 'Ollama یا هر نقطهٔ پایانی سازگار با OpenAI روی این دستگاه.',
  'connection.api.title': 'APIهای رسمی',
  'connection.api.description': 'به‌طور پیش‌فرض خاموش است. کلیدها رمزنگاری‌شده ذخیره می‌شوند.',
  'connection.state.ready': 'آماده',
  'connection.state.queued': 'در صف، جایگاه {{position}}',
  'connection.state.waitingForUser': 'این عامل به شما نیاز دارد',
  'connection.health.healthy': 'سالم',
  'connection.health.unverified': 'تأیید‌نشده',
  'connection.empty': 'هنوز هیچ اتصالی پیکربندی نشده است. با اتصال مرورگر شروع کنید.',

  'action.save': 'ذخیره',
  'action.cancel': 'انصراف',
  'action.retry': 'تلاش دوباره',
  'action.continue': 'ادامه',
  'action.test': 'آزمون',
  'action.disconnect': 'قطع اتصال',
  'action.revoke': 'ابطال',
  'action.close': 'بستن',
  'action.install': 'نصب',

  'a11y.skipLink': 'پرش به محتوای اصلی',
  'a11y.primaryNav': 'ناوبری اصلی',
  'a11y.languageSwitcher': 'زبان رابط را انتخاب کنید',
  'a11y.mainContent': 'محتوای اصلی',
  'a11y.openMenu': 'باز کردن منو',
  'a11y.closeDialog': 'بستن کادر گفتگو',
  'a11y.loading': 'در حال بارگذاری',
  'a11y.requiredField': 'فیلد الزامی',
  'a11y.errorSummary': '{{count}} مشکل در این فرم وجود دارد.',

  'format.number': 'عدد',
  'format.date': 'تاریخ',
  'format.currency': 'مبلغ: {{value}}',
  'format.codeIsLtr': 'کد همیشه از چپ به راست نمایش داده می‌شود',

  'error.generic': 'خطایی رخ داد. دوباره تلاش کنید.',
  'error.network': 'سرور پشتیبان در دسترس نیست.',
  'error.notFound': 'صفحه یافت نشد.',
  'error.timeout': 'درخواست پس از {{seconds}} ثانیه منقضی شد.',
};

export default fa;
