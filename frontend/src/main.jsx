import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { SavedPredictionsProvider } from './context/SavedPredictionsContext'
import { AuthProvider } from './context/AuthContext'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <SavedPredictionsProvider>
          <App />
        </SavedPredictionsProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
)
