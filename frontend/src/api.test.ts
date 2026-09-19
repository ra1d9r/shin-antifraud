/**
 * Тесты клиента API — про фолбеки, а не про счастливый путь.
 *
 * Каждый случай здесь однажды выглядел в интерфейсе плохо: зависший
 * запрос без таймаута, сырое исключение разбора JSON, заголовок
 * «HTTP 500 — HTTP 500». Тесты закрепляют, что так больше не будет.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, fetchHealth } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

/** Ответ, который никогда не придёт, но честно реагирует на отмену. */
function hangingFetch() {
  return (_url: string, init?: RequestInit) =>
    new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () =>
        reject(new DOMException('Aborted', 'AbortError')),
      )
    })
}

describe('ошибки транспорта', () => {
  it('недоступный backend называет адрес, а не TypeError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(fetchHealth()).rejects.toMatchObject({
      status: 0,
      message: expect.stringContaining('Поднят ли он?'),
    })
  })

  it('зависший запрос обрывается по таймауту, а не висит вечно', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', hangingFetch())

    const pending = fetchHealth()
    const assertion = expect(pending).rejects.toMatchObject({
      status: 0,
      message: expect.stringContaining('не ответил за'),
    })

    await vi.advanceTimersByTimeAsync(15_000)
    await assertion
  })
})

describe('ошибки ответа', () => {
  it('ответ без тела не даёт «HTTP 500 — HTTP 500»', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 500 })))

    await expect(fetchHealth()).rejects.toMatchObject({
      status: 500,
      message: 'Backend ответил ошибкой',
    })
  })

  it('404 объясняется словами', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 404 })))

    await expect(fetchHealth()).rejects.toMatchObject({ message: 'Адрес не найден на backend' })
  })

  it('сообщение backend важнее нашего описания', async () => {
    const body = JSON.stringify({ error_code: 'model_not_loaded', message: 'Модель не загружена' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status: 503 })))

    await expect(fetchHealth()).rejects.toMatchObject({
      status: 503,
      message: 'Модель не загружена',
    })
  })

  it('успешный ответ не в JSON не показывает сырое исключение', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('<html>502</html>', { status: 200 })),
    )

    const failure = await fetchHealth().catch((cause: unknown) => cause)

    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).message).toContain('не в формате JSON')
    expect((failure as ApiError).message).not.toContain('SyntaxError')
  })
})

describe('разбор ошибок валидации', () => {
  it('поля из ответа собираются в читаемый список', async () => {
    const body = JSON.stringify({
      error_code: 'validation_error',
      message: 'Некорректные данные запроса',
      details: { errors: [{ field: 'amount', message: 'Input should be greater than 0' }] },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status: 422 })))

    const failure = (await fetchHealth().catch((cause: unknown) => cause)) as ApiError

    expect(failure.fieldErrors).toEqual(['amount: Input should be greater than 0'])
  })
})
