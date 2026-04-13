/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#7c6af7',
          light: '#c4b8ff',
          dark: '#5b4ed6',
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
