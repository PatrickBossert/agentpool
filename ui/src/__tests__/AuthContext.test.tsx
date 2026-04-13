import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AuthProvider, useAuth } from '../context/AuthContext'

function TestConsumer() {
  const { token, login, logout } = useAuth()
  return (
    <div>
      <span data-testid="token">{token ?? 'none'}</span>
      <button onClick={() => login('fake-token', { sub: 'admin', role: 'consultant' })}>
        Login
      </button>
      <button onClick={logout}>Logout</button>
    </div>
  )
}

describe('AuthContext', () => {
  beforeEach(() => localStorage.clear())

  it('starts with no token', () => {
    render(<AuthProvider><TestConsumer /></AuthProvider>)
    expect(screen.getByTestId('token').textContent).toBe('none')
  })

  it('login stores token', async () => {
    render(<AuthProvider><TestConsumer /></AuthProvider>)
    await userEvent.click(screen.getByText('Login'))
    expect(screen.getByTestId('token').textContent).toBe('fake-token')
    expect(localStorage.getItem('ap_token')).toBe('fake-token')
  })

  it('logout clears token', async () => {
    render(<AuthProvider><TestConsumer /></AuthProvider>)
    await userEvent.click(screen.getByText('Login'))
    await userEvent.click(screen.getByText('Logout'))
    expect(screen.getByTestId('token').textContent).toBe('none')
    expect(localStorage.getItem('ap_token')).toBeNull()
  })
})
