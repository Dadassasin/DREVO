import React from 'react';
import ReactDOM from 'react-dom/client';
import { HashRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './api';
import App from './App';
import './styles.css';

const client = new QueryClient({defaultOptions:{queries:{staleTime:15000,refetchOnWindowFocus:false}}});
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={client}><AuthProvider><HashRouter><App/></HashRouter></AuthProvider></QueryClientProvider></React.StrictMode>);
