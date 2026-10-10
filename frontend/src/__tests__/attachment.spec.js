import { describe, it, expect } from 'vitest'
import { fileToBase64 } from '../utils/attachment'

/** U3: the composer turns a picked File into the base64 the upload endpoint wants. */

describe('fileToBase64', () => {
  it('encodes file bytes without the data-url prefix', async () => {
    const file = new window.File(['abc'], 'x.txt', { type: 'text/plain' })
    expect(await fileToBase64(file)).toBe('YWJj')
  })

  it('round-trips Chinese content', async () => {
    const file = new window.File(['你好'], '中文.txt', { type: 'text/plain' })
    const b64 = await fileToBase64(file)
    expect(new TextDecoder().decode(Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)))).toBe('你好')
  })
})
