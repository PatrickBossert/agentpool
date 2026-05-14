// ui/src/__tests__/Report.test.tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../context/AuthContext'
import Report from '../pages/Report'

vi.mock('../api/endpoints', () => ({
  projectsApi: {
    getSettings: vi.fn().mockResolvedValue({
      sector: 'Transport',
      llm_mode: 'standard',
      stakeholder_groups: [],
      value_stream_labels: [],
      roadmap_time_axis: 'quarters',
      crews_enabled: [],
      review_gates: false,
      slack_channel: '',
      discovery_brief: '',
      discovery_links: [],
      discovery_document_ids: [],
      interview_method: 'none',
    }),
    financialSummary: vi.fn().mockResolvedValue({
      npv: 1200000,
      irr: 0.18,
      payback_period: '18 months',
      max_borrowing: 500000,
      total_investment: 800000,
      total_benefits: 2000000,
    }),
    portfolioRegister: vi.fn().mockResolvedValue([
      {
        rank: 1,
        id: 'vp1',
        title: 'Improve customer onboarding',
        change_articulation: 'Reduce friction in signup',
        impacted_stakeholder_groups: ['customers'],
        value_estimate: 'High',
        score_financial: 7,
        score_financial_rationale: '',
        score_financial_unit: '',
        score_manufactured: 5,
        score_manufactured_rationale: '',
        score_manufactured_unit: '',
        score_intellectual: 6,
        score_intellectual_rationale: '',
        score_intellectual_unit: '',
        score_human: 8,
        score_human_rationale: '',
        score_human_unit: '',
        score_social_relationship: 7,
        score_social_relationship_rationale: '',
        score_social_relationship_unit: '',
        score_natural: 3,
        score_natural_rationale: '',
        score_natural_unit: '',
        score_safety: 4,
        score_safety_rationale: '',
        score_safety_unit: '',
        score_performance: 8,
        score_performance_rationale: '',
        score_performance_unit: '',
        total_score: 6.5,
        weights_used: { financial: 1, manufactured: 1, intellectual: 1, human: 1, social_relationship: 1, natural: 1, safety: 1, performance: 1 },
      },
    ]),
    roadmapData: vi.fn().mockResolvedValue({
      periods: ['Q1 2026'],
      value_streams: ['Customer Experience'],
      stakeholder_groups: [],
      initiatives: [
        {
          id: 'i1',
          title: 'CRM Upgrade',
          description: 'Upgrade the CRM system',
          proposition_ids: [],
          capability_uplifts: [],
          initiative_type: 'enabler',
          enabler_dependencies: [],
          change_dependencies: [],
          complexity_score: 3,
          complexity_rationale: '',
          cost_estimate: { low: 100000, high: 150000, currency: 'GBP', rationale: '' },
          related_requirements: [],
          value_streams: ['Customer Experience'],
          period: 'Q1 2026',
        },
      ],
      propositions: [],
    }),
    outputs: vi.fn().mockResolvedValue([
      { id: 1, agent_name: 'business_plan_generator', output_type: 'docx', file_path: '/outputs/plan.docx', version: 1, review_status: 'approved', created_at: '2026-05-14T10:00:00' },
    ]),
  },
}))

vi.mock('../context/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAuth: () => ({ token: 'test-token', user: null, login: vi.fn(), logout: vi.fn() }),
}))

function renderReport() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={['/smoke-test/report']}>
          <Routes>
            <Route path="/:slug/report" element={<Report />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

describe('Report', () => {
  it('renders the project slug on the cover', async () => {
    renderReport()
    expect(await screen.findByText(/smoke-test/i)).toBeInTheDocument()
  })

  it('renders the financial summary section heading', async () => {
    renderReport()
    expect(await screen.findByText(/financial summary/i)).toBeInTheDocument()
  })

  it('renders value propositions section heading', async () => {
    renderReport()
    expect(await screen.findByText(/value propositions/i)).toBeInTheDocument()
  })

  it('renders initiative register section heading', async () => {
    renderReport()
    expect(await screen.findByText(/initiative register/i)).toBeInTheDocument()
  })

  it('renders document reference section heading', async () => {
    renderReport()
    expect(await screen.findByText(/deliverables/i)).toBeInTheDocument()
  })
})
