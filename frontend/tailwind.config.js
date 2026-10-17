/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    // Include shared packages for class detection — @shizuha/ui installed from
    // the npm registry (canonical @shizuha/ui/vite boundary, ORIG-231/ORIG-324).
    "./node_modules/@shizuha/ui/dist/**/*.js",
    "/packages/shizuha-editor/src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Shizuha brand colors
        shizuha: {
          50: '#f0f9ff',
          100: '#e0f2fe',
          200: '#bae6fd',
          300: '#7dd3fc',
          400: '#38bdf8',
          500: '#0ea5e9',
          600: '#0284c7',
          700: '#0369a1',
          800: '#075985',
          900: '#0c4a6e',
          950: '#082f49',
        },
      },
      typography: (theme) => ({
        DEFAULT: {
          css: {
            maxWidth: 'none',
            color: theme('colors.gray.700'),
            a: {
              color: theme('colors.shizuha.600'),
              '&:hover': {
                color: theme('colors.shizuha.700'),
              },
            },
          },
        },
        dark: {
          css: {
            color: theme('colors.gray.100'),
            p: { color: theme('colors.gray.100') },
            li: { color: theme('colors.gray.100') },
            a: {
              color: theme('colors.shizuha.400'),
              '&:hover': {
                color: theme('colors.shizuha.300'),
              },
            },
            h1: { color: theme('colors.white') },
            h2: { color: theme('colors.white') },
            h3: { color: theme('colors.white') },
            h4: { color: theme('colors.white') },
            code: { color: theme('colors.gray.100') },
            strong: { color: theme('colors.white') },
            blockquote: {
              color: theme('colors.gray.300'),
              borderLeftColor: theme('colors.gray.600'),
            },
          },
        },
      }),
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
