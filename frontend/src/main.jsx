import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { SavedPredictionsProvider } from './context/SavedPredictionsContext'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <SavedPredictionsProvider>
        <App />
      </SavedPredictionsProvider>
    </BrowserRouter>
  </React.StrictMode>
)
