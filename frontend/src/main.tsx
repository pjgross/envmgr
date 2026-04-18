import React from 'react'
import ReactDOM from 'react-dom/client'
import { Provider } from 'react-redux'
import { ErrorBoundary } from 'react-error-boundary'
import { SnackbarProvider } from 'notistack'
import App from './App'
import { store } from './store'
import ThemedApp from './ThemedApp'
import ErrorFallback from './components/ErrorFallback'

ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
        <Provider store={store}>
            <ThemedApp>
                <SnackbarProvider
                    maxSnack={3}
                    anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                    autoHideDuration={4000}
                >
                    <ErrorBoundary FallbackComponent={ErrorFallback}>
                        <App />
                    </ErrorBoundary>
                </SnackbarProvider>
            </ThemedApp>
        </Provider>
    </React.StrictMode>,
)
