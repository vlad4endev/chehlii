import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import '@ui/tokens.css'
import '@ui/base.css'
import './app.css'

import { App } from './App'
import { initMax } from './max'
import { initTelegram } from './telegram'

initTelegram()
initMax()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
