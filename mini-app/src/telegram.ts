interface TelegramWebApp { initData:string; colorScheme:'light'|'dark'; ready():void; expand():void }
declare global { interface Window { Telegram?: { WebApp: TelegramWebApp } } }
export function initializeTelegram(): string {
  const webApp = window.Telegram?.WebApp
  if (!webApp?.initData && import.meta.env.DEV) {
    return new URLSearchParams(window.location.search).get('dev_init_data') ?? import.meta.env.VITE_DEV_INIT_DATA ?? ''
  }
  if (!webApp) return ''
  webApp.ready(); webApp.expand(); document.documentElement.dataset.theme = webApp.colorScheme
  return webApp.initData
}
