import { useCallback, useState } from 'react'
import { uploadFile } from './api'
import type { UploadResult } from './types'

export type UploadState =
  | { phase: 'idle' }
  | { phase: 'uploading'; name: string }
  | { phase: 'sheet'; file: File; result: UploadResult }
  | { phase: 'done'; result: UploadResult }
  | { phase: 'error'; message: string }

export const ACCEPT = '.csv,.tsv,.xlsx'

/** Upload a file as a private table. `onUploaded` selects the new dataset; an Excel file with several sheets asks which one. */
export function useUpload(conversationId: string, onUploaded: (dataset?: string) => void) {
  const [state, setState] = useState<UploadState>({ phase: 'idle' })
  const send = useCallback(async (file: File, sheet?: string) => {
    setState({ phase: 'uploading', name: file.name })
    try {
      const result = await uploadFile(file, conversationId, sheet)
      if (result.status === 'NEEDS_SHEET') {
        setState({ phase: 'sheet', file, result })
        return
      }
      setState({ phase: 'done', result })
      onUploaded(result.dataset ?? undefined)
    } catch (err) {
      setState({ phase: 'error', message: (err as Error).message })
    }
  }, [conversationId, onUploaded])
  const reset = useCallback(() => setState({ phase: 'idle' }), [])
  return { state, send, reset }
}
