// ui/src/components/AgentHoverCard.tsx
// Portal-based hover card - escapes overflow:hidden containers
import { useState, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import {
  AGENT_HUMAN_NAME, AGENT_AVATAR, AGENT_AVATAR_IMAGE,
  AGENT_BACKSTORY, AGENT_SKILLS,
} from './agentStatus'

interface Props {
  agentName: string   // display name key, e.g. 'Value Chain Mapper'
  children: React.ReactNode
}

export default function AgentHoverCard({ agentName, children }: Props) {
  const [visible, setVisible] = useState(false)
  const [pos, setPos] = useState({ x: 0, y: 0, below: false })
  const ref = useRef<HTMLDivElement>(null)
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const humanName = AGENT_HUMAN_NAME[agentName] ?? agentName
  const firstName  = humanName.split(' ')[0]
  const avatar     = AGENT_AVATAR[agentName] ?? { gradient: 'from-gray-400 to-gray-600' }
  const imageSrc   = AGENT_AVATAR_IMAGE[agentName]
  const backstory  = AGENT_BACKSTORY[agentName] ?? ''
  const skills     = AGENT_SKILLS[agentName] ?? []

  const show = useCallback(() => {
    if (hideTimer.current) clearTimeout(hideTimer.current)
    if (ref.current) {
      const rect = ref.current.getBoundingClientRect()
      // Flip below when there isn't enough space above (popup is ~300px tall)
      const below = rect.top < 320
      setPos({
        x: rect.left + rect.width / 2,
        y: below ? rect.bottom : rect.top,
        below,
      })
    }
    setVisible(true)
  }, [])

  const hide = useCallback(() => {
    hideTimer.current = setTimeout(() => setVisible(false), 120)
  }, [])

  const keepOpen = useCallback(() => {
    if (hideTimer.current) clearTimeout(hideTimer.current)
  }, [])

  return (
    <>
      <div ref={ref} onMouseEnter={show} onMouseLeave={hide}>
        {children}
      </div>

      {visible && createPortal(
        <div
          onMouseEnter={keepOpen}
          onMouseLeave={hide}
          style={{
            position: 'fixed',
            left: pos.x,
            top: pos.below ? pos.y + 8 : pos.y - 12,
            transform: pos.below ? 'translate(-50%, 0)' : 'translate(-50%, -100%)',
            zIndex: 9999,
          }}
          className="w-72 bg-white rounded-2xl shadow-2xl border border-gray-100 overflow-hidden pointer-events-auto"
        >
          {/* Gradient header with photo */}
          <div className={`bg-gradient-to-br ${avatar.gradient} px-4 pt-4 pb-5 flex items-end gap-3`}>
            {imageSrc ? (
              <img
                src={imageSrc}
                alt={firstName}
                className="w-16 h-16 rounded-full object-cover border-2 border-white/60 shadow-md flex-shrink-0"
              />
            ) : (
              <div className="w-16 h-16 rounded-full bg-white/20 flex items-center justify-center text-xl font-bold text-white border-2 border-white/60 flex-shrink-0">
                {humanName.split(' ').map((w: string) => w[0]).join('').slice(0, 2)}
              </div>
            )}
            <div className="pb-0.5 min-w-0">
              <p className="text-white font-bold text-lg leading-tight">{firstName}</p>
              <p className="text-white/70 text-[11px] leading-snug truncate">{agentName}</p>
            </div>
          </div>

          {/* Body */}
          <div className="px-4 py-3 space-y-3">
            {backstory && (
              <p className="text-xs text-gray-600 leading-relaxed">{backstory}</p>
            )}

            {skills.length > 0 && (
              <div className="space-y-1">
                <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest">Top skills</p>
                <div className="flex flex-wrap gap-1">
                  {skills.slice(0, 4).map(s => (
                    <span
                      key={s.name}
                      className="inline-flex items-center gap-1 text-[10px] bg-gray-100 text-gray-600 rounded-full px-2 py-0.5"
                    >
                      <s.icon size={10} className="text-gray-500" />
                      {s.name}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}
