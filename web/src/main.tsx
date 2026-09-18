import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './styles/global.css'

const root = document.getElementById('root')
if (!root) throw new Error('未找到 #root 挂载点')

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
