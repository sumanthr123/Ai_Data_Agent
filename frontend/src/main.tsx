import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'

// "/" is the governed assistant (/api/ask); "/council" keeps the classic multi-model chat. Each loads only its own code.
const Root = window.location.pathname.startsWith('/council') ? lazy(() => import('./App.tsx')) : lazy(() => import('./assistant/AssistantApp.tsx'))

createRoot(document.getElementById('root')!).render(<StrictMode><Suspense fallback={null}><Root /></Suspense></StrictMode>)
