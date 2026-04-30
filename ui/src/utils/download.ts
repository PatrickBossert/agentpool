// ui/src/utils/download.ts
import { API_BASE } from '../api/client'

export async function downloadOutput(
  slug: string,
  outputId: number,
  filename: string,
  token: string,
): Promise<void> {
  const resp = await fetch(
    `${API_BASE}/projects/${slug}/outputs/${outputId}/download`,
    { headers: { Authorization: `Bearer ${token}` } },
  )
  if (!resp.ok) throw new Error(`Download failed: ${resp.status}`)
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
