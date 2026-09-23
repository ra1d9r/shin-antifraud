import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import { LanguageProvider } from './LanguageContext'
import './styles.css'

const container = document.getElementById('root')
if (!container) throw new Error('Не найден элемент #root')

createRoot(container).render(
  <StrictMode>
    <LanguageProvider>
      <App />
    </LanguageProvider>
  </StrictMode>,
)
