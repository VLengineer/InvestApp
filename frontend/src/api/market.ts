/**
 * REST-клиер к backend-frontend (BFF). Все вызовы — относительные пути /api/*,
 * которые Vite проксирует на контейнер backend-frontend (см. vite.config.ts) —
 * тот же подход, что уже используется для n8n (/n8n-api/): браузеру не нужно
 * резолвить docker-имена.
 */

import type {
  AllNewsListResponse,
  CompanyFigiItem,
  CompanyFigiListResponse,
  FigiListResponse,
  InitialDataResponse,
  NewsResponse,
} from '../types/market'

const API_BASE = '/api/market'

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    let detail = ''
    try {
      const body = await res.json()
      detail = typeof body?.detail === 'string' ? body.detail : JSON.stringify(body?.detail ?? body)
    } catch {
      detail = await res.text().catch(() => '')
    }
    throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail}` : ''}`)
  }
  return (await res.json()) as T
}

/** Список уникальных FIGI, по которым есть данные в БД. */
export async function fetchFigis(): Promise<string[]> {
  const data = await getJson<FigiListResponse>(`${API_BASE}/figis`)
  return data.figis
}

/** FIGI + названия компаний из company_profiles. */
export async function fetchCompanies(): Promise<CompanyFigiItem[]> {
  const data = await getJson<CompanyFigiListResponse>(`${API_BASE}/companies`)
  return data.companies
}

/** Последние 500 записей для конкретного FIGI (история для графиков). */
export async function fetchInitialData(figi: string): Promise<InitialDataResponse> {
  return getJson<InitialDataResponse>(`${API_BASE}/initial-data?figi=${encodeURIComponent(figi)}`)
}

/** Полная информация о новости по ID (для модалки). */
export async function fetchNewsById(id: string): Promise<NewsResponse> {
  return getJson<NewsResponse>(`${API_BASE}/news/${encodeURIComponent(id)}`)
}

/** Все новости с пагинацией (для страницы аналитики). */
export async function fetchAllNews(limit: number, offset: number): Promise<AllNewsListResponse> {
  return getJson<AllNewsListResponse>(`${API_BASE}/all-news?limit=${limit}&offset=${offset}`)
}
