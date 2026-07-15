// ui/src/components/tabs/LucaOutputExtra.tsx
// Luca's Output tab extra: vision picture and other visual artefacts
import { useState } from 'react'
import { ZoomIn, X } from 'lucide-react'

export default function LucaOutputExtra({ slug }: { slug: string }) {
  const [lightbox, setLightbox] = useState(false)
  const visionUrl = `/api/projects/${slug}/output-files/vision_picture_v11.png`

  return (
    <div className="space-y-3">
      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Visual Artefacts</p>

      {/* Vision picture */}
      <div className="rounded-lg border border-gray-100 overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 bg-gray-50 border-b border-gray-100">
          <div>
            <p className="text-xs font-medium text-gray-700">Vision Picture — v11</p>
            <p className="text-[10px] text-gray-400">Current state · future state · transformation narrative</p>
          </div>
          <button
            onClick={() => setLightbox(true)}
            className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-brand"
          >
            <ZoomIn size={12} /> Expand
          </button>
        </div>
        <div className="bg-white p-3 cursor-zoom-in" onClick={() => setLightbox(true)}>
          <img
            src={visionUrl}
            alt="Vision picture v11"
            className="w-full rounded border border-gray-100 object-contain max-h-40"
            onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
          />
        </div>
      </div>

      {/* Lightbox */}
      {lightbox && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
          onClick={() => setLightbox(false)}
        >
          <div className="relative max-w-5xl w-full" onClick={e => e.stopPropagation()}>
            <button
              onClick={() => setLightbox(false)}
              className="absolute -top-8 right-0 text-white/70 hover:text-white flex items-center gap-1 text-sm"
            >
              <X size={16} /> Close
            </button>
            <img
              src={visionUrl}
              alt="Vision picture v11 — full size"
              className="w-full rounded-lg shadow-2xl"
            />
          </div>
        </div>
      )}
    </div>
  )
}
