const withOpacity = (variable) => ({ opacityValue }) => {
  if (opacityValue === undefined) return `var(${variable})`
  const pct = Math.round(Number(opacityValue) * 100)
  if (isNaN(pct)) return `var(${variable})`
  return `color-mix(in oklab, var(${variable}) ${pct}%, transparent)`
}

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        border: withOpacity('--border'),
        input: withOpacity('--input'),
        ring: withOpacity('--ring'),
        background: withOpacity('--background'),
        foreground: withOpacity('--foreground'),
        card: {
          DEFAULT: withOpacity('--card'),
          foreground: withOpacity('--card-foreground'),
        },
        popover: {
          DEFAULT: withOpacity('--popover'),
          foreground: withOpacity('--popover-foreground'),
        },
        secondary: {
          DEFAULT: withOpacity('--secondary'),
          foreground: withOpacity('--secondary-foreground'),
        },
        muted: {
          DEFAULT: withOpacity('--muted'),
          foreground: withOpacity('--muted-foreground'),
        },
        destructive: {
          DEFAULT: withOpacity('--destructive'),
        },
        sidebar: {
          DEFAULT: withOpacity('--sidebar'),
          foreground: withOpacity('--sidebar-foreground'),
          primary: withOpacity('--sidebar-primary'),
          'primary-foreground': withOpacity('--sidebar-primary-foreground'),
          accent: withOpacity('--sidebar-accent'),
          'accent-foreground': withOpacity('--sidebar-accent-foreground'),
          border: withOpacity('--sidebar-border'),
          ring: withOpacity('--sidebar-ring'),
        },
        chart: {
          1: withOpacity('--chart-1'),
          2: withOpacity('--chart-2'),
          3: withOpacity('--chart-3'),
          4: withOpacity('--chart-4'),
          5: withOpacity('--chart-5'),
        },
        primary: {
          DEFAULT: withOpacity('--primary'),
          foreground: withOpacity('--primary-foreground'),
          50: 'rgb(var(--c-primary-50) / <alpha-value>)',
          100: 'rgb(var(--c-primary-100) / <alpha-value>)',
          200: 'rgb(var(--c-primary-200) / <alpha-value>)',
          300: 'rgb(var(--c-primary-300) / <alpha-value>)',
          400: 'rgb(var(--c-primary-400) / <alpha-value>)',
          500: 'rgb(var(--c-primary-500) / <alpha-value>)',
          600: 'rgb(var(--c-primary-600) / <alpha-value>)',
          700: 'rgb(var(--c-primary-700) / <alpha-value>)',
          800: 'rgb(var(--c-primary-800) / <alpha-value>)',
          900: 'rgb(var(--c-primary-900) / <alpha-value>)',
        },
        accent: {
          DEFAULT: withOpacity('--accent'),
          foreground: withOpacity('--accent-foreground'),
          50: '#f5f3ff',
          100: '#ede9fe',
          200: '#ddd6fe',
          400: '#a78bfa',
          500: '#8b5cf6',
          600: '#7c3aed',
          700: '#6d28d9',
        },
        surface: {
          50: '#fafafa',
          100: '#f5f5f5',
          200: '#e5e5e5',
          300: '#d4d4d4',
          700: '#404040',
          800: '#262626',
          900: '#171717',
        },
        ink: {
          50: '#fafafa',
          100: '#f4f4f5',
          200: '#e4e4e7',
          300: '#d4d4d8',
          400: '#a1a1aa',
          500: '#71717a',
          600: '#52525b',
          700: '#3f3f46',
          800: '#27272a',
          900: '#18181b',
        },
        sage: {
          50: '#f3f7f2',
          100: '#e0eadd',
          200: '#c2d5bc',
          400: '#7fb275',
          500: '#5c9451',
          600: '#47773e',
          700: '#385f32',
        },
      },
      fontFamily: {
        serif: ['"DM Serif Display"', 'Georgia', 'serif'],
        sans: ['Figtree', 'Outfit', 'system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        'card': '0 1px 3px 0 rgb(0 0 0 / 0.05), 0 1px 2px -1px rgb(0 0 0 / 0.03)',
        'card-hover': '0 8px 24px -4px rgb(0 0 0 / 0.08), 0 2px 6px -2px rgb(0 0 0 / 0.03)',
        'card-active': '0 1px 2px 0 rgb(0 0 0 / 0.04)',
        'glow': '0 0 24px -6px rgb(var(--c-glow) / 0.25)',
        'glow-sm': '0 0 12px -4px rgb(var(--c-glow) / 0.2)',
        'glass': '0 8px 32px rgba(0, 0, 0, 0.1)',
        'glass-dark': '0 8px 32px rgba(0, 0, 0, 0.35)',
        'warm': '0 4px 16px -2px rgb(var(--c-glow) / 0.15)',
        'inner-glow': 'inset 0 1px 2px 0 rgb(var(--c-glow) / 0.1)',
      },
      borderRadius: {
        'xl': '0.875rem',
        '2xl': '1rem',
        '3xl': '1.25rem',
      },
      animation: {
        'fade-in': 'fadeIn 0.4s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'slide-down': 'slideDown 0.25s ease-out',
        'shimmer': 'shimmer 2s infinite linear',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'float': 'float 6s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideDown: {
          '0%': { opacity: '0', transform: 'translateY(-6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-8px)' },
        },
      },
      backgroundImage: {
        'shimmer': 'linear-gradient(90deg, transparent 0%, rgb(255 255 255 / 0.5) 50%, transparent 100%)',
        'gradient-brand': 'linear-gradient(135deg, rgb(var(--c-primary-500)) 0%, rgb(var(--c-primary-600)) 50%, rgb(var(--c-primary-700)) 100%)',
        'gradient-warm': 'linear-gradient(135deg, #f3f1ed 0%, #faf9f7 100%)',
      },
    },
  },
  plugins: [require('@tailwindcss/container-queries')],
}
