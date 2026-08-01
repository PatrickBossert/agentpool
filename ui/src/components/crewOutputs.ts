// ui/src/components/crewOutputs.ts
// Which output type represents each crew's work. One fact, one home: the Dashboard's inline
// preview and the agent panel's Output tab both need it, and two copies would drift the
// first time a crew's output type changed.
//
// PAM is deliberately absent - its Output tab is an Overview rendering PamReportView, not a
// versioned artefact, so it has no primary to declare and keeps its own branch.
export const CREW_OUTPUT_TYPE: Record<string, string> = {
  discovery_mapping:      'value_chain',
  assessment_design:      'interview_scripts',
  value_design:           'value_propositions',
  architecture:           'architecture',
  delivery:               'roadmap',
  business_plan:          'business_plan',
  discovery:              'discovery',
  stakeholder_management: 'stakeholder_engagement_plan',
  discovery_interviews:   'interview_synthesis',
}

// SQLite timestamps use a space separator; convert to ISO 'T' so Date parses correctly in
// every browser. Shared because both the Output tab's primary lookup and the Status tab's
// version list sort or display an output's created_at.
export function parseDbDate(ts: string | undefined | null): Date {
  if (!ts) return new Date(0)
  return new Date(ts.replace(' ', 'T') + 'Z')
}
