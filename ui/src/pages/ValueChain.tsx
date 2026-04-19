// ui/src/pages/ValueChain.tsx
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import mermaid from 'mermaid'
import { projectsApi } from '../api/endpoints'

mermaid.initialize({ startOnLoad: false, theme: 'dark' })

export default function ValueChain() {
  const { slug } = useParams<{ slug: string }>()

  const { data: outputs = [], isLoading } = useQuery({
    queryKey: ['value-chain', slug],
    queryFn: () => projectsApi.valueChain(slug!),
    enabled: !!slug,
  })

  // Pick the latest output record (API returns DESC order)
  const latest = outputs[0] ?? null

  const { data: contentData, isLoading: contentLoading, isError: contentError } = useQuery({
    queryKey: ['outputContent', slug, latest?.id],
    queryFn: () => projectsApi.getOutputContent(slug!, latest!.id),
    enabled: !!slug && !!latest,
  })

  const svgContainerRef = useRef<HTMLDivElement>(null)
  const mountKey = useRef(Math.random().toString(36).slice(2))
  const [renderError, setRenderError] = useState(false)

  useEffect(() => {
    if (!contentData?.content || !svgContainerRef.current) return
    let cancelled = false
    const container = svgContainerRef.current
    setRenderError(false)
    ;(async () => {
      try {
        const renderId = 'vc-' + mountKey.current + '-' + (latest?.id ?? 0)
        const { svg } = await mermaid.render(renderId, contentData.content)
        if (cancelled) return
        // Use DOMParser to safely parse the SVG string into a DOM node
        // (avoids innerHTML; mermaid's output is trusted — generated from
        // our own stored Mermaid source, not user-supplied HTML)
        const parser = new DOMParser()
        const svgDoc = parser.parseFromString(svg, 'image/svg+xml')
        const svgEl = svgDoc.documentElement
        container.replaceChildren(svgEl)
      } catch {
        if (!cancelled) setRenderError(true)
        if (!cancelled) container.replaceChildren()
      }
    })()
    return () => {
      cancelled = true
    }
  }, [contentData?.content, latest?.id])

  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold text-slate-100 mb-4">Value Chain</h2>

      {isLoading && <p className="text-sm text-slate-500">Loading…</p>}

      {!isLoading && outputs.length === 0 && (
        <div className="bg-surface-card rounded-xl p-8 text-center">
          <p className="text-slate-400 text-sm">Awaiting Value Chain Mapper output.</p>
          <p className="text-slate-600 text-xs mt-2">
            Run the Discovery crew to generate the value chain analysis.
          </p>
        </div>
      )}

      {latest && (
        <div className="bg-surface-card rounded-xl p-4">
          {/* Output metadata row */}
          <div className="flex justify-between items-center mb-4">
            <span className="text-sm text-slate-200">{latest.agent_name}</span>
            <span className="text-xs text-slate-500">
              v{latest.version} · {latest.review_status}
            </span>
          </div>

          {/* Diagram area */}
          {contentLoading && (
            <p className="text-sm text-slate-500">Rendering diagram…</p>
          )}
          {contentError && !contentLoading && (
            <p className="text-sm text-red-400">Failed to load diagram.</p>
          )}
          {renderError && (
            <p className="text-sm text-red-400">Invalid diagram source.</p>
          )}
          {/* SVG inserted here via DOMParser + replaceChildren */}
          <div ref={svgContainerRef} className="overflow-auto" />
        </div>
      )}
    </div>
  )
}
