// ui/src/pages/PamReport.tsx
import { useParams } from 'react-router-dom'
import PamReportView from '../components/PamReportView'

export default function PamReport() {
  const { slug } = useParams<{ slug: string }>()
  if (!slug) return null
  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      <PamReportView slug={slug} />
    </div>
  )
}
