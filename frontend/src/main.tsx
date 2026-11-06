import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'

// Every path (including the old /council) opens the assistant; "Verify with council" runs the council on demand.
const Root = lazy(() => import('./assistant/AssistantApp.tsx'))

createRoot(document.getElementById('root')!).render(<StrictMode><Suspense fallback={null}><Root /></Suspense></StrictMode>)
