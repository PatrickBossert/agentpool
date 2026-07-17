/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#19d4e8',
          light: '#7eedf6',
          dark: '#0fa8b8',
          green: '#47c247',
        },
        surface: {
          DEFAULT: '#f9fafb',
          raised: '#ffffff',
          card: '#ffffff',
        },
        primary:   '#111827',
        secondary: '#374151',
        muted:     '#4b5563',
      },
      keyframes: {
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        ekg: {
          '0%, 100%': { opacity: '0.25' },
          '50%': { opacity: '1' },
        },
        crewGlow: {
          '0%, 100%': { boxShadow: '0 0 16px #19d4e840, 0 0 40px #19d4e815' },
          '50%': { boxShadow: '0 0 28px #19d4e870, 0 0 60px #19d4e830' },
        },
        agentPulse: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.35' },
        },
        particleFlow: {
          '0%':   { top: '-4px', opacity: '0' },
          '10%':  { opacity: '1' },
          '90%':  { opacity: '1' },
          '100%': { top: 'calc(100% - 4px)', opacity: '0' },
        },
        scanline: {
          '0%':   { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(100%)' },
        },
        pamPulse: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.6' },
        },
      },
      animation: {
        blink:        'blink 1.2s step-end infinite',
        ekg:          'ekg 1.6s ease-in-out infinite',
        crewGlow:     'crewGlow 3s ease-in-out infinite',
        agentPulse:   'agentPulse 0.8s ease-in-out infinite',
        particleFlow: 'particleFlow 3s linear infinite',
        scanline:     'scanline 2s linear infinite',
        pamPulse:     'pamPulse 2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
