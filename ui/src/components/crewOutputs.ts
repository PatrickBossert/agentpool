// ui/src/components/crewOutputs.ts
// Which output type represents each crew's work. One fact, one home: the Dashboard's inline
// preview and the agent panel's Output tab both need it, and two copies would drift the
// first time a crew's output type changed.
//
// PAM is deliberately absent - its Output tab is an Overview rendering PamReportView, not a
// versioned artefact, so it has no primary to declare and keeps its own branch.
//
// Every value below is a type one of that crew's own agents actually writes - either as a
// SQLiteStateTool key in its task description, or hard-coded by a tool the registry gives it.
// tests/test_crew_output_types.py derives that set from the agent modules and fails on a
// value nothing produces, because a fictional entry here leaves the Output tab permanently
// empty and reports nothing anywhere.
//
// Where a crew produces several artefacts, the one named is its deliverable rather than a
// step towards it: the crews are sequential, so an artefact a later agent in the same crew
// reads back is an intermediate however useful it is downstream.
export const CREW_OUTPUT_TYPE: Record<string, string> = {
  discovery_mapping:      'value_chain_model',
  assessment_design:      'interview_scripts',
  // portfolio_manager reads 'propositions' back to score them, so the scored register is the
  // crew's result and the propositions are the input to it.
  value_design:           'portfolio_register',
  // Same shape: initiative_identifier reads 'architecture_register' and decomposes it into
  // the initiatives that delivery and business_plan both consume.
  architecture:           'initiative_register',
  // HtmlRoadmapTool writes 'html' too, but that is a rendering of this same JSON.
  delivery:               'roadmap_data',
  // WordOutputTool's business_plan.docx. The deck and the financial model accompany it.
  business_plan:          'docx',
  // requirements_analyst's output is explicitly "the foundation for value lever
  // identification", and value_lever_analyst reads it back - the levers are the crew's result.
  discovery:              'value_levers',
  stakeholder_management: 'stakeholder_engagement_plan',
  // synthesis_analyst's synthesis of the transcripts stakeholder_interviewer gathered.
  discovery_interviews:   'activity_insights',
}

// SQLite timestamps use a space separator; convert to ISO 'T' so Date parses correctly in
// every browser. Shared because both the Output tab's primary lookup and the Status tab's
// version list sort or display an output's created_at.
export function parseDbDate(ts: string | undefined | null): Date {
  if (!ts) return new Date(0)
  return new Date(ts.replace(' ', 'T') + 'Z')
}
