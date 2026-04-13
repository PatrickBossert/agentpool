// ui/src/__tests__/Login.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../context/AuthContext'
import Login from '../pages/Login'

// Mock the API
vi.mock('../api/endpoints', () => ({
  authApi: {
    login: vi.fn().mockResolvedValue({ access_token: 'test-token', token_type: 'bearer' }),
  },
}))

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <MemoryRouter>{children}</MemoryRouter>
    </AuthProvider>
  )
}

describe('Login', () => {
  it('renders username and password fields', () => {
    render(<Login />, { wrapper: Wrapper })
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('submits credentials and stores token', async () => {
    render(<Login />, { wrapper: Wrapper })
    await userEvent.type(screen.getByLabelText(/username/i), 'admin')
    await userEvent.type(screen.getByLabelText(/password/i), 'password')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    expect(localStorage.getItem('ap_token')).toBe('test-token')
  })

  it('shows error on failed login', async () => {
    const { authApi } = await import('../api/endpoints')
    vi.mocked(authApi.login).mockRejectedValueOnce(new Error('401'))
    render(<Login />, { wrapper: Wrapper })
    await userEvent.type(screen.getByLabelText(/username/i), 'admin')
    await userEvent.type(screen.getByLabelText(/password/i), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
