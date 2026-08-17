// ui/src/components/outputTypeLabels.ts
// What an output_type is called on screen. One fact, one home.
//
// This was declared three times - in RerunDialog, AgentStatusTab and Documents - and the three
// had already diverged by scope rather than by wording: the rerun dialog was the only one that
// knew `strategic_requirements`, `captured_requirements`, `requirements_analysis` and
// `architecture_register`, and the other two were the only ones that knew `value_chain_model`,
// `docx`, `roadmap_data` and `initiative_register`. So the same artefact read "As-Is
// Capabilities" in one dialog and "Architecture Register" in another, because the second fell
// through to the title-cased fallback.
//
// The fallback is deliberate and stays. An output type with no entry here is a new artefact
// rather than an error, and "Roadmap Data" is a perfectly good reading of `roadmap_data`; the
// map exists for the ones title casing gets wrong - `docx` would read "Docx".
// Every output type an agent owns appears here, which is what
// tests/test_output_type_labels.py asserts. The three value_chain_* entries below are
// internal - Documents.tsx and the PAM report both filter them out - and are labelled only so
// that "every owned type is named" is a complete statement rather than one with a list of
// exceptions beside it.
export const OUTPUT_TYPE_LABELS: Record<string, string> = {
  value_chain:                      'Value Chain',
  value_chain_model:                'Value Chain Model',
  value_chain_registry:             'Value Chain Registry',
  value_chain_summary:              'Value Chain Summary',
  value_chain_tree:                 'Value Chain Tree',
  // WordOutputTool records its output as 'docx'; the fallback label would read "Docx".
  docx:                             'Business Plan Document',
  interview_scripts:                'Interview Scripts',
  l0_interview_summaries:           'L0 Board Summaries',
  l1_interview_summaries:           'L1 GM Summaries',
  l2_interview_summaries:           'L2 Process Manager Summaries',
  audit_interview_summaries:        'Audit Summaries',
  customer_interview_summaries:     'Customer Summaries',
  frontline_interview_summaries:    'Frontline Summaries',
  corp_services_interview_summaries:'Corporate Services Summaries',
  requirements:                     'Requirements',
  strategic_requirements:           'Strategic Requirements',
  captured_requirements:            'Captured Requirements',
  requirements_analysis:            'Requirements Analysis',
  value_levers:                     'Value Levers',
  themes:                           'Themes',
  interview_plan:                   'Interview Plan',
  illustration_briefs:              'Illustration Briefs',
  // `propositions` is the key Quinn actually owns and writes. `value_propositions` is the
  // older name, kept so historical rows still label rather than falling through.
  propositions:                     'Value Propositions',
  value_propositions:               'Value Propositions',
  portfolio_register:               'Portfolio Register',
  architecture_register:            'As-Is Capabilities',
  // Nothing writes architecture_blueprint any more; kept so historical rows still label.
  architecture_blueprint:           'Architecture Blueprint',
  roadmap:                          'Roadmap',
  roadmap_data:                     'Roadmap Data',
  business_plan:                    'Business Plan',
  stakeholder_engagement_plan:      'Stakeholder Engagement Plan',
  interview_transcripts:            'Interview Transcripts',
  activity_insights:                'Activity Insights',
  initiative_register:              'Initiative Register',
}

export function outputLabel(outputType: string): string {
  return (
    OUTPUT_TYPE_LABELS[outputType] ??
    outputType.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  )
}
