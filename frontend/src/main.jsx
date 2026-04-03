import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { SavedPredictionsProvider } from './context/SavedPredictionsContext'
import { AuthProvider } from './context/AuthContext'
import { FeatureProvider } from './context/FeatureContext'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <FeatureProvider>
          <SavedPredictionsProvider>
            <App />
          </SavedPredictionsProvider>
        </FeatureProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
)
// Build trigger 1775084771
