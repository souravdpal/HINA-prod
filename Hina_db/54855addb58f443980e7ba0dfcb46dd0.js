/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#f0fdf4',
          100: '#dcfce7',
          500: '#22c55e',
          600: '#16a34a',
          700: '#15803d',
          950: '#052e16',
        },
        dark: {
          50: '#f6f6f6',
          100: '#e7e7e7',
          800: '#1e1e24',
          900: '#121214',
          950: '#0a0a0c',
        }
      },
    },
  },
  plugins: [],
}
