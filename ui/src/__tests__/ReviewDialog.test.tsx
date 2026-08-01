// ui/src/__tests__/ReviewDialog.test.tsx
//
// Alex's crew (discovery_mapping) used to point its inline preview and its Status tab
// diagram list at 'value_chain', the retired Mermaid output. A structured model has no
// diagram to draw - the summary card is the honest equivalent, so the map is repointed and
// the model type is kept out of the diagram set.
import { describe, it, expect } from 'vitest'
import { CREW_OUTPUT_TYPE } from '../components/ReviewDialog'
import { MERMAID_OUTPUT_TYPES } from '../components/AgentStatusTab'

describe('the value chain preview', () => {
  it('previews the model, not the retired diagram', () => {
    expect(CREW_OUTPUT_TYPE.discovery_mapping).toBe('value_chain_model')
  })

  it('does not try to draw the model as a diagram', () => {
    // Alex no longer holds MermaidRenderTool, so a fresh run produces no value_chain
    // output at all - and a JSON model has no fence to render.
    expect(MERMAID_OUTPUT_TYPES.has('value_chain_model')).toBe(false)
  })

  it('still draws the output types that really are diagrams', () => {
    // The positive anchor: without it, deleting the whole set would pass the test above.
    expect(MERMAID_OUTPUT_TYPES.has('architecture')).toBe(true)
    expect(MERMAID_OUTPUT_TYPES.has('roadmap')).toBe(true)
  })
})
