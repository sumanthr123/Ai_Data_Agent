import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'

export type ThemePref = 'system' | 'light' | 'dark'
const KEY = 'assistant.theme'

function read(): ThemePref {
  try {
    const t = localStorage.getItem(KEY)
    return t === 'light' || t === 'dark' ? t : 'system'
  } catch (err) {
    console.warn('Theme preference unavailable; following the system', err)
    return 'system'
  }
}

/** The resolved theme, for code that needs real colors (charts). Re-evaluates when the OS or the user's pick changes. */
function resolvedTheme(): 'light' | 'dark' {
  const forced = document.documentElement.dataset.theme
  if (forced === 'light' || forced === 'dark') return forced
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** Every caller sees the same resolved theme: it is read from the page (data-theme and the OS setting), not kept per hook. */
function subscribe(onChange: () => void) {
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  const observer = new MutationObserver(onChange)
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  media.addEventListener('change', onChange)
  return () => { observer.disconnect(); media.removeEventListener('change', onChange) }
}

export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(read)
  const resolved = useSyncExternalStore(subscribe, resolvedTheme)
  useEffect(() => {
    const root = document.documentElement
    if (pref === 'system') delete root.dataset.theme
    else root.dataset.theme = pref
    try {
      if (pref === 'system') localStorage.removeItem(KEY)
      else localStorage.setItem(KEY, pref)
    } catch (err) {
      console.warn('Theme preference not saved; it lasts for this session', err)
    }
  }, [pref])
  const cycle = useCallback(() => setPref((p) => (p === 'system' ? 'light' : p === 'light' ? 'dark' : 'system')), [])
  return { pref, resolved, cycle }
}

/** A CSS custom property's current value, so SVG charts and PNG export use the real theme colors. */
export const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()
