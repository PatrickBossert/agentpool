// ui/src/components/AgentAvatar.tsx
//
// An agent's face, or their initials when there is none.
//
// **The fallback belongs to the component, not to any one agent.** Every agent is in the
// "declared but not yet drawn" state between being added to `agents/identity.py` and having a
// portrait, and `image` there is nullable precisely so that state is legal - so a site that
// draws a face needs an answer for it that is not a broken image and is emphatically not some
// other agent's photograph. Laura Nelson was that agent for one day in September; she has a
// portrait now, and the state she was in has not gone anywhere.
//
// **Falsy, not `!= null`.** `''` is a portrait a project has *deliberately cleared* -
// `useAgentIdentity` keeps it falsy for exactly this reason - so it must reach the initials
// rather than an `<img src="">`, which resolves against the current document and fetches the
// page itself.
//
// **The image carries the name as its `alt`, and the fallback carries no `role="img"`.** That
// asymmetry is asserted: a fallback wearing an image role would let "renders initials rather
// than a broken image" pass against a component that still rendered an image.
//
// **Six older sites still carry their own copy of the initials rule** - `CrewCarousel` (twice),
// `AgentDetailPanel`, `AgentHoverCard`, `CrewAgentsTab` and `Team` - each with a per-agent
// gradient behind it. They are not converted here because that is a change to six renders on
// pages this task does not touch, and it is recorded rather than left to be rediscovered: this
// is where they should come, and `agentInitials` is exported so they can.

/**
 * Up to two initials from a display name.
 *
 * The rule the six sites above spell inline - first letter of each word, capped at two - stated
 * once so an agent's initials are the same two letters wherever they are drawn. It differs from
 * theirs in two harmless ways that are deliberate rather than accidental: it splits on any run
 * of whitespace, and it upper-cases, so a display name typed with a double space or in lower
 * case still yields the initials a person would write.
 */
export function agentInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => word[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

export default function AgentAvatar({
  name,
  imageUrl,
  className = '',
  fallbackClassName = 'bg-brand/15 text-teal-700 text-xs font-semibold',
}: {
  /** The display name this project shows for the agent - the `alt`, and the initials. */
  name: string
  /** The portrait, or `null`/`''` when there is none to draw. */
  imageUrl: string | null | undefined
  /** Size, ring and shadow for the circle. The caller owns these; the shape is fixed here. */
  className?: string
  /** Background and type for the initials, so a dark surface is not given a light disc. */
  fallbackClassName?: string
}) {
  return (
    <span
      data-testid="agent-avatar"
      className={`inline-flex items-center justify-center rounded-full overflow-hidden ${className}`}
    >
      {imageUrl ? (
        <img src={imageUrl} alt={name} className="w-full h-full object-cover" />
      ) : (
        <span
          data-testid="agent-initials"
          className={`w-full h-full flex items-center justify-center ${fallbackClassName}`}
        >
          {agentInitials(name)}
        </span>
      )}
    </span>
  )
}
