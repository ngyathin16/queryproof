import { createRoot } from 'react-dom/client';
import { App } from './App';
import '@fontsource-variable/dm-sans';
import '@fontsource-variable/newsreader/standard-italic.css';
import './styles.css';

const root = document.getElementById('root');
if (root) createRoot(root).render(<App />);
