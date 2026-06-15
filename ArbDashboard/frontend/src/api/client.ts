/**
 * Axios 实例与 HTTP 客户端基础配置
 * - 统一 baseURL、超时、请求/响应拦截器
 * - 错误处理与日志
 */
import axios from 'axios'
import type { AxiosInstance, AxiosResponse, InternalAxiosRequestConfig } from 'axios'

const BASE_URL = import.meta.env.VITE_API_BASE || ''

const client: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' }
})

// 请求拦截器
client.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => config,
  (error) => Promise.reject(error)
)

// 响应拦截器：统一解包 data，自动处理业务错误
client.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error) => {
    const msg = error?.response?.data?.message || error.message || '网络请求失败'
    console.error(`[API Error] ${msg}`, error)
    return Promise.reject(error)
  }
)

export default client
