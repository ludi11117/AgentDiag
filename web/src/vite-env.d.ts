/// <reference types="vite/client" />

/**
 * 环境变量类型声明。
 *
 * 显式声明而不是让 import.meta.env 保持 any：
 * 少了这层，VITE_API_KEY 拼错成 VITE_APIKEY 时编译器不会报错，
 * 只会在运行时静默不带鉴权头——这类问题在本地（后端不校验）完全暴露不出来。
 */
interface ImportMetaEnv {
  /** 可选 API Key。后端 API_KEY 留空时无需设置。 */
  readonly VITE_API_KEY?: string
  /** 开发期代理目标，默认 http://127.0.0.1:8000 */
  readonly VITE_API_PROXY_TARGET?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
