import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export const spring = { type: 'spring' as const, stiffness: 300, damping: 28 }

export const fmtMoney = (n: number) =>
  Math.abs(n) >= 1e6 ? `$${(n / 1e6).toFixed(2)}M` : Math.abs(n) >= 1e3 ? `$${(n / 1e3).toFixed(1)}K` : `$${n.toFixed(2)}`

export const fmtNum = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 })
