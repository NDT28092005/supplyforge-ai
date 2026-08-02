tailwind.config = {
  theme: {
    extend: {
      colors: {
        background: '#F8F9FA',
        surface: '#FFFFFF',
        'surface-hover': '#F1F5F9',
        primary: '#2C3E50',
        secondary: '#6C757D',
        accent: '#3498DB',
        'border-base': '#E2E8F0',
        danger: '#E74C3C',
        warn: '#F39C12',
        success: '#2ECC71',
      },
      fontFamily: {
        sans: ['Plus Jakarta Sans', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      letterSpacing: {
        tightest: '-0.04em',
      },
      boxShadow: {
        'material': '0 2px 8px -1px rgba(0, 0, 0, 0.08), 0 1px 4px -1px rgba(0, 0, 0, 0.04)',
        'material-lg': '0 10px 25px -3px rgba(0, 0, 0, 0.08), 0 4px 10px -2px rgba(0, 0, 0, 0.04)',
      }
    }
  }
}
