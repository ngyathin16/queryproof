import { createRoot } from 'react-dom/client';
import { App } from './App';
import '@fontsource-variable/ibm-plex-sans';
import '@fontsource/ibm-plex-mono/400.css';
import './styles.css';

const root = document.getElementById('root');
if (root) createRoot(root).render(<App />);
