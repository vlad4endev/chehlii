/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
  readonly VITE_TG_URL?: string
  readonly VITE_MAX_URL?: string
  readonly VITE_MAX_BOT_USERNAME?: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
