import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'

// Every path opens the assistant, except /states: the gallery of every UI state on mock data.
const Root = window.location.pathname.startsWith('/states')
  ? lazy(() => import('./assistant/StatesGallery.tsx'))
  : lazy(() => import('./assistant/AssistantApp.tsx'))

createRoot(document.getElementById('root')!).render(<StrictMode><Suspense fallback={null}><Root /></Suspense></StrictMode>)
