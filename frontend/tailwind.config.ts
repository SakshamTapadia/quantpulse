import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: '#0f1117',
        panel:   '#161b27',
        border:  '#1e2535',
        accent:  '#3b82f6',
        regime: {
          trending:      '#22c55e',
          mean_reverting:'#3b82f6',
          choppy:        '#f59e0b',
          high_vol:      '#ef4444',
        },
      },
      fontFamily: { mono: ['JetBrains Mono', 'monospace'] },
    },
  },
  plugins: [],
}
export default config
