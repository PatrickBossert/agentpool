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
          DEFAULT: '#1a1825',
          raised: '#221f33',
          card: '#2a2640',
        },
      },
    },
  },
  plugins: [],
}
